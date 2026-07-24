# Shelton's Toolkit

A Claude Code plugin with opinionated skills for code review, Jira hygiene, and developer workflows.

## Install

```bash
/plugin marketplace add sheltoncyril/sheltons-toolkit
```

## Skills

| Skill | Invoke | What it does |
|-------|--------|--------------|
| `review` | `/sheltons-toolkit:review <PR-URL>` | Multi-persona PR review with confidence scoring |
| `jira-hygiene-setup` | `/sheltons-toolkit:jira-hygiene-setup` | Configure project settings for Jira hygiene checks |
| `jira-hygiene-check` | `/sheltons-toolkit:jira-hygiene-check [scope]` | Check Jira tickets against team hygiene rules |
| `patch-operator-image` | `/sheltons-toolkit:patch-operator-image <image\|revert>` | Patch TrustyAI operator with a candidate image (auto-revert) |
| `regression-test-runner` | `/sheltons-toolkit:regression-test-runner <component> [flags]` | End-to-end regression tests with failure analysis and Jira reporting |

## How `review` works

Spawns 3 parallel review agents — each with a different personality and focus area:

| Persona | Focus | Catches |
|---------|-------|---------|
| **Chill** | Correctness & safety only | Bugs, security issues, breaking changes |
| **Grumpy** | Thoroughness | API design, style, AI-generated code smells, ceremony |
| **Unhinged** | Everything + approach | Over-engineering, PR hygiene, commit crimes, plausible-but-wrong code |

Findings are merged with confidence scoring:
- **3/3 agree** → High confidence — definitely real
- **2/3 agree** → Medium confidence — likely real
- **1/3 only** → Low confidence — might be noise

After review, optionally post findings as inline PR comments (asks before posting).

## How `jira-hygiene-check` works

Validates Jira tickets against [Team Jira Hygiene Rules](https://redhat.atlassian.net/wiki/spaces/RHODS/pages/431230832/Team+Jira+Hygiene+Rules) — 34 rules across 6 categories:

| Category | Rules | Checks |
|----------|-------|--------|
| General (GEN) | 7 | Assignee, description, component, priority, severity, staleness |
| Workflow (WF) | 7 | PR↔status sync, skipped transitions, backport completeness |
| PR Linking (PR) | 4 | Branch naming, ticket↔PR links, backport references |
| fixVersion (FV) | 7 | Version presence, branch match, naming conventions |
| Code Freeze (CF) | 5 | Freeze compliance, pre-freeze warnings |
| Resolution (RES) | 4 | Closure checklist, resolution value, QA sign-off |

**User-scoped by default** — checks only your tickets. Use `--team` for full component scope.

**Scope options:**
- Your sprint tickets (default): `/sheltons-toolkit:jira-hygiene-check`
- Team sprint tickets: `/sheltons-toolkit:jira-hygiene-check --team`
- Single ticket: `/sheltons-toolkit:jira-hygiene-check RHOAIENG-1234`
- Your open tickets: `/sheltons-toolkit:jira-hygiene-check --open`
- Team open tickets: `/sheltons-toolkit:jira-hygiene-check --open --team`
- Custom JQL: `/sheltons-toolkit:jira-hygiene-check --jql "..."`

**Auto-fix:** 8 rules support auto-fix (set assignee, transition status, add fixVersion, etc.) with per-ticket user approval. Configure via `/sheltons-toolkit:jira-hygiene-setup`.

**Code freeze dates:** Auto-fetched from Product Pages MCP when available. Falls back to manual dates in config.env.

**Sprint vetting:** Flags In Progress tickets not in any sprint and tickets carried over from previous sprints.

**Prerequisites:** Atlassian MCP plugin. Optional: `gh` CLI for GitHub PR correlation, `glab` for GitLab, Product Pages MCP for auto freeze dates.

## How `patch-operator-image` works

Patches the `trustyai-service-operator-controller-manager` deployment in `redhat-ods-applications` to use a hermetic candidate image. Auto-detects which `RELATED_IMAGE_*` env var and ConfigMap key to update by matching the image URI against known patterns (nemo-guardrails-server, eval-hub, lmes-job, guardrails-orchestrator, etc.).

**Steps:** Saves backup, adds `opendatahub.io/managed: "false"` annotation, patches env var + ConfigMap, does `oc rollout restart`, verifies.

**Revert:** `/sheltons-toolkit:patch-operator-image revert` restores original values from backup.

## How `regression-test-runner` works

End-to-end regression testing orchestrator for TrustyAI/AI Safety components:

1. Optionally patches the operator with a candidate image (invokes `patch-operator-image`)
2. Creates or links a Jira ticket in RHOAIENG
3. Runs pytest **on-cluster via a Kubernetes Job** (no local machine needed) using `quay.io/opendatahub/opendatahub-tests:latest`
4. Analyzes failures (product bug vs test bug vs environment vs infrastructure)
5. For test bugs: creates fix branches, runs pre-commit, opens PRs, runs multi-persona code review
6. Updates Jira with a structured results table
7. Transitions Jira to Resolved if no product bugs found
8. Reverts operator image if it was patched

**Components:** `nemo_guardrails`, `trustyai_service`, `trustyai_operator`, `lm_eval`, `guardrails`, `evalhub`, `component_health`

## Usage

```
# PR review
/sheltons-toolkit:review https://github.com/org/repo/pull/123

# Jira hygiene — first time setup
/sheltons-toolkit:jira-hygiene-setup

# Jira hygiene — check my sprint tickets (default)
/sheltons-toolkit:jira-hygiene-check

# Jira hygiene — check all team sprint tickets
/sheltons-toolkit:jira-hygiene-check --team

# Patch operator with candidate image
/sheltons-toolkit:patch-operator-image quay.io/rhoai/pull-request-pipelines:odh-trustyai-nemo-guardrails-server-rhel9-abc123-linux-x86-64

# Revert operator to original image
/sheltons-toolkit:patch-operator-image revert

# Regression test — basic
/sheltons-toolkit:regression-test-runner nemo_guardrails

# Regression test — with image patch and Jira
/sheltons-toolkit:regression-test-runner nemo_guardrails --image quay.io/rhoai/... --jira RHOAIENG-76661

# Regression test — skip auto-fix
/sheltons-toolkit:regression-test-runner trustyai_service --no-fix
```

## Contributing

PRs welcome. Add skills under `skills/<skill-name>/SKILL.md`.

## License

MIT
