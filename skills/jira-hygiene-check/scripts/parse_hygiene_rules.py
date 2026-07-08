#!/usr/bin/env python3
"""Parse Confluence hygiene rules page into structured JSON.

Offline refresh tool — run manually when the Confluence page is updated.

Usage:
    # From a local markdown file (copied from Confluence):
    python3 parse_hygiene_rules.py --input rules.md --output hygiene-rules.json

    # The skill can also pipe Confluence page content via stdin:
    echo "<markdown content>" | python3 parse_hygiene_rules.py --output hygiene-rules.json

This script parses the table structure of the Team Jira Hygiene Rules page
and outputs a structured JSON file matching the format in hygiene-rules.json.

Note: This is a best-effort parser. After running, review the output and
manually adjust any rules that the parser couldn't fully parse.
"""

import argparse
import json
import re
import sys
from datetime import datetime


def parse_rule_table(content, section_name, category):
    """Extract rules from a markdown table in a section."""
    rules = []

    section_pattern = rf"##\s*\d*\.?\s*{re.escape(section_name)}"
    section_match = re.search(section_pattern, content, re.IGNORECASE)
    if not section_match:
        return rules

    section_start = section_match.end()
    next_section = re.search(r"\n##\s", content[section_start:])
    section_end = section_start + next_section.start() if next_section else len(content)
    section_text = content[section_start:section_end]

    table_rows = re.findall(r"\|([^|]+)\|([^|]+)\|([^|]+)\|", section_text)

    for row in table_rows:
        cells = [cell.strip() for cell in row]
        rule_id = cells[0]

        if rule_id in ("ID", "---", ""):
            continue
        if re.match(r"^-+$", rule_id):
            continue

        rule_text = cells[1] if len(cells) > 1 else ""
        enforcement_text = cells[2] if len(cells) > 2 else ""

        enforcement = "bot" if "⚙️" in enforcement_text or "Bot" in enforcement_text else "convention"

        rules.append({
            "id": rule_id,
            "category": category,
            "title": re.sub(r"\*\*([^*]+)\*\*", r"\1", rule_text).strip(),
            "enforcement": enforcement,
            "raw_enforcement": enforcement_text.strip(),
        })

    return rules


def main():
    parser = argparse.ArgumentParser(description="Parse Confluence hygiene rules into JSON")
    parser.add_argument("--input", help="Path to markdown file with rules")
    parser.add_argument("--output", default="hygiene-rules.json", help="Output JSON path")
    parser.add_argument("--page-id", default="431230832", help="Confluence page ID for metadata")
    args = parser.parse_args()

    if args.input:
        with open(args.input) as f:
            content = f.read()
    else:
        content = sys.stdin.read()

    if not content.strip():
        print("Error: No content provided. Use --input or pipe via stdin.", file=sys.stderr)
        sys.exit(1)

    sections = [
        ("General Ticket Standards", "General"),
        ("Workflow & Status Rules", "Workflow"),
        ("Workflow & Status", "Workflow"),
        ("PR Linking Rules", "PR Linking"),
        ("PR Linking", "PR Linking"),
        ("fixVersion & Backport Rules", "fixVersion"),
        ("fixVersion & Backport", "fixVersion"),
        ("Code Freeze Rules", "Code Freeze"),
        ("Code Freeze", "Code Freeze"),
        ("Resolution & Closure Rules", "Resolution"),
        ("Resolution & Closure", "Resolution"),
    ]

    all_rules = []
    seen_ids = set()

    for section_name, category in sections:
        rules = parse_rule_table(content, section_name, category)
        for rule in rules:
            if rule["id"] not in seen_ids:
                seen_ids.add(rule["id"])
                all_rules.append(rule)

    output = {
        "meta": {
            "source_page_id": args.page_id,
            "source_url": f"https://redhat.atlassian.net/wiki/spaces/RHODS/pages/{args.page_id}/Team+Jira+Hygiene+Rules",
            "last_synced": datetime.now().strftime("%Y-%m-%d"),
            "parsed_rules_count": len(all_rules),
            "note": "Auto-parsed from Confluence. Review and add check_type, severity, auto_fixable, and other fields manually.",
        },
        "rules": all_rules,
    }

    with open(args.output, "w") as f:
        json.dump(output, f, indent=2)

    print(f"Parsed {len(all_rules)} rules from {len(seen_ids)} unique IDs", file=sys.stderr)
    print(f"Output written to {args.output}", file=sys.stderr)

    for rule in all_rules:
        print(f"  {rule['id']}: {rule['title'][:60]}...", file=sys.stderr)


if __name__ == "__main__":
    main()
