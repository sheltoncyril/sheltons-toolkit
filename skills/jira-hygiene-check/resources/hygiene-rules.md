# Team Jira Hygiene Rules — Quick Reference

Source: [Confluence page](https://redhat.atlassian.net/wiki/spaces/RHODS/pages/431230832/Team+Jira+Hygiene+Rules)

Enforcement: ⚙️ = bot-enforced | 👤 = team convention

## 1. General Ticket Standards

| ID | Rule | Enforcement |
|----|------|-------------|
| GEN-1 | Active sprint tickets must have assignee | ⚙️ |
| GEN-2 | Clear summary + description with context/criteria/repro steps | 👤 |
| GEN-3 | Correct issue type and component | ⚙️ |
| GEN-4 | Priority explicitly set (not default) | ⚙️ |
| GEN-5 | Bugs: Affects Version + severity at triage | ⚙️ |
| GEN-6 | In Progress > 14 days = stale flag | ⚙️ |
| GEN-7 | `hygiene-bot-ignore` label exempts ticket | ⚙️ |

## 2. Workflow & Status

| ID | Rule | Enforcement |
|----|------|-------------|
| WF-1 | PR exists = ticket must be >= In Progress | ⚙️ |
| WF-2 | PR ready for review = ticket must be Review | ⚙️ |
| WF-3 | Changes requested on PR = ticket back to In Progress | ⚙️ |
| WF-4 | All PRs merged = ticket to Closed (if criteria met) | ⚙️ |
| WF-5 | PR closed without merge = notify only | ⚙️ |
| WF-6 | Cannot close while backports missing | ⚙️ |
| WF-7 | No skipping workflow transitions | ⚙️ |

## 3. PR Linking

| ID | Rule | Enforcement |
|----|------|-------------|
| PR-1 | Branch/PR title must include ticket key | ⚙️ |
| PR-2 | All PRs must be linked on ticket | ⚙️ |
| PR-3 | One ticket per logical change | 👤 |
| PR-4 | Backport PRs must reference original commit | ⚙️ |

## 4. fixVersion & Backport

| ID | Rule | Enforcement |
|----|------|-------------|
| FV-1 | Merged PR = must have fixVersion | ⚙️ |
| FV-2 | fixVersions must match branches with fix | ⚙️ |
| FV-3 | Oldest release line with fix must be listed | ⚙️ |
| FV-4 | No claiming fixVersion without confirmed fix on branch | ⚙️ |
| FV-5 | Backports within 2 business days of main merge | ⚙️ |
| FV-6 | Released versions immutable (need RM approval) | ⚙️ |
| FV-7 | Version naming follows RHOAI conventions | 👤 |

## 5. Code Freeze

| ID | Rule | Enforcement |
|----|------|-------------|
| CF-1 | Freeze dates published and configured | 👤 |
| CF-2 | Past freeze: tickets targeting frozen version must be Closed | ⚙️ |
| CF-3 | Daily digest of unresolved tickets past freeze | ⚙️ |
| CF-4 | Pre-freeze warning 3 days before | ⚙️ |
| CF-5 | Post-freeze merges need `freeze-exception` label | ⚙️ |

## 6. Resolution & Closure

| ID | Rule | Enforcement |
|----|------|-------------|
| RES-1 | Closed requires: all PRs merged + backports + fixVersions + fields | ⚙️ |
| RES-2 | Closed must have resolution value | ⚙️ |
| RES-3 | Won't Fix / Duplicate must have explanation comment | 👤 |
| RES-4 | Bug/Story: QA sign-off required before Closed | ⚙️ |

## Exemption

Apply `hygiene-bot-ignore` label to exempt a ticket. Exempted tickets appear in the weekly digest.
