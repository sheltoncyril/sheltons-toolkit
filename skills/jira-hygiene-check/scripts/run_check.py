#!/usr/bin/env python3
"""Jira Hygiene Check — single-command orchestrator.

Agent dumps tickets JSON from MCP, then runs THIS script. Script handles:
  1. PR correlation via gh CLI (for all Review/In Progress/Closed tickets)
  2. Sprint membership vetting
  3. All rule evaluation (GEN, WF, PR, FV, CF, RES + Appendix A matrix)
  4. Report formatting (markdown + JSON)

Usage:
    python3 run_check.py \
        --tickets /tmp/tickets.json \
        --config config.env \
        --resources-dir <skill-dir>/resources \
        --project RHOAIENG \
        --scope "My tickets — Active Sprint" \
        --user "Shelton Cyril" \
        [--output-dir ~/jira-hygiene-reports] \
        [--freeze-dates "rhoai-3.5:2026-07-24,rhoai-3.6:2026-10-23"]

Input:
    --tickets: JSON file — either a single MCP response with issues.nodes array,
               or a raw JSON array of ticket objects with "key" and "fields".
    --freeze-dates: Override freeze dates (from Product Pages refresh).
                    If omitted, uses FREEZE_DATES from config.env.

Output:
    stdout: Markdown report (agent displays this directly)
    stderr: Progress messages
    --output-dir: If set, saves .md and .json report files
    Exit code 0 = success, exit code 1 = error
"""

import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


def load_json(path):
    with open(path) as f:
        return json.load(f)


def load_config(path):
    config = {}
    if not path or not Path(path).exists():
        return config
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                config[key.strip()] = value.strip()
    return config


def get_field(ticket, field_path, default=None):
    parts = field_path.split(".")
    obj = ticket
    for part in parts:
        if isinstance(obj, dict):
            obj = obj.get(part, default)
        else:
            return default
    return obj


def is_empty(value):
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    if isinstance(value, list) and len(value) == 0:
        return True
    return False


def days_since(date_str):
    if not date_str:
        return float("inf")
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).days
    except (ValueError, TypeError):
        return float("inf")


def parse_freeze_dates(freeze_str):
    if not freeze_str:
        return {}
    dates = {}
    for pair in freeze_str.split(","):
        pair = pair.strip()
        if ":" in pair:
            version, date_str = pair.split(":", 1)
            dates[version.strip()] = date_str.strip()
    return dates


# --- PR Correlation ---

def run_cmd(cmd, timeout=30):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip() if r.returncode == 0 else None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def has_tool(name):
    return run_cmd(["which", name]) is not None


def fetch_prs_for_ticket(key, github_repos):
    prs = []
    for repo in github_repos:
        repo = repo.strip()
        if not repo:
            continue
        output = run_cmd([
            "gh", "pr", "list", "--repo", repo, "--search", key,
            "--state", "all", "--json",
            "number,title,state,headRefName,mergedAt,isDraft,body,url,reviews",
            "--limit", "20",
        ], timeout=15)
        if not output:
            continue
        try:
            for pr in json.loads(output):
                has_cr = any(
                    r.get("state") == "CHANGES_REQUESTED"
                    for r in pr.get("reviews", []) if isinstance(r, dict)
                )
                state = pr.get("state", "").lower()
                if pr.get("mergedAt"):
                    state = "merged"
                elif state == "closed":
                    state = "closed"
                else:
                    state = "open"
                prs.append({
                    "url": pr.get("url", ""),
                    "number": pr.get("number"),
                    "title": pr.get("title", ""),
                    "state": state,
                    "draft": pr.get("isDraft", False),
                    "branch": pr.get("headRefName", ""),
                    "mergedAt": pr.get("mergedAt"),
                    "changes_requested": has_cr,
                    "body": pr.get("body", ""),
                    "repo": repo,
                })
        except json.JSONDecodeError:
            continue
    return prs


