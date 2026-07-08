#!/usr/bin/env python3
"""Format hygiene check results into markdown and JSON reports.

Usage:
    python3 format_report.py --input results.json --scope "Active Sprint (AIPCC, AI Safety)" \
        --output-dir ~/jira-hygiene-reports --project AIPCC

Input (--input): JSON array of ticket evaluation results from evaluate_rules.py:
    [
        {"key": "AIPCC-1234", "violations": [...], "exempt": false, ...},
        ...
    ]

Output:
    - <output-dir>/<project>-<date>-<scope>.json — structured report
    - <output-dir>/<project>-<date>-<scope>.md — human-readable markdown report
    - stdout — markdown report (for skill to display)
"""

import argparse
import json
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


def build_summary(results, scope_description):
    total = len(results)
    exempt = sum(1 for r in results if r.get("exempt"))
    with_violations = sum(1 for r in results if r.get("violations") and not r.get("exempt"))
    clean = total - exempt - with_violations

    all_violations = []
    for r in results:
        if not r.get("exempt"):
            all_violations.extend(r.get("violations", []))

    category_counts = Counter()
    rule_counts = Counter()
    for v in all_violations:
        cat = v.get("category", "Unknown")
        category_counts[cat] += 1
        rule_counts[v.get("rule_id", "?")] += 1

    return {
        "scope": scope_description,
        "total_tickets": total,
        "exempt_tickets": exempt,
        "clean_tickets": clean,
        "violation_tickets": with_violations,
        "total_violations": len(all_violations),
        "violations_by_category": dict(category_counts),
        "most_common_rules": rule_counts.most_common(5),
    }


def format_markdown(results, summary):
    lines = []
    lines.append("## Jira Hygiene Report\n")
    lines.append(f"**Scope:** {summary['scope']}")
    lines.append(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"**Checked:** {summary['total_tickets']} | **Exempt:** {summary['exempt_tickets']} | **Clean:** {summary['clean_tickets']} | **Violations:** {summary['violation_tickets']}\n")

    if summary["total_violations"] == 0:
        lines.append("All tickets are clean. No violations found.\n")
        return "\n".join(lines)

    # Violations by category
    lines.append("### Violations by Category\n")
    lines.append("| Category | Count | Most Common Rule |")
    lines.append("|----------|-------|-----------------|")
    cat_counts = summary["violations_by_category"]
    rule_counts = Counter()
    for r in results:
        if not r.get("exempt"):
            for v in r.get("violations", []):
                rule_counts[(v.get("category", "?"), v.get("rule_id", "?"))] += 1

    for cat, count in sorted(cat_counts.items(), key=lambda x: -x[1]):
        top_rule = max(
            [(rid, c) for (rcat, rid), c in rule_counts.items() if rcat == cat],
            key=lambda x: x[1],
            default=("—", 0),
        )
        lines.append(f"| {cat} | {count} | {top_rule[0]} ({top_rule[1]}x) |")
    lines.append("")

    # Per-ticket detail
    violation_tickets = [r for r in results if r.get("violations") and not r.get("exempt")]
    if violation_tickets:
        lines.append("### Per-Ticket Detail\n")
        lines.append("| Ticket | Type | Status | Assignee | Violations | Rules |")
        lines.append("|--------|------|--------|----------|------------|-------|")
        for r in sorted(violation_tickets, key=lambda x: -len(x.get("violations", []))):
            key = r["key"]
            link = f"[{key}](https://redhat.atlassian.net/browse/{key})"
            itype = r.get("issue_type", "?")
            status = r.get("status", "?")
            assignee = r.get("assignee") or "unassigned"
            vcount = len(r.get("violations", []))
            rules = ", ".join(sorted(set(v.get("rule_id", "?") for v in r.get("violations", []))))
            lines.append(f"| {link} | {itype} | {status} | {assignee} | {vcount} | {rules} |")
        lines.append("")

    # Detailed violations per ticket
    lines.append("### Violation Details\n")
    for r in violation_tickets:
        key = r["key"]
        lines.append(f"#### {key} — {r.get('summary', '')}\n")
        lines.append("| # | Rule | Severity | Violation | Auto-fix | Fix |")
        lines.append("|---|------|----------|-----------|----------|-----|")
        for i, v in enumerate(r.get("violations", []), 1):
            auto = "Yes" if v.get("auto_fixable") else "No"
            lines.append(f"| {i} | {v.get('rule_id', '?')} | {v.get('severity', '?')} | {v.get('message', '')} | {auto} | {v.get('fix_description', '')} |")
        lines.append("")

    # Exempt tickets
    exempt_tickets = [r for r in results if r.get("exempt")]
    if exempt_tickets:
        lines.append("### Exempt Tickets (hygiene-bot-ignore)\n")
        lines.append("| Ticket | Summary |")
        lines.append("|--------|---------|")
        for r in exempt_tickets:
            key = r["key"]
            link = f"[{key}](https://redhat.atlassian.net/browse/{key})"
            lines.append(f"| {link} | {r.get('summary', '')} |")
        lines.append("")

    return "\n".join(lines)


def format_json_report(results, summary):
    return {
        "version": 1,
        "generated": datetime.now().isoformat(),
        "summary": {
            "scope": summary["scope"],
            "total_tickets": summary["total_tickets"],
            "exempt_tickets": summary["exempt_tickets"],
            "clean_tickets": summary["clean_tickets"],
            "violation_tickets": summary["violation_tickets"],
            "total_violations": summary["total_violations"],
            "violations_by_category": summary["violations_by_category"],
        },
        "tickets": results,
    }


def main():
    parser = argparse.ArgumentParser(description="Format hygiene check report")
    parser.add_argument("--input", required=True, help="Path to evaluation results JSON")
    parser.add_argument("--scope", default="Manual check", help="Scope description")
    parser.add_argument("--output-dir", help="Directory for report files")
    parser.add_argument("--project", default="UNKNOWN", help="Project key for filename")
    args = parser.parse_args()

    with open(args.input) as f:
        results = json.load(f)

    summary = build_summary(results, args.scope)
    markdown = format_markdown(results, summary)
    json_report = format_json_report(results, summary)

    print(markdown)

    if args.output_dir:
        output_dir = Path(args.output_dir).expanduser()
        output_dir.mkdir(parents=True, exist_ok=True)

        date_str = datetime.now().strftime("%Y-%m-%d")
        scope_slug = args.scope.lower().replace(" ", "-").replace("(", "").replace(")", "")[:30]
        base_name = f"{args.project}-{date_str}-{scope_slug}"

        md_path = output_dir / f"{base_name}.md"
        json_path = output_dir / f"{base_name}.json"

        with open(md_path, "w") as f:
            f.write(markdown)
        with open(json_path, "w") as f:
            json.dump(json_report, f, indent=2)

        print(f"\nReports saved to:\n  {md_path}\n  {json_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
