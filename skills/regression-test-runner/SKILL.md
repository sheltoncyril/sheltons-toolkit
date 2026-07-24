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

If creating, use the `createJiraIssue` MCP tool:
- cloudId: `redhat.atlassian.net`
- projectKey: `RHOAIENG`
- issueTypeName: `Task`
- summary: `Regression test: <display_name> — <YYYY-MM-DD>`
- description: Include component, image URI (if patched), test path, cluster server, timestamp
- contentFormat: `markdown`

Store the created ticket key.

### Step 4: Run Tests On-Cluster

Tests run inside a Job on the OpenShift cluster, not locally. This means the user's machine does not need to stay connected.

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

**4b. Delete any previous Job with the same name:**

```bash
oc delete job regression-<COMPONENT> -n test-runner --ignore-not-found
```

**4c. Build the pytest command:**

Start with: `uv run pytest <TEST_PATH> -v --tb=long --cluster-sanity-skip-rhoai-check`

If `--markers` was specified, append `-m "<MARKERS>"`.

**4d. Create and apply the Job:**

Use `oc apply` with a heredoc. The Job manifest:

```bash
cat <<'JOBEOF' | oc apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: regression-<COMPONENT>
  namespace: test-runner
  labels:
    app: regression-test-runner
    component: <COMPONENT>
spec:
  backoffLimit: 0
  activeDeadlineSeconds: 1800
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

          <PYTEST_COMMAND>
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

Replace `<COMPONENT>` and `<PYTEST_COMMAND>` with actual values.

**4e. Monitor the Job:**

Poll until the Job completes or fails. Use a loop with `oc get job`:

```bash
oc wait --for=condition=complete --timeout=1800s job/regression-<COMPONENT> -n test-runner
```

If that fails (job failed), check:

```bash
oc wait --for=condition=failed --timeout=5s job/regression-<COMPONENT> -n test-runner
```

**4f. Collect results:**

Get the pod name and stream logs:

```bash
oc logs -n test-runner -l job-name=regression-<COMPONENT> --tail=100
```

Parse the pytest summary from the last lines of the log output. Look for the standard pytest summary line: `N passed, N failed, N skipped in Ns`.

Also collect the full log if failures are detected:

```bash
oc logs -n test-runner -l job-name=regression-<COMPONENT>
```

Save to `/tmp/regression-output-<COMPONENT>.log` for failure analysis.

Report progress:
```
Tests complete (on-cluster): <passed>/<total> passed, <failed> failed, <skipped> skipped (<duration>s)
Job: regression-<COMPONENT> in namespace test-runner
```

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
**Branch:** <git branch>
**Run flag:** `--cluster-sanity-skip-rhoai-check`

### Results: <passed> passed, <failed> failed, <skipped> skipped

| Test | Result | Classification | Notes |
|------|--------|---------------|-------|
| test_name_1 | PASS | — | — |
| test_name_2 | FAIL | test_bug | [Fix PR](<pr-url>) |
| test_name_3 | FAIL | product_bug | Needs investigation |
| test_name_4 | FAIL | environment | Expected for hermetic images |
| test_name_5 | SKIP | — | Pre-condition not met |

**Duration:** <total>s

### Summary

<2-3 sentence summary: how many passed, what failed and why, any PRs created>
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
