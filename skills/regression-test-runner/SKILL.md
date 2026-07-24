---
name: regression-test-runner
description: >
  End-to-end regression testing workflow for TrustyAI/AI Safety components.
  Accepts a component name, optional Jira ticket, and optional candidate image.
  Patches the operator if an image is provided, runs pytest against a live OCP
  cluster, analyzes failures, creates fix PRs for test bugs with code review,
  updates Jira with structured results, and reverts operator patches.
  Trigger phrases include: "run regression tests", "regression test",
  "test component", "run ai safety tests", "regression suite",
  "run nemo tests", "run evalhub tests", "run guardrails tests",
  "test hermetic image", "regression test runner".
allowed-tools: Bash Read Write Grep Glob Agent AskUserQuestion Skill
---

# Regression Test Runner

Run component regression tests against a live cluster, analyze failures, fix test bugs, report to Jira.

## Input

`$ARGUMENTS` format:

```
[component] [--jira <TICKET-KEY-OR-URL>] [--image <IMAGE-URI>] [--pr <GITHUB-PR-URL>] [--no-fix] [--markers <PYTEST-MARKERS>] [--arch <ARCH>]
```

- **component** — component name from the test map (e.g., `nemo_guardrails`, `trustyai_service`, `lm_eval`). **Optional when `--pr` is provided** — the skill auto-detects the component from the Konflux build name.
- **--jira** — existing Jira ticket key or URL. If omitted, the skill asks whether to create one
- **--image** — candidate image URI to patch into the operator before testing
- **--pr** — GitHub PR URL with a Konflux build. Auto-resolves the built image AND the component to test (see Step 2.5)
- **--arch** — architecture for Konflux image resolution: `x86-64` (default), `aarch64`, `s390x`
- **--no-fix** — skip automated fix creation for test bug failures
- **--markers** — additional pytest markers to filter tests (e.g., `smoke`, `tier1`)

## Steps

### Step 0: Parse and Validate Input

Parse `$ARGUMENTS` to extract the component name (if present) and optional flags.

Read `<skill-dir>/resources/component-test-map.json`.

If a component name was provided, look it up. If not found, print valid component names and stop.

If NO component name was provided:
- If `--pr` is set, defer component resolution to Step 2.5 (it will be auto-detected from the Konflux build name)
- If `--pr` is NOT set, print valid component names and stop with: "Component required when --pr is not provided"

Store the matched component config for later use (may be set in Step 2.5).

### Step 1: Preflight Checks

Run these checks. Each is a separate Bash call — do not combine commands.

```bash
oc whoami
```

```bash
oc whoami --show-server
```

```bash
oc version
```

If `--image` or `--pr` was provided, verify GitHub CLI is authenticated (needed for potential PR creation and image resolution):

```bash
gh auth status
```

Verify the test image exists on quay.io (non-fatal, just warn if it fails):

```bash
oc image info quay.io/opendatahub/opendatahub-tests:latest --filter-by-os=linux/amd64 2>&1 | head -3
```

Report preflight summary:
```
Cluster:   <server>
User:      <whoami>
Component: <display_name>
Test path: <test_path>
Image:     <image or "default (no patch)">
Jira:      <ticket or "will create/prompt">
```

### Step 2.5: Resolve PR to Image (conditional)

If `--pr` was provided (and `--image` was NOT), resolve the Konflux-built image from the PR.

Extract `owner/repo` and PR number from the URL. Then:

```bash
gh pr view <NUMBER> --repo <OWNER/REPO> --json headRefOid,statusCheckRollup --jq '{sha: .headRefOid, checks: [.statusCheckRollup[] | select(.name != null) | select(.name | contains("Konflux")) | .name]}'
```

From the result:
1. Get the head commit SHA
2. Get the Konflux check name (e.g., `Konflux Production Internal / odh-ta-lmes-job-on-pull-request-57892`)
3. Extract the Konflux component name: take the part after ` / `, then regex-match `(.+)-on-pull-request-\d+` — capture group 1 is the Konflux component (e.g., `odh-ta-lmes-job`)
4. Construct the image URI: `quay.io/rhoai/pull-request-pipelines:<konflux-component>-<full-sha>-linux-<ARCH>` (use `--arch` value, default `x86-64`)

