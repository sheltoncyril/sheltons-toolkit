---
name: jenkins-ci-triage
description: >
  Fetch and interpret RHOAI/ODH Jenkins CI regression run results (rhoai-smoke,
  rhoai-sanity, odh-tier1, etc.). Classifies failures as known/already-fixed,
  version-mismatch (component pinned to main/latest against a released branch),
  cascading infra (shared cluster/operator health check), or genuine new
  regressions, then cross-references opendatahub-tests git history to find
  existing fixes and backport them via the cherry-pick bot convention.
  Trigger phrases include: "check this jenkins run", "investigate this build",
  "triage jenkins failures", "is this a real bug or infra", "analyze rhoai-smoke",
  "jenkins ci triage".
allowed-tools: Bash Read AskUserQuestion
---

# Jenkins CI Triage

Given a Jenkins build (smoke/sanity/tier1/etc. for RHOAI or ODH), fetch its results and figure out — per failure — whether it's worth acting on, and if so, what action.

Read `resources/job-hierarchy.md` and `resources/jenkins-structure.md` once per session before starting; they explain the job structure, `COMPONENTS_TESTS_CONFIG` format, and the cascading-health-check pattern referenced below.

## Input

`$ARGUMENTS` — one or more Jenkins build URLs (e.g. `https://<jenkins-host>/job/rhoai/job/3.5/job/selfmanaged/job/cli/job/aws/job/rhoai-smoke/48/`), or a job path + build number.

## Step 0: Resolve Jenkins connection

Never hardcode a Jenkins hostname, username, or API token in any script or committed file.

1. Check environment variables: `JENKINS_BASE_URL`, `JENKINS_USER`, `JENKINS_API_TOKEN`.
2. If missing, extract the hostname from the URL the user gave you (if any) and ask for the username via `AskUserQuestion` or plain prompt. Ask the user to `export JENKINS_API_TOKEN=...` themselves rather than typing it into chat — if they paste it anyway, use it for this session only, never write it to a file, and warn them it appeared in plaintext.
3. Jenkins API auth is HTTP Basic with `username:api_token` (the token comes from the user's Jenkins profile, not their login password).

## Step 1: Fetch build metadata and test report

```bash
curl -s -u "$JENKINS_USER:$JENKINS_API_TOKEN" "$JENKINS_BASE_URL/<job-path>/<build>/api/json" -o /tmp/build.json
curl -s -u "$JENKINS_USER:$JENKINS_API_TOKEN" "$JENKINS_BASE_URL/<job-path>/<build>/testReport/api/json" -o /tmp/testreport.json
```

From `build.json`, extract via the `ParametersAction`:
- `COMPONENTS_TESTS_CONFIG` — parse into a `{component: {enabled, image, branch}}` table (split on `,@@@,` then `,` per entry — strip leading/trailing commas per entry first, the raw string has a leading comma after each `@@@`).
- `RHOAI_VERSION_XY` / `RHOAI_VERSION` / `PRODUCT` — what version/product this run is actually testing.
- `CLUSTER_NAME`, and the upstream `causes[].shortDescription` (names the triggering `test_matrix_run` build number, if any — useful for finding sibling provider builds of the same regression run).

From `testreport.json`, extract `failCount`/`passCount`/`skipCount` and, per failing case: `className`, `name`, `status`, `errorDetails`, `age`, `failedSince`.

## Step 2: Classify every failure

Work through each failed case and bucket it:

**a. Version/branch mismatch.** Map the failing suite's `className` prefix back to a component in the parsed `COMPONENTS_TESTS_CONFIG` table. If that component's `branch`/image tag is `main`/`latest` while the run's `RHOAI_VERSION_XY` is a released/EA version, flag: *"runs unreleased code — not necessarily a regression for this version."* Still worth noting, but don't treat it with the same urgency as (c)/(d).

**b. Cascading shared-fixture failure.** If the exact same test name (commonly `test_data_science_cluster_healthy` or another `operator_health`/`cluster_health`/`component_health`-marked test) fails across multiple *different* suites in the same build, treat it as **one** root cause, not N. Pull the full `errorDetails` from any one instance — it embeds the `DataScienceCluster` resource's `status.conditions` — and find the specific component condition that's `False`/`NotReady`/stuck. Report that component as the actual problem; the rest are collateral damage from the shared health gate.

**c. Persistent/known issue.** Check `age`/`failedSince`. `age` ≥ ~3 means this has failed in multiple consecutive builds — a real, reproducible bug, not a flake. `age` 0–1 means it's new (could be a fresh regression) or a one-off flake — say so explicitly and suggest comparing against the immediately preceding build for that same job/provider.

**d. Genuine new regression.** Doesn't fit a/b/c — a real, fresh, reproducible failure worth root-causing against product or test code.

## Step 3: Root-cause persistent/genuine failures

For anything landing in bucket (c) or (d) that looks like a **test bug** (not a product bug) once you've read the traceback:

1. In the `opendatahub-tests` repo, find the failing test file (`errorStackTrace` gives the path) and read it plus its git history: `git log --oneline -- <path>`.
2. Check whether a fix already exists on another branch: `git log --oneline --all -- <path>` to spot candidate fix commits, then `git merge-base --is-ancestor <fix-sha> <branch-under-test>` to confirm it's genuinely missing there.
3. If a fix exists elsewhere and is merged, this is a backport gap — follow the cherry-pick bot convention: find the merged PR that introduced the fix (`gh pr view <PR-URL-or-number>`), confirm it's merged, then comment `/cherry-pick <target-branch>` on that **original PR** (`gh pr comment <number> --body "/cherry-pick <branch>"`). A bot picks this up and opens the backport PR automatically — don't hand-cherry-pick and open a duplicate PR yourself. **Confirm with the user before posting** — it's a visible action on a shared PR.
4. If no fix exists anywhere, this is a genuinely new bug — report it clearly with the root cause and suggest whether it's product-side or test-side, but don't file anything without asking the user first.

For product-bug suspicions (operator/controller behavior, not test code), just report the finding — this skill doesn't attempt operator-side fixes.

## Step 4: Report

Summarize per build:
- Total pass/fail/skip.
- Each failure bucketed (a/b/c/d) with a one-line reason.
- For (b), the single real root cause plus the list of collateral suites.
- For (c)/(d) with a found-and-not-backported fix, the PR you'd comment on and the target branch — wait for confirmation before acting.
- If multiple provider builds from the same `test_matrix_run` run were given, note whether a failure is provider-specific or cross-cloud (cross-cloud + persistent is the strongest signal of a real regression).

Keep it terse — a table or bullet list per failure, not prose paragraphs. This is meant to be run repeatedly across many builds in a regression sweep, so favor scannable output over narrative.
