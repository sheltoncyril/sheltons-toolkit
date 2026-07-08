#!/usr/bin/env python3
"""Core rule evaluation engine for Jira Hygiene Checker.

Evaluates a single Jira ticket against hygiene rules and returns violations.

Usage (from SKILL.md — the skill calls this per ticket):
    python3 evaluate_rules.py --ticket ticket.json --rules hygiene-rules.json \
        --matrix appendix-a-matrix.json --versions appendix-b-versions.json \
        [--pr-data pr_data.json] [--config config.env] [--staleness-days 14]

Input:
    --ticket: JSON file with full Jira issue fields (from MCP getJiraIssue)
    --rules: hygiene-rules.json resource file
    --matrix: appendix-a-matrix.json required fields matrix
    --versions: appendix-b-versions.json fixVersion naming patterns
    --pr-data: Optional JSON with PR correlation data (from pr_correlator.py)
    --config: Optional config.env for freeze dates, workflow statuses
    --staleness-days: Override default staleness threshold (default: 14)

Output (stdout, JSON):
    {
        "key": "AIPCC-1234",
        "summary": "...",
        "status": "In Progress",
        "assignee": "user@example.com" | null,
        "issue_type": "Bug",
        "exempt": false,
        "violations": [
            {
                "rule_id": "GEN-1",
                "category": "General",
                "severity": "high",
                "title": "Active sprint tickets must have assignee",
                "message": "Ticket AIPCC-1234 is in an active sprint but has no assignee",
                "auto_fixable": true,
                "fix_action": "set_assignee",
                "fix_description": "Set assignee on the ticket"
            }
        ]
    }
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
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


def is_empty_or_none(value):
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
        now = datetime.now(timezone.utc)
        return (now - dt).days
    except (ValueError, TypeError):
        return float("inf")


def check_gen_1(ticket, rule, config):
    """GEN-1: Active sprint tickets must have assignee."""
    assignee = get_field(ticket, "fields.assignee")
    sprint_field = get_field(ticket, "fields.sprint") or get_field(ticket, "fields.customfield_10020")
    in_sprint = sprint_field is not None
    if not in_sprint and isinstance(sprint_field, list):
        in_sprint = len(sprint_field) > 0

    if in_sprint and is_empty_or_none(assignee):
        return {
            "rule_id": "GEN-1",
            "message": f"Ticket {ticket['key']} is in an active sprint but has no assignee",
        }
    return None


def check_gen_2(ticket, rule, config):
    """GEN-2: Description must not be empty/trivially short."""
    description = get_field(ticket, "fields.description", "")
    if isinstance(description, dict):
        content = json.dumps(description)
        if len(content) < 50:
            return {
                "rule_id": "GEN-2",
                "message": f"Ticket {ticket['key']} has a very short or empty description",
            }
    elif is_empty_or_none(description) or len(str(description).strip()) < 20:
        return {
            "rule_id": "GEN-2",
            "message": f"Ticket {ticket['key']} has an empty or very short description",
        }
    return None


def check_gen_3(ticket, rule, config):
    """GEN-3: Must have component."""
    components = get_field(ticket, "fields.components", [])
    if is_empty_or_none(components):
        return {
            "rule_id": "GEN-3",
            "message": f"Ticket {ticket['key']} has no component set",
        }
    return None


def check_gen_4(ticket, rule, config):
    """GEN-4: Priority must be explicitly set (not default)."""
    priority = get_field(ticket, "fields.priority")
    if is_empty_or_none(priority):
        return {
            "rule_id": "GEN-4",
            "message": f"Ticket {ticket['key']} has no priority set",
        }
    priority_name = priority.get("name", "") if isinstance(priority, dict) else str(priority)
    default_values = rule.get("default_values", ["Normal", None])
    if priority_name in default_values:
        return {
            "rule_id": "GEN-4",
            "message": f"Ticket {ticket['key']} has default priority '{priority_name}' — set an explicit priority",
        }
    return None


def check_gen_5(ticket, rule, config):
    """GEN-5: Bugs must have Affects Version and severity."""
    issue_type = get_field(ticket, "fields.issuetype.name", "")
    if issue_type.lower() != "bug":
        return None

    versions = get_field(ticket, "fields.versions", [])
    severity = get_field(ticket, "fields.customfield_12316142")

    missing = []
    if is_empty_or_none(versions):
        missing.append("Affects Version")
    if is_empty_or_none(severity):
        missing.append("Severity")

    if missing:
        return {
            "rule_id": "GEN-5",
            "message": f"Bug {ticket['key']} is missing: {', '.join(missing)}",
        }
    return None


def check_gen_6(ticket, rule, config):
    """GEN-6: Staleness check — In Progress > N days."""
    status = get_field(ticket, "fields.status.name", "")
    if status != "In Progress":
        return None

    staleness_days = int(config.get("STALENESS_DAYS", rule.get("staleness_days", 14)))
    updated = get_field(ticket, "fields.updated", "")
    days = days_since(updated)

    if days > staleness_days:
        return {
            "rule_id": "GEN-6",
            "message": f"Ticket {ticket['key']} has been In Progress for {days} days without update (threshold: {staleness_days})",
        }
    return None


def check_gen_7(ticket, rule, config):
    """GEN-7: Check exemption label. Returns special marker."""
    labels = get_field(ticket, "fields.labels", [])
    if "hygiene-bot-ignore" in labels:
        return {"rule_id": "GEN-7", "exempt": True, "message": f"Ticket {ticket['key']} is exempt via hygiene-bot-ignore label"}
    return None


def check_wf_7(ticket, rule, config):
    """WF-7: Changelog shows skipped transitions."""
    changelog = get_field(ticket, "changelog.histories", [])
    if not changelog:
        return None

    workflow_order_str = config.get("WORKFLOW_STATUSES", "New,Refinement,To Do,In Progress,Review,Closed")
    workflow_order = [s.strip() for s in workflow_order_str.split(",")]

    status_transitions = []
    for history in changelog:
        for item in history.get("items", []):
            if item.get("field") == "status":
                from_status = item.get("fromString", "")
                to_status = item.get("toString", "")
                status_transitions.append((from_status, to_status))

    for from_s, to_s in status_transitions:
        if from_s in workflow_order and to_s in workflow_order:
            from_idx = workflow_order.index(from_s)
            to_idx = workflow_order.index(to_s)
            if to_idx > from_idx + 1:
                skipped = workflow_order[from_idx + 1 : to_idx]
                return {
                    "rule_id": "WF-7",
                    "message": f"Ticket {ticket['key']} skipped statuses: {from_s} → {to_s} (skipped: {', '.join(skipped)})",
                }
    return None


def check_fv_1(ticket, rule, config, pr_data=None):
    """FV-1: Merged PR but no fixVersion."""
    fix_versions = get_field(ticket, "fields.fixVersions", [])
    if not is_empty_or_none(fix_versions):
        return None

    has_merged = False
    if pr_data:
        for pr in pr_data:
            if pr.get("state") == "merged" or pr.get("mergedAt"):
                has_merged = True
                break

    status = get_field(ticket, "fields.status.name", "")
    if status == "Closed" and not has_merged:
        has_merged = True

    if has_merged and is_empty_or_none(fix_versions):
        return {
            "rule_id": "FV-1",
            "message": f"Ticket {ticket['key']} has merged PRs but no fixVersion set",
        }
    return None


def check_fv_7(ticket, rule, config):
    """FV-7: fixVersion naming must match RHOAI conventions."""
    fix_versions = get_field(ticket, "fields.fixVersions", [])
    if is_empty_or_none(fix_versions):
        return None

    versions_config_path = config.get("_versions_config_path")
    if not versions_config_path:
        return None

    try:
        version_patterns = load_json(versions_config_path)
        patterns = [re.compile(p["regex"]) for p in version_patterns.get("patterns", [])]
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return None

    bad_names = []
    for fv in fix_versions:
        name = fv.get("name", "") if isinstance(fv, dict) else str(fv)
        if not any(p.match(name) for p in patterns):
            bad_names.append(name)

    if bad_names:
        return {
            "rule_id": "FV-7",
            "message": f"Ticket {ticket['key']} has non-standard fixVersion names: {', '.join(bad_names)}",
        }
    return None


def check_fv_6(ticket, rule, config):
    """FV-6: Released versions are immutable."""
    fix_versions = get_field(ticket, "fields.fixVersions", [])
    released = []
    for fv in fix_versions:
        if isinstance(fv, dict) and fv.get("released"):
            released.append(fv.get("name", "unknown"))

    if released:
        return {
            "rule_id": "FV-6",
            "message": f"Ticket {ticket['key']} references released (immutable) versions: {', '.join(released)} — changes require release-manager approval",
            "severity_override": "info",
        }
    return None


def check_res_2(ticket, rule, config):
    """RES-2: Closed tickets must have resolution."""
    status = get_field(ticket, "fields.status.name", "")
    if status != "Closed":
        return None

    resolution = get_field(ticket, "fields.resolution")
    if is_empty_or_none(resolution):
        return {
            "rule_id": "RES-2",
            "message": f"Ticket {ticket['key']} is Closed but has no resolution value",
        }
    return None


def check_res_3(ticket, rule, config):
    """RES-3: Won't Fix / Duplicate must have explanation comment."""
    resolution = get_field(ticket, "fields.resolution")
    if not resolution:
        return None
    res_name = resolution.get("name", "") if isinstance(resolution, dict) else str(resolution)

    if res_name not in ("Won't Fix", "Duplicate", "Won't Do"):
        return None

    comments = get_field(ticket, "fields.comment.comments", [])
    if not comments:
        return {
            "rule_id": "RES-3",
            "message": f"Ticket {ticket['key']} resolved as {res_name} but has no comments explaining why",
        }
    return None


