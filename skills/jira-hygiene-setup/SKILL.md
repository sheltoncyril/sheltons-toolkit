---
name: setup
description: >
  Configure Jira Hygiene Checker with project key, team component, code repos,
  workflow statuses, and enforcement preferences. Creates config.env that the
  check skill reads at startup. Run once per environment; re-run to update.
  Trigger phrases include: "setup hygiene", "configure hygiene checker",
  "jira hygiene setup", "initialize hygiene", "reconfigure hygiene".
allowed-tools: Bash Read Write AskUserQuestion
---

# Setup — Jira Hygiene Checker Configuration

Interactive questionnaire that creates `config.env` with project-specific settings. The `/jira-hygiene-check` skill reads this file at startup.

**Usage:** `/jira-hygiene-setup`

---

## Workflow

### Step 1: Check Existing Configuration

Check if `config.env` already exists in the current working directory.

If it exists, read it and present current values:

> "You already have a hygiene checker configuration. Current values:
>
> <table of current settings>
>
> Would you like to reconfigure from scratch, or update specific values?"

If the user wants to update specific values, ask which ones and skip to the relevant step.
If the user says no changes needed, stop.

### Step 2: Auto-Detect What We Can

Run these detection commands silently and store results as suggestions:

**Detect Atlassian MCP availability:**
Try a read-only MCP call: `searchJiraIssuesUsingJql` with JQL `project = AIPCC ORDER BY updated DESC`, `maxResults: 1`, `cloudId: redhat.atlassian.net`.

If the call succeeds, MCP is available. If it fails, warn the user and point them to `skills/check/resources/mcp-setup.md`.

**Detect GitHub CLI:**
```bash
which gh && gh auth status 2>&1 | head -3
```

**Detect GitLab CLI:**
```bash
which glab && glab auth status 2>&1 | head -3
```

**Detect git remotes (for repo suggestions):**
```bash
git remote -v 2>/dev/null | grep -E '(github|gitlab)' | awk '{print $2}' | sort -u
```

### Step 3: Jira Project Settings

**3a: Project Key**

> "What is your Jira project key?
>
> Examples: `AIPCC`, `RHOAIENG`
>
> This determines which project tickets are checked."

Validate with a JQL query: `searchJiraIssuesUsingJql` with JQL `project = <KEY> ORDER BY updated DESC`, `maxResults: 1`.

If it fails, warn and ask for correction.

**3b: Cloud ID**

> "What is your Jira cloud instance?
>
> Default: `redhat.atlassian.net`
>
> Press Enter to accept the default."

**3c: Team Component (optional)**

> "What is your team's Jira component name? This scopes sprint and open-ticket queries to your team.
>
> Example: `AI Safety`, `TrustyAI`
>
> Type 'skip' if your team doesn't use components or you want to check all tickets in the project."

If provided, validate: `searchJiraIssuesUsingJql` with JQL `project = <KEY> AND component = "<COMPONENT>" ORDER BY updated DESC`, `maxResults: 1`.

### Step 4: Workflow Configuration

**4a: Workflow Statuses**

> "What are your project's workflow statuses in order?
>
> Default: `New, Refinement, To Do, In Progress, Review, Closed`
>
> These are used to detect skipped transitions (WF-7). Enter comma-separated status names, or press Enter for the AIPCC default."

**4b: Staleness Threshold**

> "How many days before an In Progress ticket is flagged as stale?
>
> Default: `14`
>
> Press Enter to accept the default."

### Step 5: Code Repository Configuration (optional)

**5a: GitHub Repos**

> "Which GitHub repositories should be searched for PRs linked to your tickets?
>
> Enter comma-separated `org/repo` pairs.
> Example: `opendatahub-io/trustyai-explainability, opendatahub-io/trustyai-service-operator`
>
> Auto-detected from git remotes: `<detected repos>`
>
> Type 'skip' to disable GitHub PR checking."

**5b: GitLab Repos**

> "Which GitLab repositories should be searched?
>
> Enter comma-separated `host:org/repo` pairs.
> Example: `gitlab.cee.redhat.com:ai/trustyai-service`
>
> Type 'skip' to disable GitLab PR checking."

### Step 6: Enforcement Preferences

**6a: Enforcement Mode**

Present as a checkpoint:

**Enforcement mode:**

- **Option 1:** Report-only — flag violations, no Jira writes
- **Option 2:** Report and fix — flag violations, then offer to auto-fix with per-ticket approval

Reply with the option number.

**6b: Auto-Fix Rules (only if report-and-fix)**

