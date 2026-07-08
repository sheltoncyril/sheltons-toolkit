---
name: check
description: >
  Check Jira tickets against team hygiene rules. User-scoped by default (your
  tickets only); use --team for full component scope. Supports single ticket,
  sprint, JQL, or all-open checks. Reports violations with rule IDs and fixes.
  Opt-in auto-fix with per-ticket approval. Auto-fetches code freeze dates from
  Product Pages when available. Trigger phrases include: "check hygiene",
  "hygiene check", "jira hygiene", "sprint hygiene", "hygiene audit",
  "run hygiene", "hygiene report", "my ticket hygiene".
allowed-tools: Bash Read Write Grep Glob Agent AskUserQuestion
---

# Jira Hygiene Check

Validate Jira tickets against team hygiene rules. **User-scoped by default** — checks only your tickets. Use `--team` for full component scope.

**Usage:**
- `/jira-hygiene-check` — your tickets in active sprint (default)
- `/jira-hygiene-check --team` — all team tickets in active sprint
- `/jira-hygiene-check --sprint` — your sprint tickets (same as no-arg default)
- `/jira-hygiene-check --open` — your unresolved tickets
- `/jira-hygiene-check --open --team` — all team unresolved tickets
- `/jira-hygiene-check RHOAIENG-1234` — single ticket (ignores scoping)
- `/jira-hygiene-check --jql "..."` — custom JQL (ignores scoping)

**Rules reference:** [Team Jira Hygiene Rules](https://redhat.atlassian.net/wiki/spaces/RHODS/pages/431230832/Team+Jira+Hygiene+Rules)

---

## Mandatory Execution Checklist

**YOU MUST complete every step in order. Do not skip any step. Check off each step as you complete it by reporting progress to the user.**

Before presenting results, verify you have completed ALL of the following:

- [ ] **Step 0** — Load config.env, identify user via `atlassianUserInfo`, verify MCP, refresh freeze dates
- [ ] **Step 1** — Determine scope (user-scoped default or --team)
- [ ] **Step 2** — Fetch all tickets via JQL (paginate if needed)
- [ ] **Step 2b** — Sprint membership vetting (flag In Progress tickets not in sprint)
- [ ] **Step 3** — Check exemptions (`hygiene-bot-ignore` label)
- [ ] **Step 4** — Evaluate field-based rules (GEN-1 through GEN-7, FV-1, FV-6, FV-7, RES-1 through RES-4, WF-7)
- [ ] **Step 5** — **PR CORRELATION (MANDATORY when PR_CHECK_ENABLED=true)** — for EVERY ticket in Review, In Progress, or Closed status, check linked PRs via Teamwork Graph AND `gh` CLI. Evaluate WF-1 through WF-5, PR-1 through PR-4. This step catches critical mismatches between ticket status and PR state — DO NOT SKIP IT.
- [ ] **Step 6** — Compile all violations (field-based AND PR-based) into final report
- [ ] **Step 7** — Present results with fix checkpoints
- [ ] **Step 8** — Apply fixes if approved
- [ ] **Step 9** — Save report

**Why PR correlation matters (from real findings):**
- Tickets in Review but PR is still Draft = status is ahead of reality
- Tickets In Progress with zero PRs for weeks = zombie work
- Branch names missing ticket keys = broken traceability
- All PRs merged but ticket not Closed = missed transition
- PR closed without merge = needs manual resolution

Skipping Step 5 produces a report that misses the most actionable violations. Field checks alone (GEN/FV/RES) catch hygiene gaps but miss workflow-state mismatches that block releases.

---

## Workflow

### Step 0: Load Configuration and Identify User

Read `config.env` from the current working directory.

If `config.env` does not exist:
> "No configuration found. Run `/jira-hygiene-setup` first to configure your project."
Stop.

Parse config into variables. Load resource files relative to this skill:
- `resources/hygiene-rules.json` — rule definitions
- `resources/appendix-a-matrix.json` — required fields matrix
- `resources/appendix-b-versions.json` — fixVersion naming patterns

**Identify the current user:**
Call `atlassianUserInfo` (no parameters) to get the authenticated user's display name and account ID. Store both — the display name is shown in the report header, the account ID is used as a fallback if `currentUser()` JQL fails.

**Verify MCP connectivity:**
`searchJiraIssuesUsingJql` with JQL `project = <JIRA_PROJECT_KEY> ORDER BY updated DESC`, `maxResults: 1`, `cloudId: <JIRA_CLOUD_ID>`.

If MCP fails, stop and point user to `resources/mcp-setup.md`.

**Refresh code freeze dates from Product Pages (best-effort):**

Try to auto-fetch freeze dates from Product Pages MCP. This is a best-effort enhancement — if Product Pages is unavailable, fall back to config.env.

1. Probe: Call `search_entities` with `q: "<FREEZE_PRODUCT from config or 'Red Hat AI'>"` to test if Product Pages MCP is available.
2. If available:
   - Call `search_entities` with `q: "Red Hat AI"` or the configured `FREEZE_PRODUCT` to find the product entity
   - Call `get_entity_hierarchy` with `entity_id: <product_id>`, `role: "children"`, `kind: "release"` to get release IDs
   - Call `browse_schedule` for each active release with `q: "freeze"` to get code freeze dates
   - Filter for tasks with `flags` containing `"code"` and `"freeze"`, and `date_finish` in the future
   - Extract the RHOAI code freeze dates (look for task names containing "RHOAI Code Freeze")
   - Use these dates in-memory for CF rules (do NOT rewrite config.env during a check run)
   - Log: "Freeze dates refreshed from Product Pages"
3. If Product Pages MCP is NOT available:
   - Check `FREEZE_DATES` in config.env
   - If present, use those cached values. Log: "Freeze dates: using cached values from config.env"
   - If empty, log: "No freeze dates available. Install the Product Pages MCP for auto-fetch, or run `/jira-hygiene-setup` to add dates manually. CF rules will be skipped."
   - To install Product Pages MCP, tell user: "Product Pages MCP provides automatic code freeze dates. If available in your Claude Code environment, it will be auto-detected. Contact your admin if you need access."

### Step 1: Determine Scope

Parse the user's input to determine check mode. **Default is user-scoped** (current user's tickets only). The `--team` flag overrides to full component scope.

