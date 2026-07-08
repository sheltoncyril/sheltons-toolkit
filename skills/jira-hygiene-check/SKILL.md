---
name: jira-hygiene-check
description: >
  Check Jira tickets against team hygiene rules. User-scoped by default (your
  tickets only); use --team for full component scope. Reports violations with
  rule IDs and fixes. All evaluation is done programmatically by run_check.py —
  the agent only handles MCP calls and presenting results.
  Trigger phrases include: "check hygiene", "hygiene check", "jira hygiene",
  "sprint hygiene", "hygiene audit", "run hygiene", "hygiene report".
allowed-tools: Bash Read Write Grep Glob Agent AskUserQuestion
---

# Jira Hygiene Check

**Usage:**
- `/jira-hygiene-check` — your sprint tickets (default)
- `/jira-hygiene-check --team` — all team sprint tickets
- `/jira-hygiene-check --open` — your unresolved tickets
- `/jira-hygiene-check --open --team` — all team unresolved tickets
- `/jira-hygiene-check RHOAIENG-1234` — single ticket
- `/jira-hygiene-check --jql "..."` — custom JQL

---

## Workflow — 4 Steps Only

The agent does MCP data gathering. The Python script does ALL evaluation, PR
correlation, sprint vetting, and report formatting. Do not evaluate rules inline.

### Step 1: Setup (MCP calls)

1. Read `config.env`. If missing, tell user to run `/jira-hygiene-setup` and stop.

2. Call `atlassianUserInfo` (no params) to get display name. Store it.

3. Verify MCP: `searchJiraIssuesUsingJql` with `project = <JIRA_PROJECT_KEY> ORDER BY updated DESC`, `maxResults: 1`.

4. **Refresh freeze dates from Product Pages (best-effort):**
   - Try `search_entities` with `q: "<FREEZE_PRODUCT from config>"` (default `"Red Hat AI"`)
   - If available: `get_entity_hierarchy` for releases, then `browse_schedule` with `q: "freeze"` for each
   - Filter tasks with flags `["code", "freeze"]` and future `date_finish`, extract RHOAI code freeze dates
   - Store as `--freeze-dates` argument for run_check.py (format: `version:YYYY-MM-DD,version:YYYY-MM-DD`)
   - If unavailable: omit `--freeze-dates` flag (script falls back to config.env FREEZE_DATES)

### Step 2: Fetch Tickets (MCP call)

Build JQL based on arguments:

| Input | JQL |
|-------|-----|
| No args / `--sprint` | `project = <PROJ> AND sprint in openSprints() AND assignee = currentUser()` + optional `AND component = "<COMP>"` |
| `--team` | Same but drop `AND assignee = currentUser()` |
| `--open` | `project = <PROJ> AND resolution = Unresolved AND assignee = currentUser()` + optional component |
| `--open --team` | Same but drop assignee filter |
| `RHOAIENG-1234` | `key = RHOAIENG-1234` |
| `--jql "..."` | Verbatim |

Call `searchJiraIssuesUsingJql` with `fields: ["*all"]`, `maxResults: 50`. Paginate if needed.

**Save the full MCP response to a temp file:**
```bash
# Agent writes the JSON response to a temp file
```
Write the MCP response JSON to `/tmp/hygiene-tickets.json` using the Write tool.

If zero tickets returned, report "No tickets found for <user> in scope" and suggest `--team` or `--open`.

### Step 3: Run the Check Script

This is the ONLY evaluation step. Do NOT evaluate any rules inline. The script handles everything:
- PR correlation via `gh` CLI (searches all configured repos)
- Sprint membership vetting
- All 34 hygiene rules (GEN, WF, PR, FV, CF, RES + Appendix A matrix)
- Report formatting (markdown output)

```bash
python3 <skill-dir>/scripts/run_check.py \
    --tickets /tmp/hygiene-tickets.json \
    --config config.env \
    --resources-dir <skill-dir>/resources \
    --project <JIRA_PROJECT_KEY> \
    --scope "<scope description>" \
    --user "<display name from Step 1>" \
    --output-dir ~/jira-hygiene-reports \
    [--freeze-dates "<from Product Pages Step 1.4>"]
```

Where `<skill-dir>` is the base directory for this skill (provided in the skill invocation header).

The script outputs:
- **stdout**: Markdown report — display this directly to the user
- **stderr**: Progress messages + `[FIXABLE]` section listing auto-fixable violations

### Step 4: Handle Fixes (only if ENFORCEMENT_MODE=report-and-fix)

Parse the `[FIXABLE]` lines from stderr. If there are auto-fixable violations AND `ENFORCEMENT_MODE=report-and-fix` in config:

Present a checkpoint:

**Fix violations?**

- **Option 1:** Fix all auto-fixable (<N> violations)
- **Option 2:** Pick specific tickets
- **Option 3:** Skip fixes

If user approves fixes, apply them via MCP:

| fix_action | MCP call |
|------------|----------|
| `set_assignee` | `editJiraIssue` — ask user who to assign |
| `set_component` | `editJiraIssue` — `components: [{"name": "<TEAM_COMPONENT>"}]` |
| `set_priority` | `editJiraIssue` — ask user for priority value |
| `set_fix_version` | `editJiraIssue` — ask user which version |
| `set_resolution` | `editJiraIssue` — ask user (Fixed/Won't Fix/Duplicate/Cannot Reproduce) |
| `transition_forward` | `getTransitionsForJiraIssue` then `transitionJiraIssue` |
| `transition_to_review` | `getTransitionsForJiraIssue` then `transitionJiraIssue` |
| `transition_to_in_progress` | `getTransitionsForJiraIssue` then `transitionJiraIssue` |

After each fix:
1. Add audit comment: `addCommentToJiraIssue` with `"[Hygiene Check] Auto-fixed {RULE_ID}"`
2. Verify: `getJiraIssue` to confirm field was updated

**Per-ticket approval required.** Show what will change before applying.

---

## Do Not

- Do not evaluate rules inline — the script handles ALL rule logic
- Do not skip running run_check.py and try to produce the report yourself
- Do not modify tickets without explicit user approval at a checkpoint
- Do not create new Jira tickets
- Do not post credentials in chat or Jira comments
- Do not rewrite config.env during a check run