def check_res_4(ticket, rule, config):
    """RES-4: Bug/Story must have QA sign-off before Closed."""
    status = get_field(ticket, "fields.status.name", "")
    if status != "Closed":
        return None

    issue_type = get_field(ticket, "fields.issuetype.name", "")
    if issue_type.lower() not in ("bug", "story"):
        return None

    qa_signoff = get_field(ticket, "fields.customfield_12319940")
    if is_empty_or_none(qa_signoff):
        return {
            "rule_id": "RES-4",
            "message": f"{issue_type} {ticket['key']} is Closed but QA sign-off field is not set",
        }
    return None


def check_required_fields(ticket, matrix, config):
    """Check Appendix A required fields matrix."""
    issue_type = get_field(ticket, "fields.issuetype.name", "")
    status = get_field(ticket, "fields.status.name", "")

    type_matrix = matrix.get("matrix", {}).get(issue_type, {})
    required = type_matrix.get(status, [])
    field_mappings = matrix.get("field_mappings", {})

    missing = []
    for field_name in required:
        if field_name == "pr_link":
            continue
        field_path = field_mappings.get(field_name, f"fields.{field_name}")
        value = get_field(ticket, field_path)
        if is_empty_or_none(value):
            missing.append(field_name)

    if missing:
        return {
            "rule_id": "MATRIX",
            "category": "Required Fields",
            "severity": "high",
            "title": "Required fields missing for current status",
            "message": f"Ticket {ticket['key']} ({issue_type} / {status}) is missing required fields: {', '.join(missing)}",
            "auto_fixable": False,
            "fix_description": f"Set the following fields: {', '.join(missing)}",
        }
    return None