If no Konflux check found, report error and stop.

If multiple Konflux checks exist, list them and ask the user which one to use.

**Verify the Konflux build succeeded** by checking the check conclusion:

```bash
gh pr view <NUMBER> --repo <OWNER/REPO> --json statusCheckRollup --jq '.statusCheckRollup[] | select(.name != null) | select(.name | contains("Konflux")) | {name: .name, conclusion: .conclusion, status: .status}'
```

If conclusion is `FAILURE`, report error and stop: "Konflux build failed. No image to test."
If conclusion is empty and status is not `COMPLETED`, warn: "Konflux build still running. Image may not exist yet."

**Verify the image exists on quay.io:**

```bash
oc image info <constructed-image-uri> --filter-by-os=linux/amd64 2>&1 | head -5
```

If the image does not exist (output contains "manifest unknown" or "not found"), report error and stop: "Image not found on quay.io. Konflux build may not have pushed the image yet."

**Auto-detect test component** (if not already specified):

Read `<skill-dir>/resources/component-test-map.json`. For each entry, check if any of its `image_patterns` is a substring of the Konflux component name. The first match determines which test suite to run.

Mapping examples:
- Konflux `odh-ta-lmes-job` contains pattern `lmes-job` → test component `lm_eval`
- Konflux `odh-trustyai-nemo-guardrails-server` contains pattern `nemo-guardrails-server` → test component `nemo_guardrails`
- Konflux `odh-trustyai-service-operator` contains pattern `trustyai-service-operator` → test component `trustyai_operator`

If no match found and no component was provided in arguments, list the known components and ask the user which to run.

If a component WAS provided in arguments, use that (explicit override).

Report:
```
Resolved from PR #<number>:
  Konflux component: <konflux-component>
  Test component:    <test-component> (<display_name>)
  Test path:         <test_path>
  SHA:               <sha>
  Image:             quay.io/rhoai/pull-request-pipelines:<konflux-component>-<sha>-linux-<arch>
```

Set the resolved image as the `--image` value and the test component config, then continue to Step 2.

### Step 2: Patch Operator Image (conditional)

If `--image` was provided, invoke the patch-operator-image skill:

Use the Skill tool with `skill: "sheltons-toolkit:patch-operator-image"` and `args: "<IMAGE_URI>"`.

If the skill reports failure, stop the entire workflow.

Set a flag `IMAGE_PATCHED=true` so Step 9 knows to revert.

### Step 3: Jira Ticket

**If `--jira` was provided:**

Fetch the ticket using the `getJiraIssue` MCP tool (use `redhat.atlassian.net` as cloudId). If the value is a URL, extract the ticket key from it (e.g., `RHOAIENG-76661` from `https://redhat.atlassian.net/browse/RHOAIENG-76661`). Store the key.

**If `--jira` was not provided:**

Ask the user:

```
No Jira ticket specified. Options:
1. Create a new ticket in RHOAIENG
2. Provide an existing ticket key
3. Skip Jira tracking (results shown in terminal only)
```

If creating:

First, look up the current user's account ID via the `atlassianUserInfo` MCP tool.

Then use the `createJiraIssue` MCP tool:
- cloudId: `redhat.atlassian.net`
- projectKey: `RHOAIENG`
- issueTypeName: `Task`
- summary: `Regression test: <display_name> — <YYYY-MM-DD>`
- description: Include component, image URI (if patched), test path, cluster server, timestamp
- contentFormat: `markdown`
- assignee_account_id: the account ID from `atlassianUserInfo`
- additional_fields:
  ```json
  {
    "components": [{"name": "<jira_component from component-test-map.json>"}],
    "labels": ["regression-test", "ai-safety"]
  }
  ```

After creation, transition to In Progress via `transitionJiraIssue` (transition ID `71`).

Store the created ticket key.

### Step 4: Run Tests On-Cluster

Tests run inside sequential Jobs on the OpenShift cluster, one per tier. This means the user's machine does not need to stay connected.

The tiers run in order: `smoke` → `tier1` → `tier2` → `tier3`. Each tier only runs if tests with that marker exist for the component. If `--markers` was explicitly provided, skip tier detection and run only the specified markers.

