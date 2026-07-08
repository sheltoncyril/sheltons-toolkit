---
name: check
description: >
  Check Jira tickets against team hygiene rules. Supports single ticket, sprint,
  JQL, or all-open checks. Reports violations with rule IDs and actionable fixes.
  Opt-in auto-fix transitions status, sets fields, and posts audit comments with
  per-ticket user approval. Trigger phrases include: "check hygiene", "hygiene check",
  "jira hygiene", "check ticket hygiene", "sprint hygiene", "hygiene audit",
  "run hygiene", "hygiene report".
allowed-tools: Bash Read Write Grep Glob Agent AskUserQuestion
---

# Jira Hygiene Check

Validate Jira tickets against team hygiene rules. Reports violations with rule IDs, severity, and fixes. Optionally auto-fixes with per-ticket approval.

**Usage:**
- `/jira-hygiene-check AIPCC-1234` — single ticket
- `/jira-hygiene-check --sprint` — active sprint
- `/jira-hygiene-check --jql "project = AIPCC AND status = 'In Progress'"` — custom JQL
- `/jira-hygiene-check --open` — all unresolved tickets
- `/jira-hygiene-check` — prompted to pick scope

**Rules reference:** [Team Jira Hygiene Rules](https://redhat.atlassian.net/wiki/spaces/RHODS/pages/431230832/Team+Jira+Hygiene+Rules)

---

## Workflow

### Step 0: Load Configuration

Read `config.env` from the current working directory.

If `config.env` does not exist:
> "No configuration found. Run `/jira-hygiene-setup` first to configure your project."
Stop.

Parse config into variables. Load resource files relative to this skill:
- `resources/hygiene-rules.json` — rule definitions
- `resources/appendix-a-matrix.json` — required fields matrix
- `resources/appendix-b-versions.json` — fixVersion naming patterns

Verify MCP connectivity with a read-only JQL query:
`searchJiraIssuesUsingJql` with JQL `project = <JIRA_PROJECT_KEY> ORDER BY updated DESC`, `maxResults: 1`, `cloudId: <JIRA_CLOUD_ID>`.

If MCP fails, stop and point user to `resources/mcp-setup.md`.

### Step 1: Determine Scope

Parse the user's input to determine check mode:

**If argument is a ticket key** (matches `[A-Z]+-\d+` pattern):
- Mode: single ticket
- JQL: `key = <KEY>`

**If argument is `--sprint`:**
- Mode: active sprint
- JQL: `project = <JIRA_PROJECT_KEY> AND sprint in openSprints()`
- If `TEAM_COMPONENT` is set, append: `AND component = "<TEAM_COMPONENT>"`
- Order: `ORDER BY status ASC, priority DESC`

**If argument is `--jql "<query>"`:**
- Mode: custom JQL
- JQL: user-provided query verbatim

**If argument is `--open`:**
- Mode: all unresolved
- JQL: `project = <JIRA_PROJECT_KEY> AND resolution = Unresolved`
- If `TEAM_COMPONENT` is set, append: `AND component = "<TEAM_COMPONENT>"`
- Order: `ORDER BY status ASC, updated DESC`

**If no arguments:**
Present a checkpoint:

**Check scope:**

- **Option 1:** Active sprint — tickets in the current sprint
- **Option 2:** All open — all unresolved tickets for the project/component
- **Option 3:** Custom JQL — provide your own query
- **Option 4:** Cancel

Reply with the option number.

If Option 3, ask for the JQL query.

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
| GEN-4 | `fields.priority` is null or name is "Normal" | Always |
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

Only run if `FREEZE_DATES` is configured in config.env.

Parse freeze dates: `version:YYYY-MM-DD` pairs.

| Rule | Check |
|------|-------|
| CF-1 | Informational — freeze dates configured? Log to report |
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

### Step 5: PR Correlation

Run only if `PR_CHECK_ENABLED=true` in config.

For each ticket being checked, gather PR data using a layered approach:

**Layer 1 — Teamwork Graph (always available with MCP):**

Use `getTeamworkGraphContext`:
- `cloudId`: from config
- `objectType`: `"JiraWorkItem"`
- `objectIdentifier`: ticket key (e.g., `AIPCC-1234`)
- `targetObjectTypes`: `["ExternalPullRequest"]`

This returns PR links from the Jira development panel. Extract PR URLs, states, and basic metadata.

**Layer 2 — GitHub CLI (if `gh` available and GITHUB_REPOS configured):**

For richer PR data (branch names, review states, draft status, body), use the Python script:
```bash
python3 <skill-dir>/scripts/pr_correlator.py \
    --ticket-key <KEY> \
    --github-repos "<GITHUB_REPOS from config>" \
    --gitlab-repos "<GITLAB_REPOS from config>" \
    --output /tmp/<KEY>-prs.json
```

Or call `gh` directly:
```bash
gh pr list --repo <org/repo> --search "<KEY>" --state all \
    --json number,title,state,headRefName,mergedAt,isDraft,body,url,reviews --limit 20
```

**Layer 3 — Branch containment (for FV-2/FV-3/FV-4):**

Only run when needed (ticket has fixVersions AND merged PRs).

For each merged PR, check if the merge commit exists on each release branch:
```bash
gh api repos/<owner>/<repo>/compare/<release-branch>...<merge-sha> --jq '.status'
```

**Caching:** Cache PR data per ticket key. If a ticket was already checked, reuse cached data.

**Graceful fallback:** If `gh`/`glab` not available, use Teamwork Graph data only. PR-dependent rules that need branch/review state will report "unable to verify — PR tool not available" instead of false positives.

### Step 6: Compile Violations

Collect all violations from Step 4 into a per-ticket structure:

```json
{
    "key": "AIPCC-1234",
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
            "message": "Ticket AIPCC-1234 is in an active sprint but has no assignee",
            "auto_fixable": true,
            "fix_action": "set_assignee",
            "fix_description": "Set assignee on the ticket"
        }
    ]
}
```

### Step 7: Present Results

**Always show the batch summary first:**

```
## Jira Hygiene Report

**Scope:** Active Sprint (AIPCC, AI Safety)
**Date:** 2026-07-08
**Checked:** 23 | **Exempt:** 2 | **Clean:** 14 | **Violations:** 7

### Violations by Category

| Category | Count | Most Common Rule |
|----------|-------|-----------------|
| General | 6 | GEN-1 (3x) |
| Workflow | 3 | WF-2 (2x) |
| fixVersion | 3 | FV-1 (2x) |
| Resolution | 1 | RES-2 (1x) |

### Per-Ticket Detail

| Ticket | Type | Status | Assignee | Violations | Rules |
|--------|------|--------|----------|------------|-------|
| [AIPCC-1234](https://redhat.atlassian.net/browse/AIPCC-1234) | Bug | In Progress | unassigned | 3 | GEN-1, GEN-4, FV-1 |
| ... |
```

**Then show detailed violations per ticket:**

For each ticket with violations, show the violation table:

```
#### AIPCC-1234 — Fix bias metric calculation

| # | Rule | Severity | Violation | Auto-fix | Fix |
|---|------|----------|-----------|----------|-----|
| 1 | GEN-1 | high | No assignee in sprint | Yes | Set assignee |
| 2 | GEN-4 | medium | Default priority | Yes | Set priority |
| 3 | FV-1 | high | No fixVersion, PR merged | Yes | Add fixVersion |
```

**If ENFORCEMENT_MODE is `report-and-fix`:**

After showing each ticket's violations, present a per-ticket fix checkpoint:

**Fix violations for AIPCC-1234?**

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
| [AIPCC-5678](https://redhat.atlassian.net/browse/AIPCC-5678) | Legacy auth migration |
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
- Summary statistics
- All violations with rule IDs
- Fix actions taken (if any)
- Exempt tickets
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