**Scoping logic:**
- `--team` flag present: scope by project + component (no assignee filter)
- `--team` flag absent: scope by `assignee = currentUser()` AND project + component

**If argument is a ticket key** (matches `[A-Z]+-\d+` pattern):
- Mode: single ticket
- JQL: `key = <KEY>`
- Scoping: ignored (always checks the specific ticket)

**If argument is `--sprint` or no arguments (default):**
- Mode: active sprint, user-scoped
- JQL: `project = <JIRA_PROJECT_KEY> AND sprint in openSprints() AND assignee = currentUser()`
- If `TEAM_COMPONENT` is set, append: `AND component = "<TEAM_COMPONENT>"`
- Order: `ORDER BY status ASC, priority DESC`
- If `--team` is also present: drop `AND assignee = currentUser()`

**If argument is `--jql "<query>"`:**
- Mode: custom JQL
- JQL: user-provided query verbatim
- Scoping: ignored (user controls the query)

**If argument is `--open`:**
- Mode: all unresolved, user-scoped
- JQL: `project = <JIRA_PROJECT_KEY> AND resolution = Unresolved AND assignee = currentUser()`
- If `TEAM_COMPONENT` is set, append: `AND component = "<TEAM_COMPONENT>"`
- Order: `ORDER BY status ASC, updated DESC`
- If `--team` is also present: drop `AND assignee = currentUser()`

**If no arguments and no flags:**
Default to user-scoped sprint check. Show who is being checked:

> "Running hygiene check for **<display name>** — active sprint tickets.
> Use `--team` to check all <TEAM_COMPONENT> tickets instead."

Then proceed with the `--sprint` JQL (user-scoped).

### Step 2: Fetch Tickets

Use `searchJiraIssuesUsingJql` with:
- `cloudId`: from config
- `jql`: from Step 1
- `fields`: `["*all"]` (need custom fields for severity, QA sign-off)
- `maxResults`: 50

If results indicate more pages, paginate using `nextPageToken` until all tickets are fetched.

**Large result set warning:** If total tickets > 100, present a checkpoint:

