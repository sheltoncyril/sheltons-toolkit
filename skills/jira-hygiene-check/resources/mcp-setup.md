# Atlassian MCP — Jira Hygiene Checker Prerequisites

The hygiene checker uses the Atlassian MCP plugin for all Jira read/write operations. This must be set up once per environment.

---

## One-time Setup (human)

Agents: if MCP is missing, point the user to **this section**. Do not paste API tokens into chat.

**API token:** https://id.atlassian.com/manage-profile/security/api-tokens

### Claude Code

```bash
pip install mcp-atlassian
```

```bash
claude mcp add --scope user --transport stdio user-atlassian -- \
  uvx mcp-atlassian \
  --jira-url https://redhat.atlassian.net \
  --jira-username your.name@redhat.com \
  --jira-token YOUR_TOKEN
```

### Cursor

Add to `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "user-atlassian": {
      "command": "uvx",
      "args": [
        "mcp-atlassian",
        "--jira-url", "https://redhat.atlassian.net",
        "--jira-username", "your.name@redhat.com",
        "--jira-token", "YOUR_TOKEN"
      ]
    }
  }
}
```

Enable the server in **Cursor Settings > MCP**; restart if tools do not appear.

### Verify

Smoke-test with a read-only JQL query:
- `searchJiraIssuesUsingJql` with JQL: `project = AIPCC ORDER BY updated DESC`, `maxResults: 1`

If calls fail: restart MCP, check token, check network/VPN to `redhat.atlassian.net`.

**Do not commit** real tokens.

---

## MCP Tools Used by Hygiene Checker

| Tool | Purpose |
|------|---------|
| `searchJiraIssuesUsingJql` | Fetch tickets by sprint, JQL, or single key |
| `getJiraIssue` | Read full ticket fields including custom fields |
| `editJiraIssue` | Auto-fix: set assignee, component, priority, fixVersion, resolution |
| `transitionJiraIssue` | Auto-fix: move ticket to correct status |
| `getTransitionsForJiraIssue` | Discover valid transitions for a ticket |
| `addCommentToJiraIssue` | Audit trail comment after auto-fix |
| `getTeamworkGraphContext` | PR correlation via Jira development panel |

---

## Optional: GitHub / GitLab CLI

For PR correlation (WF-1 through WF-5, PR-1 through PR-4):

**GitHub:**
```bash
gh auth login
gh auth status
```

**GitLab:**
```bash
glab auth login
glab auth status
```

These are optional. Without them, PR checks use only the Teamwork Graph API (Jira dev panel links).

---

## Optional: Product Pages MCP

For automatic code freeze date fetching (CF-1 through CF-5):

Product Pages MCP is a **server-side plugin** — not a locally-installed MCP server. It is either available in your Claude Code environment or it is not. No `pip install` or token configuration needed.

**Detection:** The setup and check skills automatically probe for Product Pages by calling `search_entities`. If available, freeze dates are auto-fetched from Red Hat's release schedule system.

**Authentication:** Product Pages uses browser-based OAuth. The first time it's used in a session, you may be prompted to authenticate via your browser. After that, it works automatically.

**If not available:** Freeze dates can be entered manually during `/jira-hygiene-setup`, or the CF rules will be skipped. Contact your admin if you need Product Pages access.

| Tool | Purpose |
|------|---------|
| `search_entities` | Find product/release entities by name |
| `get_entity_hierarchy` | Navigate product → release tree |
| `browse_schedule` | Get schedule tasks (freeze dates) for a release |
| `list_schedule_milestones` | List milestone types (GA, Code Freeze, etc.) |