**4a. Set up RBAC (idempotent):**

```bash
oc create namespace test-runner --dry-run=client -o yaml | oc apply -f -
```

```bash
oc create serviceaccount test-runner -n test-runner --dry-run=client -o yaml | oc apply -f -
```

```bash
oc adm policy add-cluster-role-to-user cluster-admin -z test-runner -n test-runner
```

**4b. Detect which tiers have tests:**

If `--markers` was NOT provided, check which tiers exist for this component. For each tier in `[smoke, tier1, tier2, tier3]`, run:

```bash
python -m pytest <TEST_PATH> -m "<TIER>" --collect-only -q 2>&1 | tail -3
```

If the output shows `N tests collected` where N > 0, include that tier. If 0 tests or an error, skip that tier.

Build the list of tiers to run. Report:
```
Tiers detected for <component>:
  smoke: N tests
  tier1: N tests
  tier2: N tests
  tier3: skipped (0 tests)
```

If `--markers` WAS provided, use a single tier with that marker value.

**4c. Run each tier sequentially:**

For each tier in the detected list, run one Job and wait for it to complete before starting the next.

For each tier:

**4c-i. Delete any previous Job:**

```bash
oc delete job regression-<COMPONENT>-<TIER> -n test-runner --ignore-not-found
```

**4c-ii. Create and apply the Job:**

The Job manifest is the same template for each tier, with the tier name in the Job name and the `-m "<TIER>"` marker in the pytest command.