def correlate_prs(tickets, config):
    gh_available = has_tool("gh")
    github_repos = [r for r in config.get("GITHUB_REPOS", "").split(",") if r.strip()]
    pr_enabled = config.get("PR_CHECK_ENABLED", "false").lower() == "true"

    pr_cache = {}
    pr_skipped = False

    if not pr_enabled:
        print("[run_check] PR checking disabled in config", file=sys.stderr)
        return pr_cache, True

    if not gh_available:
        print("[run_check] gh CLI not available — PR rules will report 'unable to verify'", file=sys.stderr)
        return pr_cache, True

    if not github_repos:
        print("[run_check] No GitHub repos configured — PR rules will report 'unable to verify'", file=sys.stderr)
        return pr_cache, True

    check_statuses = {"In Progress", "Review", "Closed"}
    tickets_to_check = [t for t in tickets if get_field(t, "fields.status.name", "") in check_statuses]

    print(f"[run_check] Checking PRs for {len(tickets_to_check)} tickets across {len(github_repos)} repos", file=sys.stderr)

    for t in tickets_to_check:
        key = t["key"]
        if key in pr_cache:
            continue
        prs = fetch_prs_for_ticket(key, github_repos)
        pr_cache[key] = prs
        status = "found" if prs else "none"
        print(f"  {key}: {len(prs)} PRs {status}", file=sys.stderr)

    return pr_cache, False


# --- Sprint Vetting ---

def vet_sprints(tickets):
    findings = []
    for t in tickets:
        status = get_field(t, "fields.status.name", "")
        if status != "In Progress":
            continue

        key = t["key"]
        sprint_field = get_field(t, "fields.customfield_10020") or get_field(t, "fields.sprint")
        in_active_sprint = False

        if isinstance(sprint_field, list):
            for s in sprint_field:
                if isinstance(s, dict) and s.get("state") == "active":
                    in_active_sprint = True
                    break
        elif isinstance(sprint_field, dict) and sprint_field.get("state") == "active":
            in_active_sprint = True

        if not in_active_sprint:
            findings.append({
                "key": key,
                "summary": get_field(t, "fields.summary", "")[:80],
                "finding": "In Progress but not in any active sprint",
                "type": "SPRINT-VET",
            })

    return findings


# --- Rule Evaluation ---

