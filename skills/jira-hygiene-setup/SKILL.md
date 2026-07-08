---
name: jira-hygiene-setup
description: >
  Configure Jira Hygiene Checker with project key, team component, code repos,
  workflow statuses, and enforcement preferences. Creates config.env that the
  check skill reads at startup. Auto-fetches code freeze dates from Product Pages
  when available. Run once per environment; re-run to update.
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

**Detect current user:**
Call `atlassianUserInfo` (no parameters) to get the authenticated user's display name. Show it: "Authenticated as: **<display name>**"

**Detect Product Pages MCP availability:**
Try calling `search_entities` with `q: "Red Hat AI"`. If the tool exists and returns results, Product Pages MCP is available. Store the product entity ID for Step 8.

If not available, note it for later — Step 8 will fall back to manual entry.

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

### Step 8: Code Freeze Dates

This step uses a three-tier approach: Product Pages auto-fetch, manual entry, or skip.

**8a: Try Product Pages MCP (if detected in Step 2)**

If Product Pages MCP is available:

1. Ask: "What is the Product Pages product name for your release schedule?"
   - Default: `Red Hat AI` (detected in Step 2)
   - Store as `FREEZE_PRODUCT`

2. Fetch releases:
   - Call `search_entities` with `q: "<FREEZE_PRODUCT>"` to find the product entity
   - Call `get_entity_hierarchy` with `entity_id: <product_id>`, `role: "children"`, `kind: "release"` to get active releases

3. Fetch freeze dates for each release:
   - Call `browse_schedule` with `entity_id: <release_id>`, `q: "freeze"` for each release
   - Filter for tasks with flags containing `"code"` and `"freeze"`, and `date_finish` in the future
   - Extract RHOAI code freeze dates (task names containing "RHOAI Code Freeze")

4. Present for confirmation:
   > "Found these upcoming code freeze dates from Product Pages:
   >
   > | Version | Freeze Date | Days Until |
   > |---------|-------------|------------|
   > | rhoai-3.5 | 2026-07-24 | 16 |
   > | rhoai-3.6.EA1 | 2026-08-21 | 44 |
   > | ...
   >
   > Accept these dates, or enter your own?"

5. User can accept (store with `FREEZE_SOURCE=productpages`) or override with manual dates.

**8b: If Product Pages MCP is NOT available**

Inform the user:

> "Product Pages MCP is not available in this session. It provides automatic code freeze date fetching from Red Hat's release schedule system.
>
> Product Pages is a server-side MCP plugin — if it's available in your Claude Code environment, it will be auto-detected. It requires browser-based OAuth authentication the first time. Contact your admin if you need access.
>
> You can enter freeze dates manually instead, or skip to disable code freeze rules."

Then proceed with manual entry:

> "Enter code freeze dates as comma-separated `version:date` pairs.
> Example: `rhoai-3.5:2026-07-15, rhoai-3.4.2:2026-07-20`
>
> Type 'skip' to disable code freeze rules."

If manual dates provided, store with `FREEZE_SOURCE=manual`.

**8c: Skip**

If user types 'skip', leave `FREEZE_DATES=` empty. Code freeze rules (CF-1 through CF-5) will be skipped during checks.

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
FREEZE_SOURCE=<productpages or manual or empty>
FREEZE_PRODUCT=<Product Pages product name or empty>
```

For any value the user skipped, leave the right side empty (e.g., `TEAM_COMPONENT=`).
Set `PR_CHECK_ENABLED=true` if either `GITHUB_REPOS` or `GITLAB_REPOS` is non-empty.

### Step 10: Verify and Summarize

Present the final configuration:

> "Configuration saved to `config.env`. Summary:
>
> | Category | Setting | Value | Status |
> |----------|---------|-------|--------|
> | User | Identity | `Shelton Cyril` | Verified |
> | Project | Key | `RHOAIENG` | Verified (JQL works) |
> | Project | Cloud ID | `redhat.atlassian.net` | Set |
> | Project | Component | `AI Safety` | Verified / Not configured |
> | Workflow | Statuses | `New → ... → Closed` | Set |
> | Workflow | Staleness | `14 days` | Set |
> | PR Check | GitHub repos | `7 repos` | Set / Not configured |
> | PR Check | GitLab repos | `0 repos` | Not configured |
> | Enforcement | Mode | `report-and-fix` | Set |
> | Enforcement | Auto-fix rules | `GEN-1, GEN-3, ...` | Set / None |
> | Freeze | Source | `Product Pages` | Auto-fetched / Manual / Not configured |
> | Freeze | Dates | `4 configured` | Set / Not configured |
> | Freeze | Next freeze | `rhoai-3.5: 2026-07-24 (16 days)` | — |
> | MCP | Atlassian | Connected | Verified / Not available |
> | MCP | Product Pages | Connected | Available / Not available |
> | Tools | gh CLI | Available | Verified / Not found |
> | Tools | glab CLI | Not found | — |
>
> Run `/jira-hygiene-check` to check your tickets (user-scoped by default).
> Run `/jira-hygiene-check --team` to check all team tickets."

---

## Edge Cases

- **MCP not available:** Warn but allow continuing setup. The check skill will fail with a clear error pointing to `mcp-setup.md`.
- **Project key invalid:** Error and re-ask. This is required.
- **gh/glab not found:** Set `PR_CHECK_ENABLED=false`. PR-dependent rules (WF-1 through WF-5, PR-1 through PR-4) will use Teamwork Graph API only.
- **User wants to change one setting:** Read existing config.env, present it, ask which value(s) to update, rewrite with only those changed.
- **No freeze dates:** Leave `FREEZE_DATES=` empty. Code freeze rules (CF-1 through CF-5) will be skipped during checks.
- **Product Pages MCP available but authentication required:** The MCP handles its own OAuth flow. If the tool call fails with an auth error, inform the user that Product Pages requires browser authentication and they may need to re-authenticate.
- **Product Pages returns no releases:** The product name may be wrong. Ask user to confirm or provide the correct product name.
- **Product Pages returns past freeze dates only:** Filter to future dates. If none remain, inform user and offer manual entry.

## Do Not

- Do not paste or display API tokens in chat
- Do not commit config.env to git (it may contain team-specific settings)
- Do not run hygiene checks during setup — that is the check skill's job
- Do not modify any Jira tickets during setup
- Do not install Product Pages MCP — it is server-side and either available or not