def check_pr_rules(ticket, pr_data, config):
    """Check WF-1 through WF-5, PR-1 through PR-4 using PR data."""
    if not pr_data:
        return []

    violations = []
    status = get_field(ticket, "fields.status.name", "")
    key = ticket["key"]
    workflow_order_str = config.get("WORKFLOW_STATUSES", "New,Refinement,To Do,In Progress,Review,Closed")
    workflow_order = [s.strip() for s in workflow_order_str.split(",")]

    has_any_pr = len(pr_data) > 0
    has_open_pr = any(pr.get("state") in ("open", "OPEN") for pr in pr_data)
    has_draft_pr = any(pr.get("state") in ("open", "OPEN") and pr.get("draft") for pr in pr_data)
    has_ready_pr = any(pr.get("state") in ("open", "OPEN") and not pr.get("draft") for pr in pr_data)
    has_changes_requested = any(pr.get("changes_requested") for pr in pr_data)
    all_merged = all(pr.get("state") == "merged" or pr.get("mergedAt") for pr in pr_data) and has_any_pr
    has_closed_without_merge = any(pr.get("state") == "closed" and not pr.get("mergedAt") for pr in pr_data)

    status_idx = workflow_order.index(status) if status in workflow_order else -1
    in_progress_idx = workflow_order.index("In Progress") if "In Progress" in workflow_order else -1

    # WF-1: PR exists but status < In Progress
    if has_any_pr and status_idx < in_progress_idx and in_progress_idx >= 0:
        violations.append({
            "rule_id": "WF-1",
            "category": "Workflow",
            "severity": "high",
            "title": "Work must not begin until ticket is In Progress",
            "message": f"Ticket {key} has PRs but status is '{status}' (should be at least In Progress)",
            "auto_fixable": True,
            "fix_action": "transition_forward",
            "fix_description": "Transition ticket to In Progress",
        })

    # WF-2: PR ready for review but status != Review
    if has_ready_pr and status != "Review" and not has_changes_requested:
        violations.append({
            "rule_id": "WF-2",
            "category": "Workflow",
            "severity": "high",
            "title": "PR ready for review but ticket not in Review",
            "message": f"Ticket {key} has a PR ready for review but status is '{status}'",
            "auto_fixable": True,
            "fix_action": "transition_to_review",
            "fix_description": "Transition ticket to Review",
        })

    # WF-3: Changes requested but status != In Progress
    if has_changes_requested and status != "In Progress":
        violations.append({
            "rule_id": "WF-3",
            "category": "Workflow",
            "severity": "medium",
            "title": "Changes requested but ticket not In Progress",
            "message": f"Ticket {key} has a PR with changes requested but status is '{status}'",
            "auto_fixable": True,
            "fix_action": "transition_to_in_progress",
            "fix_description": "Transition ticket back to In Progress",
        })

    # WF-4: All PRs merged but status != Closed
    if all_merged and status != "Closed":
        violations.append({
            "rule_id": "WF-4",
            "category": "Workflow",
            "severity": "high",
            "title": "All PRs merged but ticket not Closed",
            "message": f"Ticket {key} has all PRs merged but status is '{status}'",
            "auto_fixable": False,
            "fix_description": "Verify closure criteria (RES-1) then transition to Closed",
        })

    # WF-5: PR closed without merge
    if has_closed_without_merge:
        closed_prs = [pr.get("url", "unknown") for pr in pr_data if pr.get("state") == "closed" and not pr.get("mergedAt")]
        violations.append({
            "rule_id": "WF-5",
            "category": "Workflow",
            "severity": "medium",
            "title": "PR closed without merging",
            "message": f"Ticket {key} has PR(s) closed without merge: {', '.join(closed_prs)}",
            "auto_fixable": False,
            "fix_description": "Review ticket status — a PR was closed without merging",
        })

    # PR-1: Branch/title must include ticket key
    for pr in pr_data:
        branch = pr.get("branch", pr.get("headRefName", ""))
        title = pr.get("title", "")
        if key.upper() not in branch.upper() and key.upper() not in title.upper():
            violations.append({
                "rule_id": "PR-1",
                "category": "PR Linking",
                "severity": "medium",
                "title": "PR branch/title missing ticket key",
                "message": f"PR {pr.get('url', 'unknown')} does not contain ticket key {key} in branch name or title",
                "auto_fixable": False,
                "fix_description": "Update the PR title or branch name to include the ticket key",
            })
            break

    # PR-3: Too many PRs
    if len(pr_data) > 5:
        violations.append({
            "rule_id": "PR-3",
            "category": "PR Linking",
            "severity": "low",
            "title": "Many PRs linked to one ticket",
            "message": f"Ticket {key} has {len(pr_data)} PRs linked — consider splitting into separate tickets",
            "auto_fixable": False,
            "fix_description": "Review whether these PRs cover unrelated changes",
        })

    # PR-4: Backport PRs must reference original commit
    for pr in pr_data:
        title = pr.get("title", "").lower()
        body = pr.get("body", "") or ""
        if "backport" in title or "cherry-pick" in title or "cherry pick" in title:
            if "cherry picked from commit" not in body.lower() and "cherry-picked from" not in body.lower():
                violations.append({
                    "rule_id": "PR-4",
                    "category": "PR Linking",
                    "severity": "medium",
                    "title": "Backport PR missing original commit reference",
                    "message": f"Backport PR {pr.get('url', 'unknown')} does not contain 'cherry picked from commit <sha>'",
                    "auto_fixable": False,
                    "fix_description": "Add 'cherry picked from commit <sha>' to the PR body",
                })
                break

    return violations


