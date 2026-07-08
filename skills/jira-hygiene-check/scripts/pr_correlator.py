#!/usr/bin/env python3
"""PR correlation — discover PR state for a Jira ticket key.

Usage:
    python3 pr_correlator.py --ticket-key AIPCC-1234 \
        [--github-repos org/repo1,org/repo2] \
        [--gitlab-repos host:org/repo] \
        [--output pr_data.json]

Output (stdout or --output, JSON array):
    [
        {
            "url": "https://github.com/org/repo/pull/42",
            "number": 42,
            "title": "AIPCC-1234: fix bias metric",
            "state": "merged",
            "draft": false,
            "branch": "AIPCC-1234-fix-bias",
            "mergedAt": "2026-07-01T12:00:00Z",
            "reviews": [{"state": "APPROVED"}],
            "changes_requested": false,
            "body": "...",
            "source": "github"
        }
    ]

Falls back gracefully if gh/glab not available.
"""

import argparse
import json
import subprocess
import sys


def run_command(cmd, timeout=30):
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return None


def check_tool(tool_name):
    return run_command(["which", tool_name]) is not None


def search_github_prs(ticket_key, repos):
    if not check_tool("gh"):
        print(f"[pr_correlator] gh CLI not available — skipping GitHub PR search", file=sys.stderr)
        return []

    results = []
    for repo in repos:
        repo = repo.strip()
        if not repo:
            continue

        output = run_command([
            "gh", "pr", "list",
            "--repo", repo,
            "--search", ticket_key,
            "--state", "all",
            "--json", "number,title,state,headRefName,mergedAt,isDraft,body,url,reviews",
            "--limit", "20",
        ])

        if not output:
            continue

        try:
            prs = json.loads(output)
        except json.JSONDecodeError:
            continue

        for pr in prs:
            has_changes_requested = False
            reviews = pr.get("reviews", [])
            if reviews:
                for review in reviews:
                    if review.get("state") == "CHANGES_REQUESTED":
                        has_changes_requested = True
                        break

            state = pr.get("state", "").lower()
            if state == "merged" or pr.get("mergedAt"):
                state = "merged"
            elif state == "closed":
                state = "closed"
            else:
                state = "open"

            results.append({
                "url": pr.get("url", f"https://github.com/{repo}/pull/{pr.get('number')}"),
                "number": pr.get("number"),
                "title": pr.get("title", ""),
                "state": state,
                "draft": pr.get("isDraft", False),
                "branch": pr.get("headRefName", ""),
                "mergedAt": pr.get("mergedAt"),
                "reviews": reviews,
                "changes_requested": has_changes_requested,
                "body": pr.get("body", ""),
                "source": "github",
                "repo": repo,
            })

    return results


def search_gitlab_prs(ticket_key, repos):
    if not check_tool("glab"):
        print(f"[pr_correlator] glab CLI not available — skipping GitLab MR search", file=sys.stderr)
        return []

    results = []
    for repo_spec in repos:
        repo_spec = repo_spec.strip()
        if not repo_spec:
            continue

        if ":" in repo_spec:
            host, repo = repo_spec.split(":", 1)
        else:
            host = "gitlab.com"
            repo = repo_spec

        output = run_command([
            "glab", "mr", "list",
            "--repo", repo,
            "--search", ticket_key,
            "--all",
            "--output", "json",
        ])

        if not output:
            continue

        try:
            mrs = json.loads(output)
        except json.JSONDecodeError:
            continue

        for mr in mrs:
            state = mr.get("state", "").lower()
            merged_at = mr.get("merged_at")
            if merged_at:
                state = "merged"

            results.append({
                "url": mr.get("web_url", ""),
                "number": mr.get("iid"),
                "title": mr.get("title", ""),
                "state": state,
                "draft": mr.get("draft", False) or mr.get("work_in_progress", False),
                "branch": mr.get("source_branch", ""),
                "mergedAt": merged_at,
                "reviews": [],
                "changes_requested": False,
                "body": mr.get("description", ""),
                "source": "gitlab",
                "repo": repo_spec,
            })

    return results


def main():
    parser = argparse.ArgumentParser(description="Discover PR state for a Jira ticket")
    parser.add_argument("--ticket-key", required=True, help="Jira ticket key (e.g. AIPCC-1234)")
    parser.add_argument("--github-repos", default="", help="Comma-separated GitHub repos (org/repo)")
    parser.add_argument("--gitlab-repos", default="", help="Comma-separated GitLab repos (host:org/repo)")
    parser.add_argument("--output", help="Output JSON file path (default: stdout)")
    args = parser.parse_args()

    all_prs = []

    github_repos = [r for r in args.github_repos.split(",") if r.strip()]
    if github_repos:
        all_prs.extend(search_github_prs(args.ticket_key, github_repos))

    gitlab_repos = [r for r in args.gitlab_repos.split(",") if r.strip()]
    if gitlab_repos:
        all_prs.extend(search_gitlab_prs(args.ticket_key, gitlab_repos))

    output = json.dumps(all_prs, indent=2)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output)
        print(f"[pr_correlator] Found {len(all_prs)} PRs for {args.ticket_key}, saved to {args.output}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