def evaluate_ticket(ticket, rules_by_id, matrix, version_patterns, pr_data, config, freeze_dates):
    key = ticket.get("key", "UNKNOWN")
    f = ticket.get("fields", {})
    status = get_field(ticket, "fields.status.name", "")
    issue_type = get_field(ticket, "fields.issuetype.name", "")
    assignee_obj = get_field(ticket, "fields.assignee")
    assignee_name = None
    if isinstance(assignee_obj, dict):
        assignee_name = assignee_obj.get("displayName") or assignee_obj.get("emailAddress")

    result = {
        "key": key,
        "summary": get_field(ticket, "fields.summary", "")[:80],
        "status": status,
        "assignee": assignee_name,
        "issue_type": issue_type,
        "exempt": False,
        "violations": [],
    }

    labels = get_field(ticket, "fields.labels", [])
    if "hygiene-bot-ignore" in labels:
        result["exempt"] = True
        return result

    violations = []
    priority = get_field(ticket, "fields.priority")
    priority_name = priority.get("name", "") if isinstance(priority, dict) else ""
    components = get_field(ticket, "fields.components", [])
    fix_versions = get_field(ticket, "fields.fixVersions", [])
    description = get_field(ticket, "fields.description", "")
    updated = get_field(ticket, "fields.updated", "")
    resolution = get_field(ticket, "fields.resolution")
    versions = get_field(ticket, "fields.versions", [])
    severity = get_field(ticket, "fields.customfield_12316142")
    staleness_days = int(config.get("STALENESS_DAYS", "14"))
    workflow_order = [s.strip() for s in config.get("WORKFLOW_STATUSES", "New,Refinement,To Do,In Progress,Review,Closed").split(",")]

    def add(rule_id, severity, message, auto_fixable=False, fix_action=None, fix_desc=""):
        rule_def = rules_by_id.get(rule_id, {})
        violations.append({
            "rule_id": rule_id,
            "category": rule_def.get("category", rule_id.split("-")[0]),
            "severity": severity,
            "title": rule_def.get("title", ""),
            "message": message,
            "auto_fixable": auto_fixable,
            "fix_action": fix_action,
            "fix_description": fix_desc or rule_def.get("fix_description", ""),
        })

    # GEN-1: unassigned in sprint
    sprint_field = get_field(ticket, "fields.customfield_10020") or get_field(ticket, "fields.sprint")
    in_sprint = False
    if isinstance(sprint_field, list) and sprint_field:
        in_sprint = True
    elif sprint_field is not None:
        in_sprint = True
    if in_sprint and is_empty(assignee_obj):
        add("GEN-1", "high", f"{key} is in a sprint but has no assignee", True, "set_assignee")

    # GEN-2: empty description
    desc_len = len(str(description)) if description else 0
    if isinstance(description, dict):
        desc_len = len(json.dumps(description))
    if desc_len < 20:
        add("GEN-2", "medium", f"{key} has empty or very short description ({desc_len} chars)")

    # GEN-3: missing component
    if is_empty(components):
        add("GEN-3", "high", f"{key} has no component set", True, "set_component")

    # GEN-4: default priority
    if priority_name in ("Normal", "Undefined", "") or is_empty(priority):
        add("GEN-4", "medium", f"{key} has priority '{priority_name or 'none'}' — set explicit priority", True, "set_priority")

    # GEN-5: bug missing severity/affects version
    if issue_type.lower() == "bug":
        missing = []
        if is_empty(versions):
            missing.append("Affects Version")
        if is_empty(severity):
            missing.append("Severity")
        if missing:
            add("GEN-5", "high", f"Bug {key} missing: {', '.join(missing)}")

    # GEN-6: stale In Progress
    if status == "In Progress":
        days = days_since(updated)
        if days > staleness_days:
            add("GEN-6", "medium", f"{key} In Progress for {days} days without update (threshold: {staleness_days})")

    # WF-7: skipped transitions (needs changelog)
    changelog = get_field(ticket, "changelog.histories", [])
    if changelog:
        for history in changelog:
            for item in history.get("items", []):
                if item.get("field") == "status":
                    from_s = item.get("fromString", "")
                    to_s = item.get("toString", "")
                    if from_s in workflow_order and to_s in workflow_order:
                        fi = workflow_order.index(from_s)
                        ti = workflow_order.index(to_s)
                        if ti > fi + 1:
                            skipped = workflow_order[fi + 1:ti]
                            add("WF-7", "high", f"{key} skipped: {from_s} -> {to_s} (skipped: {', '.join(skipped)})")
                            break

    # FV-1: merged PR or Closed but no fixVersion
    if is_empty(fix_versions):
        has_merged = any(pr.get("state") == "merged" or pr.get("mergedAt") for pr in (pr_data or []))
        if has_merged or status == "Closed":
            add("FV-1", "high", f"{key} has merged PRs/is Closed but no fixVersion", True, "set_fix_version")

    # FV-6: released versions (info)
    for fv in fix_versions:
        if isinstance(fv, dict) and fv.get("released"):
            add("FV-6", "info", f"{key} references released version: {fv.get('name', '?')}")

    # FV-7: version naming
    if version_patterns and fix_versions:
        for fv in fix_versions:
            name = fv.get("name", "") if isinstance(fv, dict) else str(fv)
            if not any(p.match(name) for p in version_patterns):
                add("FV-7", "low", f"{key} has non-standard fixVersion: '{name}'")

    # CF-2/CF-4: code freeze checks
    if freeze_dates:
        today = datetime.now(timezone.utc).date()
        for fv in fix_versions:
            fv_name = fv.get("name", "") if isinstance(fv, dict) else str(fv)
            for freeze_ver, freeze_date_str in freeze_dates.items():
                if freeze_ver.lower() in fv_name.lower():
                    try:
                        freeze_date = datetime.strptime(freeze_date_str, "%Y-%m-%d").date()
                    except ValueError:
                        continue
                    days_until = (freeze_date - today).days
                    if days_until < 0 and status != "Closed":
                        add("CF-2", "critical", f"{key} targets frozen version {freeze_ver} (froze {-days_until} days ago) but status is {status}")
                    elif 0 <= days_until <= 3 and status != "Closed":
                        add("CF-4", "high", f"{key} targets {freeze_ver} — code freeze in {days_until} days, status is {status}")

    # RES-2: closed without resolution
    if status == "Closed" and is_empty(resolution):
        add("RES-2", "high", f"{key} is Closed but has no resolution", True, "set_resolution")

    # RES-3: won't fix/duplicate without comment
    if resolution:
        res_name = resolution.get("name", "") if isinstance(resolution, dict) else str(resolution)
        if res_name in ("Won't Fix", "Duplicate", "Won't Do"):
            comments = get_field(ticket, "fields.comment.comments", [])
            if not comments:
                add("RES-3", "medium", f"{key} resolved as {res_name} but has no explanation comment")

    # RES-4: bug/story closed without QA sign-off
    if status == "Closed" and issue_type.lower() in ("bug", "story"):
        qa = get_field(ticket, "fields.customfield_12319940")
        if is_empty(qa):
            add("RES-4", "high", f"{issue_type} {key} is Closed but QA sign-off is not set")

    # PR-based rules (WF-1 through WF-5, PR-1 through PR-4)
    if pr_data is not None:
        has_any = len(pr_data) > 0
        has_ready = any(p["state"] == "open" and not p.get("draft") and not p.get("changes_requested") for p in pr_data)
        has_draft_only = all(p.get("draft") for p in pr_data if p["state"] == "open") and any(p["state"] == "open" for p in pr_data)
        has_cr = any(p.get("changes_requested") for p in pr_data)
        all_merged = has_any and all(p["state"] == "merged" or p.get("mergedAt") for p in pr_data)
        has_closed_no_merge = any(p["state"] == "closed" and not p.get("mergedAt") for p in pr_data)

        status_idx = workflow_order.index(status) if status in workflow_order else -1
        ip_idx = workflow_order.index("In Progress") if "In Progress" in workflow_order else -1

        if has_any and ip_idx >= 0 and status_idx < ip_idx:
            add("WF-1", "high", f"{key} has PRs but status '{status}' is before In Progress", True, "transition_forward")

        if status == "Review" and has_draft_only and not has_cr:
            add("WF-2", "high", f"{key} is in Review but PR is still Draft — status is ahead of PR state")

        if has_ready and status != "Review" and status != "Closed" and not has_cr:
            add("WF-2", "high", f"{key} has PR ready for review but status is '{status}'", True, "transition_to_review")

        if has_cr and status != "In Progress":
            add("WF-3", "medium", f"{key} has changes requested but status is '{status}'", True, "transition_to_in_progress")

        if all_merged and status != "Closed":
            add("WF-4", "high", f"{key} has all PRs merged but status is '{status}'")

        if has_closed_no_merge:
            add("WF-5", "medium", f"{key} has PR(s) closed without merge")

        for pr in pr_data:
            branch = pr.get("branch", "")
            title = pr.get("title", "")
            if key.upper() not in branch.upper() and key.upper() not in title.upper():
                add("PR-1", "medium", f"PR {pr.get('url', '?')} branch/title missing ticket key {key}")
                break

        if not has_any and status in ("In Progress", "Review"):
            add("PR-2", "medium", f"{key} is {status} but has no linked PRs")

        if len(pr_data) > 5:
            add("PR-3", "low", f"{key} has {len(pr_data)} PRs — consider splitting")

        for pr in pr_data:
            t_lower = pr.get("title", "").lower()
            body = pr.get("body", "") or ""
            if "backport" in t_lower or "cherry-pick" in t_lower:
                if "cherry picked from commit" not in body.lower():
                    add("PR-4", "medium", f"Backport PR {pr.get('url', '?')} missing cherry-pick reference")
                    break

    # Required fields matrix
    type_matrix = matrix.get("matrix", {}).get(issue_type, {})
    required = type_matrix.get(status, [])
    field_mappings = matrix.get("field_mappings", {})
    missing_fields = []
    for fname in required:
        if fname == "pr_link":
            continue
        fpath = field_mappings.get(fname, f"fields.{fname}")
        if is_empty(get_field(ticket, fpath)):
            missing_fields.append(fname)
    if missing_fields:
        add("MATRIX", "high", f"{key} ({issue_type}/{status}) missing required fields: {', '.join(missing_fields)}")

    result["violations"] = violations
    return result