def evaluate_ticket(ticket, rules, matrix, versions_path, pr_data=None, config=None):
    config = config or {}
    config["_versions_config_path"] = versions_path

    result = {
        "key": ticket.get("key", "UNKNOWN"),
        "summary": get_field(ticket, "fields.summary", ""),
        "status": get_field(ticket, "fields.status.name", ""),
        "assignee": None,
        "issue_type": get_field(ticket, "fields.issuetype.name", ""),
        "exempt": False,
        "violations": [],
    }

    assignee = get_field(ticket, "fields.assignee")
    if isinstance(assignee, dict):
        result["assignee"] = assignee.get("displayName") or assignee.get("emailAddress")

    rules_list = rules.get("rules", [])
    rules_by_id = {r["id"]: r for r in rules_list}

    # Check exemption first
    gen7 = check_gen_7(ticket, rules_by_id.get("GEN-7", {}), config)
    if gen7 and gen7.get("exempt"):
        result["exempt"] = True
        result["violations"].append(gen7)
        return result

    checkers = [
        ("GEN-1", check_gen_1),
        ("GEN-2", check_gen_2),
        ("GEN-3", check_gen_3),
        ("GEN-4", check_gen_4),
        ("GEN-5", check_gen_5),
        ("GEN-6", check_gen_6),
        ("WF-7", check_wf_7),
        ("FV-7", check_fv_7),
        ("FV-6", check_fv_6),
        ("RES-2", check_res_2),
        ("RES-3", check_res_3),
        ("RES-4", check_res_4),
    ]

    for rule_id, checker_fn in checkers:
        rule_def = rules_by_id.get(rule_id, {})
        if rule_id == "FV-1":
            violation = check_fv_1(ticket, rule_def, config, pr_data)
        else:
            violation = checker_fn(ticket, rule_def, config)

        if violation:
            violation.setdefault("category", rule_def.get("category", "Unknown"))
            violation.setdefault("severity", violation.get("severity_override", rule_def.get("severity", "medium")))
            violation.setdefault("title", rule_def.get("title", ""))
            violation.setdefault("auto_fixable", rule_def.get("auto_fixable", False))
            violation.setdefault("fix_action", rule_def.get("fix_action"))
            violation.setdefault("fix_description", rule_def.get("fix_description", ""))
            violation.pop("severity_override", None)
            result["violations"].append(violation)

    # FV-1 (needs pr_data)
    fv1 = check_fv_1(ticket, rules_by_id.get("FV-1", {}), config, pr_data)
    if fv1:
        rule_def = rules_by_id.get("FV-1", {})
        fv1.setdefault("category", rule_def.get("category", "fixVersion"))
        fv1.setdefault("severity", rule_def.get("severity", "high"))
        fv1.setdefault("title", rule_def.get("title", ""))
        fv1.setdefault("auto_fixable", rule_def.get("auto_fixable", True))
        fv1.setdefault("fix_action", rule_def.get("fix_action", "set_fix_version"))
        fv1.setdefault("fix_description", rule_def.get("fix_description", ""))
        result["violations"].append(fv1)

    # PR-based rules
    pr_violations = check_pr_rules(ticket, pr_data or [], config)
    for v in pr_violations:
        result["violations"].append(v)

    # Required fields matrix check
    matrix_violation = check_required_fields(ticket, matrix, config)
    if matrix_violation:
        result["violations"].append(matrix_violation)

    return result


def main():
    parser = argparse.ArgumentParser(description="Evaluate Jira ticket against hygiene rules")
    parser.add_argument("--ticket", required=True, help="Path to ticket JSON file")
    parser.add_argument("--rules", required=True, help="Path to hygiene-rules.json")
    parser.add_argument("--matrix", required=True, help="Path to appendix-a-matrix.json")
    parser.add_argument("--versions", required=True, help="Path to appendix-b-versions.json")
    parser.add_argument("--pr-data", help="Path to PR data JSON (from pr_correlator.py)")
    parser.add_argument("--config", help="Path to config.env")
    parser.add_argument("--staleness-days", type=int, default=14)
    args = parser.parse_args()

    ticket = load_json(args.ticket)
    rules = load_json(args.rules)
    matrix = load_json(args.matrix)

    pr_data = None
    if args.pr_data:
        pr_data = load_json(args.pr_data)

    config = load_config(args.config)
    if args.staleness_days != 14:
        config["STALENESS_DAYS"] = str(args.staleness_days)

    result = evaluate_ticket(ticket, rules, matrix, args.versions, pr_data, config)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