> "Found <N> tickets. This may take a while to check. Continue?"
>
> - **Option 1:** Continue with all <N> tickets
> - **Option 2:** Limit to first 50
> - **Option 3:** Cancel

For changelog-dependent rules (WF-7), fetch each ticket individually with `expand=changelog` via `getJiraIssue`:
- `cloudId`: from config
- `issueIdOrKey`: ticket key
- `expand`: `"changelog"`
- `fields`: `["*all"]`

Only do this for tickets that are candidates (status not "New" — skipping tickets that haven't moved yet).

### Step 2b: Sprint Membership Vetting

For tickets with status "In Progress", verify they actually belong in the current sprint:

1. Check the `sprint` or `customfield_10020` field on each In Progress ticket
2. If a ticket is "In Progress" but NOT in any open sprint:
   - Flag as a **SPRINT-VET** finding: "Ticket is In Progress but not in any active sprint — may be abandoned work"
   - This is informational, not a rule violation — displayed in a separate "Sprint Vetting" section of the report
3. If a ticket is in an open sprint but has been In Progress since a PREVIOUS sprint (sprint start date < current sprint start):
   - Flag as **SPRINT-CARRY**: "Ticket carried over from a previous sprint — still In Progress"
   - Check the sprint history in `customfield_10020` (array of sprint objects) to identify carryover

This vetting helps surface zombie tickets that are technically "In Progress" but forgotten.

### Step 3: Check Exemptions

For each ticket, check if `hygiene-bot-ignore` label is present in `fields.labels`.

If present:
- Mark ticket as exempt
- Include in report under "Exempt Tickets" section
- Skip all rule enforcement for this ticket
- This honors rule GEN-7

### Step 4: Evaluate Rules

For each non-exempt ticket, run the evaluation engine. You can either:

**Option A — Use the Python script:**
Write ticket JSON to a temp file, call:
```bash
python3 <skill-dir>/scripts/evaluate_rules.py \
    --ticket /tmp/ticket.json \
    --rules <skill-dir>/resources/hygiene-rules.json \
    --matrix <skill-dir>/resources/appendix-a-matrix.json \
    --versions <skill-dir>/resources/appendix-b-versions.json \
    --config config.env \
    [--pr-data /tmp/pr_data.json]
```

**Option B — Evaluate inline (preferred for small batches):**
Apply the rule checks directly using the logic described below. This avoids file I/O overhead for small batches.

#### Phase A — General Standards (GEN-1 through GEN-7)

| Rule | Check | When |
|------|-------|------|
| GEN-1 | `fields.assignee` is null | Ticket is in active sprint (sprint field non-null) |
| GEN-2 | `fields.description` is null, empty, or < 20 characters | Always |
| GEN-3 | `fields.components` is empty | Always |
| GEN-4 | `fields.priority` is null or name is "Normal" or "Undefined" | Always |
| GEN-5 | `fields.versions` empty OR severity custom field null | Issue type is Bug |
| GEN-6 | `fields.updated` is > STALENESS_DAYS ago | Status is "In Progress" |
| GEN-7 | `hygiene-bot-ignore` in labels | Already checked in Step 3 |

#### Phase B — Workflow Status (WF-1 through WF-7)

WF-1 through WF-5 require PR data (Step 5). WF-7 requires changelog.

| Rule | Check | Requires |
|------|-------|----------|
| WF-1 | PR exists but status is before "In Progress" in workflow order | PR data |
| WF-2 | PR is open + not draft + no changes requested, but status ≠ "Review" | PR data |
| WF-3 | PR has changes_requested review, but status ≠ "In Progress" | PR data |
| WF-4 | All PRs merged, but status ≠ "Closed" | PR data |
| WF-5 | PR closed without merge — advisory only | PR data |
| WF-6 | Status is "Closed" but required backports missing | PR data + branch analysis |
| WF-7 | Changelog shows transition that skips statuses in WORKFLOW_STATUSES order | Changelog (expand=changelog) |

For WF-7, compare each status transition in `changelog.histories[].items` where `field = "status"`. If `fromString` and `toString` are both in WORKFLOW_STATUSES and the transition skips one or more intermediate statuses, flag it.

#### Phase C — PR Linking (PR-1 through PR-4)

All require PR data from Step 5.

| Rule | Check |
|------|-------|
| PR-1 | For each linked PR: branch name (`headRefName`) and title do not contain ticket key (case-insensitive) |
| PR-2 | Ticket has no PR links visible (from Teamwork Graph or GitHub/GitLab search) but status is Review or Closed |
| PR-3 | More than 5 PRs linked to this ticket |
| PR-4 | PR title/body contains "backport" or "cherry-pick" but body does not contain "cherry picked from commit" |

#### Phase D — fixVersion (FV-1 through FV-7)

| Rule | Check | Complexity |
|------|-------|-----------|
| FV-1 | `fields.fixVersions` empty but ticket has merged PRs or status is "Closed" | Simple |
| FV-2 | fixVersion names do not match branches containing the fix commit | Needs branch containment check |
| FV-3 | Oldest release branch with fix not in fixVersions | Needs branch containment check |
| FV-4 | fixVersion claimed but no commit on that branch | Needs branch containment check |
| FV-5 | Multiple fixVersions + some backport PRs are > 2 business days old and still open | PR data + date math |
| FV-6 | Any fixVersion has `released: true` — informational flag | Simple |
| FV-7 | fixVersion name does not match any regex in `appendix-b-versions.json` | Regex check |

For FV-2/FV-3/FV-4 (branch containment), use when `gh` is available:
```bash
gh api repos/<owner>/<repo>/compare/<release-branch>...<merge-sha> --jq '.status'
```
If status is "behind" or "identical", the commit is on that branch. If "ahead" or "diverged", it is not.

These are expensive checks. Only run for tickets where fixVersions is non-empty AND PR data shows merged PRs.

#### Phase E — Code Freeze (CF-1 through CF-5)

Only run if freeze dates are available (from Product Pages refresh in Step 0, or from `FREEZE_DATES` in config.env).

Parse freeze dates: `version:YYYY-MM-DD` pairs.

| Rule | Check |
|------|-------|
| CF-1 | Informational — freeze dates source (Product Pages / config.env / none). Log to report |
| CF-2 | Ticket has a fixVersion matching a frozen version AND current date is past freeze AND status ≠ "Closed" |
| CF-3 | Compile all tickets past freeze that are unresolved — batch into digest section |
| CF-4 | Current date is within 3 days before a freeze — flag tickets targeting that version that are not "Closed" |
| CF-5 | Ticket has merged PR (mergedAt > freeze date) for a frozen version AND does not have `freeze-exception` label |

#### Phase F — Resolution & Closure (RES-1 through RES-4)

| Rule | Check | When |
|------|-------|------|
| RES-1 | Status is "Closed" but one or more of: no merged PRs, missing backports, empty fixVersions, missing required fields per Appendix A matrix | Status is "Closed" |
| RES-2 | `fields.resolution` is null | Status is "Closed" |
| RES-3 | Resolution is "Won't Fix" or "Duplicate" but `fields.comment.comments` is empty or has no comments | Resolution matches |
| RES-4 | QA sign-off custom field (`customfield_12319940`) is null | Status is "Closed" AND issue type is Bug or Story |

#### Appendix A Matrix Check

After all rule phases, run the required fields matrix check:
- Load `appendix-a-matrix.json`
- Look up `matrix[issue_type][status]` for the list of required fields
- Check each field (using `field_mappings` for the Jira field path)
- Skip `pr_link` (checked via PR rules)
- Report any missing required fields as a `MATRIX` violation

### Step 5: PR Correlation — MANDATORY

**THIS STEP IS NOT OPTIONAL.** When `PR_CHECK_ENABLED=true` in config, you MUST run PR correlation for every ticket in Review, In Progress, or Closed status before presenting results. Do not skip this step to save time. Do not present results without completing it. PR correlation catches the most actionable violations — without it the report is incomplete.

**Which tickets need PR checks:**
- ALL tickets in **Review** status — verify PR state matches (draft? merged? changes requested?)
- ALL tickets in **In Progress** status — verify PRs exist and are not already merged
- ALL tickets in **Closed** status — verify PRs are merged, not just closed
- Tickets in **New/Backlog** — skip (no PRs expected)

**What PR correlation catches (real examples):**

| Pattern | Rules | Why it matters |
|---------|-------|----------------|
| Ticket in Review but PR is still Draft | WF-2 | Status is ahead of reality — misleads sprint progress |
| Ticket In Progress for weeks with zero PRs | PR-2 | Zombie work — no code activity at all |
| All PRs merged but ticket not Closed | WF-4 | Missed transition — blocks release metrics |
| PR closed without merge | WF-5 | Needs manual resolution — work may be abandoned |
| Branch name missing ticket key | PR-1 | Broken traceability — bot can't discover the PR |
| 5+ tickets sharing one PR (umbrella) | PR-3 | One-ticket-per-change convention violated |
| Backport PR missing cherry-pick reference | PR-4 | Downstream verification broken |

**Execution — use ALL available layers:**

**Layer 1 — Teamwork Graph (always run first):**

Use `getTeamworkGraphContext` for each ticket:
- `cloudId`: from config
- `objectType`: `"JiraWorkItem"`
- `objectIdentifier`: ticket key (e.g., `RHOAIENG-1234`)
- `targetObjectTypes`: `["ExternalPullRequest"]`

This returns PR link count from the Jira development panel. If count > 0, proceed to Layer 2 for details. If count = 0 and ticket is In Progress or Review, flag as PR-2 (no PR links).

**Layer 2 — GitHub CLI (MUST run for every ticket with PRs or in Review/In Progress):**

Search ALL configured repos for PRs matching the ticket key:
```bash
gh pr list --repo <org/repo> --search "<KEY>" --state all \
    --json number,title,state,headRefName,mergedAt,isDraft,body,url,reviews --limit 20
```

Run this for EACH repo in `GITHUB_REPOS`. Do not search just one repo and stop. A ticket may have PRs across multiple repos (e.g., operator + tests).

For GitLab repos, use the pr_correlator.py script or `glab` directly.

**From the PR data, evaluate these rules:**

| Rule | Check | How |
|------|-------|-----|
| WF-1 | PR exists but status < In Progress | Compare ticket status position against "In Progress" in workflow order |
| WF-2 | PR ready for review but ticket ≠ Review | `state=open AND isDraft=false AND no changes_requested review` but ticket status is not "Review" |
| WF-3 | Changes requested but ticket ≠ In Progress | Any review has `state=CHANGES_REQUESTED` but ticket is not "In Progress" |
| WF-4 | All PRs merged but ticket ≠ Closed | Every PR has `mergedAt != null` but ticket status is not "Closed" |
| WF-5 | PR closed without merge | `state=closed AND mergedAt=null` — advisory notification |
| PR-1 | Branch/title missing ticket key | `ticket_key.upper() not in headRefName.upper() AND ticket_key.upper() not in title.upper()` |
| PR-2 | No PRs found but ticket is In Progress or Review | Teamwork Graph count = 0 AND `gh` search returns empty |
| PR-3 | More than 5 PRs linked | Count of unique PRs > 5 |
| PR-4 | Backport PR missing cherry-pick reference | Title/body contains "backport" or "cherry-pick" but body lacks "cherry picked from commit" |

**Layer 3 — Branch containment (for FV-2/FV-3/FV-4):**

Only run when needed (ticket has fixVersions AND merged PRs).

For each merged PR, check if the merge commit exists on each release branch:
```bash
gh api repos/<owner>/<repo>/compare/<release-branch>...<merge-sha> --jq '.status'
```
If status is "behind" or "identical", the commit is on that branch. If "ahead" or "diverged", it is not.

**Caching:** Cache PR data per ticket key. If a ticket was already checked across repos, reuse cached data.

**Graceful fallback:** If `gh`/`glab` not available AND Teamwork Graph returns no data, report each PR-dependent rule as "unable to verify — PR tool not available" instead of skipping silently. The user must see that PR rules were NOT checked.

### Step 6: Compile Violations

Collect all violations from Step 4 into a per-ticket structure:

```json
{
    "key": "RHOAIENG-1234",
    "summary": "Fix bias metric calculation",
    "status": "In Progress",
    "assignee": "user@example.com",
    "issue_type": "Bug",
    "exempt": false,
    "violations": [
        {
            "rule_id": "GEN-1",
            "category": "General",
            "severity": "high",
            "title": "Active sprint tickets must have assignee",
            "message": "Ticket RHOAIENG-1234 is in an active sprint but has no assignee",
            "auto_fixable": true,
            "fix_action": "set_assignee",
            "fix_description": "Set assignee on the ticket"
        }
    ]
}
```

### Step 7: Present Results

**Always show the report header with user context:**

```
## Jira Hygiene Report

**User:** Shelton Cyril
**Scope:** My tickets — Active Sprint (RHOAIENG, AI Safety)
**Date:** 2026-07-08
**Freeze dates:** rhoai-3.5 freezes 2026-07-24 (16 days) — from Product Pages
**Checked:** 8 | **Exempt:** 0 | **Clean:** 5 | **Violations:** 3
```

If `--team` was used, header shows:
```
**Scope:** Team — Active Sprint (RHOAIENG, AI Safety)
```

**Sprint vetting section (if any findings from Step 2b):**

```
### Sprint Vetting

| Ticket | Status | Finding |
|--------|--------|---------|
| RHOAIENG-5678 | In Progress | Not in any active sprint — may be abandoned |
| RHOAIENG-9012 | In Progress | Carried over from previous sprint |
```

**Then violations by category and per-ticket detail (same format as before):**

```
### Violations by Category

| Category | Count | Most Common Rule |
|----------|-------|-----------------|
| General | 6 | GEN-1 (3x) |
| ...
```

**Per-ticket detail and fix checkpoints (unchanged from original).**

**If ENFORCEMENT_MODE is `report-and-fix`:**

After showing each ticket's violations, present a per-ticket fix checkpoint:

**Fix violations for RHOAIENG-1234?**

- **Option 1:** Fix all auto-fixable (3 violations)
- **Option 2:** Fix selected — enter violation numbers (e.g., "1, 3")
- **Option 3:** Skip this ticket
- **Option 4:** Switch to report-only for remaining tickets

Reply with the option number.

**If ENFORCEMENT_MODE is `report-only`:**
Show results without fix checkpoints. After all tickets displayed, offer:

> "Report complete. Would you like to save the report to `~/jira-hygiene-reports/`?"

**Exempt tickets section (if any):**

```
### Exempt Tickets (hygiene-bot-ignore)

| Ticket | Summary |
|--------|---------|
| [RHOAIENG-5678](https://redhat.atlassian.net/browse/RHOAIENG-5678) | Legacy auth migration |
```

### Step 8: Apply Fixes (if approved)

Only run when `ENFORCEMENT_MODE=report-and-fix` AND user approved fixes at the Step 7 checkpoint.

For each approved fix, check the rule's `AUTO_FIX_RULES` in config to ensure it's enabled.

**Fix actions by rule:**

| Rule | MCP Tool | Action |
|------|----------|--------|
| GEN-1 | `editJiraIssue` | Set `assignee` — ask user who to assign (suggest reporter) |
| GEN-3 | `editJiraIssue` | Add `components: [{"name": "<TEAM_COMPONENT>"}]` |
| GEN-4 | `editJiraIssue` | Set `priority: {"name": "<value>"}` — ask user for priority |
| WF-1 | `transitionJiraIssue` | Transition to "In Progress" — use `getTransitionsForJiraIssue` to find transition ID |
| WF-2 | `transitionJiraIssue` | Transition to "Review" — use `getTransitionsForJiraIssue` to find transition ID |
| WF-3 | `transitionJiraIssue` | Transition to "In Progress" — use `getTransitionsForJiraIssue` to find transition ID |
| FV-1 | `editJiraIssue` | Set `fixVersions: [{"name": "<version>"}]` — ask user which version |
| RES-2 | `editJiraIssue` | Set `resolution: {"name": "<value>"}` — ask user (Fixed, Won't Fix, Duplicate, Cannot Reproduce) |

**For each fix:**

1. Look up valid transitions (for status changes): `getTransitionsForJiraIssue` with `cloudId` and `issueIdOrKey`
2. Apply the fix via the appropriate MCP tool
3. Add audit comment: `addCommentToJiraIssue` with:
   - `cloudId`: from config
   - `issueIdOrKey`: ticket key
   - `commentBody`: `"[Hygiene Check] Auto-fixed rule {RULE_ID}: {rule_title}. See [Team Jira Hygiene Rules|https://redhat.atlassian.net/wiki/spaces/RHODS/pages/431230832/Team+Jira+Hygiene+Rules]."`
   - `contentFormat`: `"markdown"`
4. Verify the fix: `getJiraIssue` with `cloudId` and `issueIdOrKey`, check the field was actually updated
5. Report result: "Fixed" or "Failed — <reason>"

**Never auto-fix without user checkpoint approval.** Every fix requires explicit approval at the per-ticket checkpoint in Step 7.

### Step 9: Save Report

Write reports to `~/jira-hygiene-reports/`:

Use the Python script:
```bash
python3 <skill-dir>/scripts/format_report.py \
    --input /tmp/hygiene-results.json \
    --scope "<scope description>" \
    --output-dir ~/jira-hygiene-reports \
    --project <JIRA_PROJECT_KEY>
```

Or write directly:
- `~/jira-hygiene-reports/<project>-<date>-<scope>.json` — structured JSON report
- `~/jira-hygiene-reports/<project>-<date>-<scope>.md` — markdown report

Report includes:
- User name and scope (my tickets vs team)
- Summary statistics
- Sprint vetting findings
- All violations with rule IDs
- Fix actions taken (if any)
- Exempt tickets
- Freeze date source and upcoming freezes
- Timestamp and scope

---

## Custom Field IDs

These may vary by Jira project. Confirm by fetching a ticket with `fields=["*all"]`:

| Field | Expected Custom Field ID | Notes |
|-------|-------------------------|-------|
| Severity | `customfield_12316142` | Bug severity (Blocker, Critical, Major, Minor) |
| QA Sign-off | `customfield_12319940` | QA validation field |
| Sprint | `customfield_10020` | Sprint field (may also be `sprint`) |

If custom field IDs don't match, update `appendix-a-matrix.json` field_mappings.

---

## Edge Cases

- **No violations found:** Report "All tickets clean" with a summary. Still save the report.
- **All tickets exempt:** Report that all tickets have `hygiene-bot-ignore`. List them.
- **Ticket not found:** JQL returns empty — report the key and move on. Don't error out the whole run.
- **MCP timeout:** Retry once. If still fails, report partial results for tickets already fetched.
- **PR tool not available:** Skip PR-dependent rules (WF-1 through WF-5, PR-1 through PR-4). Log which rules were skipped.
- **Changelog not available:** Skip WF-7. Log that it was skipped.
- **Custom field ID mismatch:** If a custom field returns null but the ticket clearly has the value in the UI, warn the user to check custom field IDs and update `appendix-a-matrix.json`.
- **Transition not available:** If `getTransitionsForJiraIssue` shows the target status is not a valid transition from current status, report "cannot auto-fix — transition not available" and skip.
- **Large sprint (>100 tickets):** Confirm with user before proceeding. Process in batches of 50.
- **Product Pages MCP unavailable:** Fall back to config.env FREEZE_DATES. If also empty, skip CF rules and inform user.
- **currentUser() fails:** Fall back to account ID from `atlassianUserInfo` call. If that also fails, ask user for their Jira display name and use `assignee = "<name>"`.
- **User has no sprint tickets:** Report "No tickets found for <name> in the active sprint" and suggest `--team` or `--open`.

## Do Not

- Do not modify any Jira ticket without explicit user approval at the per-ticket checkpoint
- Do not auto-fix rules that are not in the `AUTO_FIX_RULES` config list
- Do not skip the per-ticket checkpoint even if the user said "fix all" — show what will be fixed first
- Do not create new Jira tickets — this skill only reads and updates existing tickets
- Do not delete labels, comments, or other ticket data
- Do not post API tokens, passwords, or credentials in chat or Jira comments
- Do not ignore the `hygiene-bot-ignore` exemption
- Do not treat convention rules (👤) as errors — report them as informational/low severity
- Do not fabricate PR data — if PR tools are unavailable, report rules as "unable to verify"
- Do not rewrite config.env during a check run — freeze date refresh is in-memory only