> "Which rules should be auto-fixable? Only bot-enforced rules with clear fixes are eligible:
>
> | Rule | Auto-fix Action |
> |------|----------------|
> | GEN-1 | Set assignee |
> | GEN-3 | Add team component |
> | GEN-4 | Set priority (prompts for value) |
> | WF-1 | Transition to In Progress |
> | WF-2 | Transition to Review |
> | WF-3 | Transition to In Progress |
> | FV-1 | Add fixVersion (prompts for value) |
> | RES-2 | Set resolution (prompts for value) |
>
> Enter comma-separated rule IDs, or 'all' for all of the above.
> Default: none (each fix requires manual action)."

### Step 7: Confluence Rules Page (optional)

> "What is the Confluence page ID for your team's hygiene rules?
>
> Default: `431230832` (Team Jira Hygiene Rules)
>
> This is used by the refresh-rules command. Press Enter to accept the default."

### Step 8: Code Freeze Dates (optional)

> "Do you have any upcoming code freeze dates to configure?
>
> Enter as comma-separated `version:date` pairs.
> Example: `rhoai-3.5:2026-07-15, rhoai-3.4.2:2026-07-20`
>
> Type 'skip' if you don't have freeze dates or manage them elsewhere."

### Step 9: Write Configuration

Write `config.env` at the project working directory:

```
# Jira Hygiene Checker Configuration
# Generated by /jira-hygiene-setup on <current date>
# Re-run /jira-hygiene-setup to reconfigure.

# === Jira Project ===
JIRA_PROJECT_KEY=<value>
JIRA_CLOUD_ID=<value>
TEAM_COMPONENT=<value or empty>
HYGIENE_RULES_PAGE_ID=<value>

# === Workflow ===
WORKFLOW_STATUSES=<comma-separated>
STALENESS_DAYS=<value>

# === Code Repos (PR checking) ===
GITHUB_REPOS=<comma-separated org/repo>
GITLAB_REPOS=<comma-separated host:org/repo>
PR_CHECK_ENABLED=<true or false>

# === Enforcement ===
ENFORCEMENT_MODE=<report-only or report-and-fix>
AUTO_FIX_RULES=<comma-separated rule IDs>

# === Code Freeze ===
FREEZE_DATES=<comma-separated version:date pairs>
```

For any value the user skipped, leave the right side empty (e.g., `TEAM_COMPONENT=`).
Set `PR_CHECK_ENABLED=true` if either `GITHUB_REPOS` or `GITLAB_REPOS` is non-empty.

### Step 10: Verify and Summarize

Present the final configuration:

> "Configuration saved to `config.env`. Summary:
>
> | Category | Setting | Value | Status |
> |----------|---------|-------|--------|
> | Project | Key | `AIPCC` | Verified (JQL works) |
> | Project | Cloud ID | `redhat.atlassian.net` | Set |
> | Project | Component | `AI Safety` | Verified / Not configured |
> | Workflow | Statuses | `New → ... → Closed` | Set |
> | Workflow | Staleness | `14 days` | Set |
> | PR Check | GitHub repos | `2 repos` | Set / Not configured |
> | PR Check | GitLab repos | `0 repos` | Not configured |
> | Enforcement | Mode | `report-and-fix` | Set |
> | Enforcement | Auto-fix rules | `GEN-1, GEN-3, ...` | Set / None |
> | Freeze | Dates | `1 configured` | Set / Not configured |
> | MCP | Atlassian | Connected | Verified / Not available |
> | Tools | gh CLI | Available | Verified / Not found |
> | Tools | glab CLI | Not found | — |
>
> Run `/jira-hygiene-check` to check your tickets."

---

## Edge Cases

- **MCP not available:** Warn but allow continuing setup. The check skill will fail with a clear error pointing to `mcp-setup.md`.
- **Project key invalid:** Error and re-ask. This is required.
- **gh/glab not found:** Set `PR_CHECK_ENABLED=false`. PR-dependent rules (WF-1 through WF-5, PR-1 through PR-4) will use Teamwork Graph API only.
- **User wants to change one setting:** Read existing config.env, present it, ask which value(s) to update, rewrite with only those changed.
- **No freeze dates:** Leave `FREEZE_DATES=` empty. Code freeze rules (CF-1 through CF-5) will be skipped during checks.

## Do Not

- Do not paste or display API tokens in chat
- Do not commit config.env to git (it may contain team-specific settings)
- Do not run hygiene checks during setup — that is the check skill's job
- Do not modify any Jira tickets during setup