# --- Report Formatting ---

def format_report(results, sprint_vetting, summary, freeze_dates, freeze_source, user_name):
    lines = []
    lines.append("## Jira Hygiene Report\n")
    lines.append(f"**User:** {user_name}")
    lines.append(f"**Scope:** {summary['scope']}")
    lines.append(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")

    if freeze_dates:
        today = datetime.now(timezone.utc).date()
        upcoming = []
        for ver, ds in sorted(freeze_dates.items()):
            try:
                fd = datetime.strptime(ds, "%Y-%m-%d").date()
                days = (fd - today).days
                if days >= 0:
                    upcoming.append(f"{ver}: {ds} ({days} days)")
            except ValueError:
                pass
        if upcoming:
            lines.append(f"**Freeze dates:** {upcoming[0]} — from {freeze_source}")

    lines.append(f"**Checked:** {summary['total']} | **Exempt:** {summary['exempt']} | **Clean:** {summary['clean']} | **Violations:** {summary['with_violations']}")
    if summary.get("pr_skipped"):
        lines.append("**Warning:** PR correlation was unavailable — WF/PR rules not checked")
    lines.append("")

    if summary["total"] == 0:
        lines.append("No tickets found.\n")
        return "\n".join(lines)

    if summary["with_violations"] == 0 and not sprint_vetting:
        lines.append("All tickets clean. No violations found.\n")
        return "\n".join(lines)

    # Sprint vetting
    if sprint_vetting:
        lines.append("### Sprint Vetting\n")
        lines.append(f"**{len(sprint_vetting)} tickets In Progress but NOT in any active sprint:**\n")
        lines.append("| Ticket | Summary | Finding |")
        lines.append("|--------|---------|---------|")
        for sv in sprint_vetting:
            link = f"[{sv['key']}](https://redhat.atlassian.net/browse/{sv['key']})"
            lines.append(f"| {link} | {sv['summary'][:50]} | {sv['finding']} |")
        lines.append("")

    # Violations by category
    all_v = []
    for r in results:
        if not r["exempt"]:
            all_v.extend(r["violations"])

    if all_v:
        cat_counts = Counter(v["rule_id"] for v in all_v)
        cat_group = Counter(v["rule_id"].split("-")[0] for v in all_v)

        lines.append("### Violations by Rule\n")
        lines.append("| Rule | Count | Severity | Auto-fixable |")
        lines.append("|------|-------|----------|-------------|")
        for rule_id, count in cat_counts.most_common():
            sev = next((v["severity"] for v in all_v if v["rule_id"] == rule_id), "?")
            auto = "Yes" if any(v.get("auto_fixable") for v in all_v if v["rule_id"] == rule_id) else "No"
            lines.append(f"| {rule_id} | {count} | {sev} | {auto} |")
        lines.append("")

    # Per-ticket detail
    violation_tickets = [r for r in results if r["violations"] and not r["exempt"]]
    if violation_tickets:
        lines.append("### Per-Ticket Detail\n")
        for r in sorted(violation_tickets, key=lambda x: -len(x["violations"])):
            key = r["key"]
            link = f"[{key}](https://redhat.atlassian.net/browse/{key})"
            lines.append(f"#### {link} — {r['summary']}\n")
            lines.append(f"**{r['issue_type']}** | **{r['status']}** | **{r['assignee'] or 'unassigned'}**\n")
            lines.append("| # | Rule | Severity | Violation | Auto-fix |")
            lines.append("|---|------|----------|-----------|----------|")
            for i, v in enumerate(r["violations"], 1):
                auto = "Yes" if v.get("auto_fixable") else "No"
                lines.append(f"| {i} | {v['rule_id']} | {v['severity']} | {v['message']} | {auto} |")
            lines.append("")

    # Exempt
    exempt_tickets = [r for r in results if r["exempt"]]
    if exempt_tickets:
        lines.append("### Exempt Tickets (hygiene-bot-ignore)\n")
        lines.append("| Ticket | Summary |")
        lines.append("|--------|---------|")
        for r in exempt_tickets:
            link = f"[{r['key']}](https://redhat.atlassian.net/browse/{r['key']})"
            lines.append(f"| {link} | {r['summary']} |")
        lines.append("")

    return "\n".join(lines)


# --- Main ---

def main():
    parser = argparse.ArgumentParser(description="Jira Hygiene Check — full orchestrator")
    parser.add_argument("--tickets", required=True, help="Path to tickets JSON (MCP response or array)")
    parser.add_argument("--config", required=True, help="Path to config.env")
    parser.add_argument("--resources-dir", required=True, help="Path to resources/ directory")
    parser.add_argument("--project", default="UNKNOWN", help="Project key")
    parser.add_argument("--scope", default="Manual check", help="Scope description for report header")
    parser.add_argument("--user", default="Unknown", help="User display name")
    parser.add_argument("--output-dir", help="Save reports to this directory")
    parser.add_argument("--freeze-dates", help="Override freeze dates (version:date,version:date)")
    args = parser.parse_args()

    config = load_config(args.config)
    res_dir = Path(args.resources_dir)

    rules = load_json(res_dir / "hygiene-rules.json")
    matrix = load_json(res_dir / "appendix-a-matrix.json")
    versions_data = load_json(res_dir / "appendix-b-versions.json")
    version_patterns = [re.compile(p["regex"]) for p in versions_data.get("patterns", [])]

    rules_by_id = {r["id"]: r for r in rules.get("rules", [])}

    # Parse tickets
    raw = load_json(args.tickets)
    if isinstance(raw, dict) and "issues" in raw:
        tickets = raw["issues"].get("nodes", [])
    elif isinstance(raw, list):
        tickets = raw
    else:
        tickets = [raw]

    print(f"[run_check] {len(tickets)} tickets loaded", file=sys.stderr)

    # Freeze dates
    freeze_str = args.freeze_dates or config.get("FREEZE_DATES", "")
    freeze_dates = parse_freeze_dates(freeze_str)
    freeze_source = "Product Pages" if args.freeze_dates else config.get("FREEZE_SOURCE", "config.env")
    if freeze_dates:
        print(f"[run_check] {len(freeze_dates)} freeze dates loaded from {freeze_source}", file=sys.stderr)

    # PR correlation
    pr_cache, pr_skipped = correlate_prs(tickets, config)

    # Sprint vetting
    sprint_vetting = vet_sprints(tickets)
    if sprint_vetting:
        print(f"[run_check] {len(sprint_vetting)} sprint vetting findings", file=sys.stderr)

    # Evaluate all tickets
    results = []
    for t in tickets:
        key = t.get("key", "?")
        pr_data = pr_cache.get(key) if not pr_skipped else None
        result = evaluate_ticket(t, rules_by_id, matrix, version_patterns, pr_data, config, freeze_dates)
        results.append(result)

    # Summary
    total = len(results)
    exempt = sum(1 for r in results if r["exempt"])
    with_v = sum(1 for r in results if r["violations"] and not r["exempt"])
    clean = total - exempt - with_v

    summary = {
        "scope": args.scope,
        "total": total,
        "exempt": exempt,
        "clean": clean,
        "with_violations": with_v,
        "pr_skipped": pr_skipped,
    }

    # Format report
    markdown = format_report(results, sprint_vetting, summary, freeze_dates, freeze_source, args.user)
    print(markdown)

    # Save reports
    if args.output_dir:
        out_dir = Path(args.output_dir).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y-%m-%d")
        scope_slug = re.sub(r"[^a-z0-9-]", "", args.scope.lower().replace(" ", "-"))[:30]
        base = f"{args.project}-{date_str}-{scope_slug}"

        with open(out_dir / f"{base}.md", "w") as f:
            f.write(markdown)
        with open(out_dir / f"{base}.json", "w") as f:
            json.dump({
                "version": 1,
                "generated": datetime.now().isoformat(),
                "summary": summary,
                "sprint_vetting": sprint_vetting,
                "tickets": results,
            }, f, indent=2)
        print(f"\n[run_check] Reports saved to {out_dir / base}.*", file=sys.stderr)

    # Print fix summary to stderr for agent to parse
    fixable = []
    for r in results:
        for v in r.get("violations", []):
            if v.get("auto_fixable"):
                fixable.append({"key": r["key"], "rule_id": v["rule_id"], "fix_action": v.get("fix_action", ""), "message": v["message"]})

    if fixable:
        print(f"\n[FIXABLE] {len(fixable)} auto-fixable violations:", file=sys.stderr)
        for f in fixable:
            print(f"  {f['key']} | {f['rule_id']} | {f['fix_action']} | {f['message']}", file=sys.stderr)


if __name__ == "__main__":
    main()