Also add any env vars the component needs (check the repo's `.env` file for values like `HF_ACCESS_TOKEN`).

```bash
cat <<'JOBEOF' | oc apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: regression-<COMPONENT>-<TIER>
  namespace: test-runner
  labels:
    app: regression-test-runner
    component: <COMPONENT>
    tier: <TIER>
spec:
  backoffLimit: 0
  activeDeadlineSeconds: <TIER_TIMEOUT>
  template:
    spec:
      serviceAccountName: test-runner
      restartPolicy: Never
      containers:
      - name: test-runner
        image: quay.io/opendatahub/opendatahub-tests:latest
        env:
        - name: HOME
          value: /home/odh
        - name: KUBECONFIG
          value: /tmp/kubeconfig
        <EXTRA_ENV_VARS>
        command: ["/bin/bash", "-c"]
        args:
        - |
          set -e
          cd /home/odh/opendatahub-tests
          mkdir -p results

          KUBE_TOKEN=$(cat /var/run/secrets/kubernetes.io/serviceaccount/token)
          KUBE_CA=/var/run/secrets/kubernetes.io/serviceaccount/ca.crt
          KUBE_HOST="https://${KUBERNETES_SERVICE_HOST}:${KUBERNETES_SERVICE_PORT}"

          cat > /tmp/kubeconfig << KCEOF
          apiVersion: v1
          kind: Config
          clusters:
          - cluster:
              certificate-authority: ${KUBE_CA}
              server: ${KUBE_HOST}
            name: in-cluster
          contexts:
          - context:
              cluster: in-cluster
              user: sa-user
            name: in-cluster
          current-context: in-cluster
          users:
          - name: sa-user
            user:
              token: ${KUBE_TOKEN}
          KCEOF

          uv run pytest <TEST_PATH> -v --tb=long --cluster-sanity-skip-rhoai-check -m "<TIER>"
        resources:
          requests:
            cpu: "500m"
            memory: "1Gi"
          limits:
            cpu: "2"
            memory: "4Gi"
        volumeMounts:
        - name: results
          mountPath: /home/odh/opendatahub-tests/results
      volumes:
      - name: results
        emptyDir: {}
JOBEOF
```

Replace `<COMPONENT>`, `<TIER>`, `<TEST_PATH>`, `<EXTRA_ENV_VARS>`, and `<TIER_TIMEOUT>` with actual values.

**Tier timeouts (activeDeadlineSeconds):**

| Tier | Timeout | activeDeadlineSeconds |
|------|---------|----------------------|
| smoke | 30 min | 1800 |
| tier1 | 2 hours | 7200 |
| tier2 | 3 hours | 10800 |
| tier3 | 5 hours | 18000 |

For `<EXTRA_ENV_VARS>`, check the repo's `.env` file and include relevant env vars for the component. Common ones:
- `HF_ACCESS_TOKEN` — needed for `lm_eval` tests
- Other component-specific tokens or config

**4c-iii. Wait for Job completion:**

```bash
oc wait --for=condition=complete --timeout=<TIER_TIMEOUT>s job/regression-<COMPONENT>-<TIER> -n test-runner
```

Use the same timeout value from the tier timeouts table above (e.g., `1800s` for smoke, `7200s` for tier1).

If the wait fails (job failed), check:

```bash
oc wait --for=condition=failed --timeout=5s job/regression-<COMPONENT>-<TIER> -n test-runner
```

**4c-iv. Collect tier results:**

```bash
oc logs -n test-runner -l job-name=regression-<COMPONENT>-<TIER> --tail=100
```

Parse the pytest summary line. Store results for this tier.

If failures detected, also save full logs:

```bash
oc logs -n test-runner -l job-name=regression-<COMPONENT>-<TIER> > /tmp/regression-output-<COMPONENT>-<TIER>.log
```

Report tier progress:
```
[<TIER>] complete: <passed>/<total> passed, <failed> failed, <skipped> skipped (<duration>s)
```

**4c-v. Continue to next tier** regardless of this tier's result (do not stop on failure — run all tiers to get full picture).

**4d. Aggregate results:**

After all tiers complete, aggregate into a combined summary:

```
All tiers complete:

  Tier   | Passed | Failed | Skipped | Duration
  -------|--------|--------|---------|----------
  smoke  |      5 |      0 |       0 |     12s
  tier1  |     12 |      1 |       0 |    340s
  tier2  |      8 |      0 |       2 |    210s
  tier3  |      — |      — |       — |  skipped
  -------|--------|--------|---------|----------
  Total  |     25 |      1 |       2 |    562s
```

Collect all failures across tiers for Step 5 analysis. Save combined logs to `/tmp/regression-output-<COMPONENT>.log`.

### Step 5: Analyze Failures

If there are no failures (failed == 0 and errors == 0), skip to Step 7.

For each failure (up to 5), spawn analysis agents **in parallel** (send all Agent calls in a single message). Each agent gets this prompt:

> Analyze this test failure from the `<component>` regression suite.
>
> **Test ID:** `<test_id>`
> **Error:** `<short_message>`
> **Phase:** `<phase>`
>
> Read the full test log saved at `/tmp/regression-output-<COMPONENT>.log`. Search for `FAILED <test_id>` or the test function name to find the full traceback.
>
> Then read the test source file in the local opendatahub-tests repo to understand what the test is asserting.
>
> Read any conftest.py in the same directory and parent directories if needed to understand fixtures.
>
> Classify the failure as one of:
> - **product_bug** — the product is behaving incorrectly; the test assertion is correct but the system under test fails
> - **test_bug** — the test code itself has a bug (wrong assertion, fixture error, import error, stale expectation)
> - **infrastructure** — cluster issue, timeout, network problem, resource exhaustion
> - **flaky** — non-deterministic, likely timing-related
> - **environment** — expected for this environment (e.g., hermetic images use tags not SHA256 digests)
>
> Return your analysis in this exact format:
>
> ```
> ANALYSIS_JSON_START
> {
>   "test_id": "<test_id>",
>   "classification": "<one of the above>",
>   "confidence": "high|medium|low",
>   "analysis": "<2-3 sentence explanation>",
>   "fix_suggestion": "<what to change, if test_bug>",
>   "affected_file": "<file path to fix, if test_bug>"
> }
> ANALYSIS_JSON_END
> ```

Collect all analysis results. Present a summary table:

```
| Test | Classification | Confidence | Analysis |
|------|---------------|------------|----------|
| ... | ... | ... | ... |
```

### Step 6: Create Fixes for Test Bugs (conditional)

If `--no-fix` was set, skip to Step 7.

If there are no `test_bug` classifications, skip to Step 7.

**User checkpoint — always ask before creating fixes:**

```
Found N test bug(s) that may be fixable:

| # | Test | Issue | Confidence |
|---|------|-------|------------|
| 1 | test_name | description | high |
| 2 | test_name | description | medium |

Create fix PRs? (all / pick numbers / skip)
```

For each approved fix:

1. **Create a branch** from current HEAD:
   ```bash
   git checkout -b fix/ai-safety-<short-slug>
   ```

2. **Make the fix** — edit the affected file based on the analysis and fix suggestion

3. **Run pre-commit on changed files:**
   ```bash
   pre-commit run --files <CHANGED_FILES>
   ```
   If pre-commit fails, fix the issues and re-run. Repeat up to 3 times.

4. **Commit with DCO sign-off:**
   ```bash
   git commit -s -m "$(cat <<'EOF'
   fix(ai_safety): <short description>

   <1-2 sentence explanation of what was wrong and what this fixes>

   Signed-off-by: <git user.name> <git user.email>
   EOF
   )"
   ```

5. **Push:**
   ```bash
   git push origin fix/ai-safety-<short-slug>
   ```

6. **Create PR:**
   ```bash
   gh pr create --title "fix(ai_safety): <short description>" --body "$(cat <<'EOF'
   ## Summary

   - Fixes test bug in `<test_id>`
   - Classification: test_bug (confidence: <confidence>)
   - Root cause: <analysis>

   ## Jira

   <JIRA_KEY if available>

   ## Test plan

   - [ ] Pre-commit hooks pass
   - [ ] Test passes on cluster after fix
   EOF
   )"
   ```

7. **Code review** — invoke the review skill:
   Use the Skill tool with `skill: "sheltons-toolkit:review"` and `args: "<PR_URL>"`.

8. **Return to main branch:**
   ```bash
   git checkout main
   ```

Collect all PR URLs.

### Step 7: Update Jira

If no Jira ticket is being tracked, skip to Step 8.

Build the results comment. Use the `addCommentToJiraIssue` MCP tool with `contentFormat: "markdown"` and `cloudId: "redhat.atlassian.net"`.

Comment body format:

```markdown
## Regression Test Results: <Display Name>

**Date:** <YYYY-MM-DD>
**Cluster:** <server> (OCP <version>)
**Image:** <image URI or "default">
**Run mode:** On-cluster Jobs (sequential tiers)

### Tier Summary

| Tier | Passed | Failed | Skipped | Duration | Job Status |
|------|--------|--------|---------|----------|------------|
| smoke | N | N | N | Ns | Complete/Failed |
| tier1 | N | N | N | Ns | Complete/Failed |
| tier2 | N | N | N | Ns | Complete/Failed |
| tier3 | — | — | — | — | Skipped (0 tests) |
| **Total** | **N** | **N** | **N** | **Ns** | |

### Failures

| Tier | Test | Classification | Notes |
|------|------|---------------|-------|
| tier1 | test_name | test_bug | [Fix PR](<pr-url>) |
| tier2 | test_name | product_bug | Needs investigation |
| smoke | test_name | environment | Expected for hermetic images |

### Summary

<2-3 sentence summary: how many tiers ran, what failed and why, any PRs created>
```

### Step 8: Transition Jira (conditional)

If no Jira ticket is being tracked, skip.

Determine if the ticket should be resolved:
- If ALL failures are classified as `test_bug`, `environment`, `flaky`, or `infrastructure` (i.e., zero `product_bug` failures), the component is functionally passing.
- If there are `product_bug` failures, do NOT offer to resolve.

If eligible for resolution, ask:

```
All functional tests pass (no product bugs). Transition <JIRA_KEY> to Resolved?
```

If user approves:
1. Get available transitions via `getTransitionsForJiraIssue` MCP tool
2. Find the "Resolved" transition ID
3. Call `transitionJiraIssue` MCP tool with that transition ID

### Step 9: Revert Operator Image (conditional)

If `IMAGE_PATCHED` is not set, skip.

Ask the user:

```
Operator was patched with candidate image. Revert to original? (y/n)
```

If yes, invoke the patch-operator-image skill in revert mode:
Use the Skill tool with `skill: "sheltons-toolkit:patch-operator-image"` and `args: "revert"`.

### Step 10: Final Summary

Print a complete summary:

```
## Regression Test Complete

**Component:** <display_name>
**Jira:** <KEY> (<status>)
**Cluster:** <server>

### Results
- Total: <N>
- Passed: <N>
- Failed: <N> (<M> product bugs, <K> test bugs, <J> environment/infra/flaky)
- Skipped: <N>

### Actions Taken
- [x/—] Operator patched with candidate image
- [x] Tests executed (<duration>s)
- [x/—] <N> test bug fix PR(s) created: <links>
- [x/—] Jira <KEY> updated with results
- [x/—] Jira transitioned to Resolved
- [x/—] Operator reverted to original image
```

## Learned from Trial Runs

These are hard-won lessons from real cluster testing sessions.

**DSC may not be Ready — that's fine.** The cluster's DataScienceCluster often reports `Ready: False` due to unrelated components (e.g., `trainer` with `PreConditionFailed`). The components under test (TrustyAI, Kserve) can be individually ready. Always use `--cluster-sanity-skip-rhoai-check` to bypass the global DSC ready check.

**On-cluster Job execution needs three things:**
1. `mkdir -p results` — the container image has `/home/odh/opendatahub-tests/` but not the `results/` subdirectory. Without it, pytest crashes on log file creation.
2. `HOME=/home/odh` — the container's default HOME is `/` which is read-only. Set HOME explicitly in the Job env.
3. `KUBECONFIG=/tmp/kubeconfig` — generate kubeconfig from SA token at `/tmp/kubeconfig`. The `get_client()` function in ocp_resources tries kubeconfig first and throws `ConfigException` (not `MaxRetryError`) when none exists, bypassing the in-cluster fallback. Writing a kubeconfig from the SA token is the reliable approach.

**`/home/odh` is read-only in the container.** Cannot create `.kube/` there. Use `/tmp/` for any writable files (kubeconfig, temp data).

**The `oc` binary is auto-downloaded.** The test framework downloads `oc` from the cluster's ConsoleCLIDownload resource at startup. No need to pre-install it in the Job.

**Image validation test (`validate_images`) will always fail for hermetic candidates.** These tests check for SHA256-pinned digests, but PR/hermetic images use tags. Classification: `environment`, not `product_bug` or `test_bug`.

**HF_ACCESS_TOKEN for LM Eval.** LM Eval tests need a HuggingFace access token. The conftest reads it from `os.environ.get("HF_ACCESS_TOKEN")` or `--hf-access-token` CLI arg. Set it as an env var on the Job pod — simpler than mounting a Secret. Check the repo's `.env` file for the token value.

**Konflux build status can change mid-run.** A build that showed `FAILURE` earlier may be re-triggered and show empty conclusion (in-progress). Always check both the conclusion AND verify the image exists on quay.io before proceeding.

**Test namespaces are created by fixtures.** The tests create their own namespaces (e.g., `test-lmeval-hf-tier1`, `test-nemo-guardrails`). If a Job fails mid-test, these namespaces may be left behind. Clean up with `oc delete namespace <name>` after failed runs.

**LM Eval tests create LMEvalJob CRs** that spawn their own pods. These pods pull the image from `RELATED_IMAGE_ODH_TA_LMES_JOB_IMAGE` — that's why patching the operator env var is necessary, not just patching the test Job image.

**Ruff pre-commit needs two runs.** First run auto-fixes, second run validates. The opendatahub-tests repo's pre-commit config also enforces FCN001 (keyword-only args in test functions).

## Do Not

- Do not run tests without `--cluster-sanity-skip-rhoai-check`
- Do not auto-transition Jira if any `product_bug` failures exist
- Do not create fix PRs without user approval at the checkpoint in Step 6
- Do not leave the operator patched without informing the user
- Do not push to upstream repos — only push to origin (user's fork)
- Do not skip code review when creating fix PRs
- Do not commit without `Signed-off-by` trailer (DCO requirement)
- Do not combine shell commands with `&&`, `;`, or `||`
- Do not read the full pytest log in the main agent context — always use a subagent
- Do not skip pre-commit hooks when committing fixes
- Do not patch the operator with an image that hasn't been verified to exist
- Do not forget to clean up test namespaces left by failed runs
