# Jenkins Pipeline Internals — Parameters, Components Config, Test Report Structure

Companion to `job-hierarchy.md`. This covers what happens *inside* a leaf gate job (`rhoai-smoke`, `odh-tier1`, etc.) and how to read its results.

## Two test systems run in the same build

Every leaf job build can run **both** of these, independently toggled — don't assume a suite name style tells you which system produced it, check the toggle:

1. **Legacy ods-ci Robot Framework suite** — toggled by `RUN_TESTS` (boolean). Defaults to `true` for smoke/sanity/tier1/tier2/tier3/known-issues/customer-workflows gates. Runs `ods-ci` with `--extra-robot-args '-i Smoke -e Resources-* -e ExcludeOnRHOAI'`-style tag selection.
2. **Shift-left pytest suite** (`opendatahub-tests` repo) — toggled by `QUALITY_GATES` + `COMPONENTS_TESTS_CONFIG` both being set. This is the newer, per-component containerized test layer and almost always the one worth investigating for AI Safety / AI Hub component failures.

Both write JUnit XML that gets merged into the single Jenkins `testReport` you see at `/testReport/`. A single build's `testReport` can therefore contain robot-framework-style suite names *and* pytest-style suite names side by side.

## `COMPONENTS_TESTS_CONFIG` — the shift-left test matrix

**Format:** `name,enabled,imageUrl,additionalArgs,configOverride` tuples joined by the literal separator `,@@@,`.

```
ai-safety-evalhub,true,quay.io/opendatahub/opendatahub-tests:3.5,,3.5@@@,spark-operator,true,quay.io/opendatahub/opendatahub-operator-e2e:main,,main@@@,...
```

**Where the defaults come from:** a components-testing registry (per component: `components/<name>/main.yaml`, optionally overridden per-release by `components/<name>/<version>.yaml`), plus shared base configs in `shared-frameworks/<framework>/main.yaml` that components inherit from via `copyFromFramework`. Most opendatahub-tests-based components inherit from a shared `opendatahub-tests` framework whose defaults look like:

```yaml
image:
  url: quay.io/opendatahub/opendatahub-tests
  tag: latest
  commonArgs: [-vv, --junit-xml="results/xunit_report.xml"]
setup:
  - name: component-health   # runs `-m component_health` before the component's own tests
```

A per-component `main.yaml` (e.g. `ai-safety-evalhub`) overrides specifics:

```yaml
copyFromFramework: opendatahub-tests
enablement:
  enable: true
  minRhoai: 3.5
merge:
  image:
    args: [-o junit_suite_name=ai-safety-evalhub, tests/ai_safety/evalhub/]
  qualityGatesMap:
    default:
      smoke: "-m smoke"
      sanity: "-m sanity"
      tier1: "-m tier1"
```

**This is exactly where the JUnit suite name (`ai-safety-evalhub`) and pytest marker selection (`-m smoke`, `-m sanity`...) per quality gate come from.** The `qualityGatesMap` maps a Jenkins `gate` name directly to a pytest `-m <marker>` argument scoped to that component's test directory.

**Enablement rules:** `enable: false` always wins. Otherwise `minRhoai`/`maxRhoai` gate numeric versions, or an explicit per-version key (e.g. `odh-stable: true`) for non-numeric/EA versions. If a component's `qualityGatesMap` has no entry for the requested gate, that component is silently skipped for the run (not failed).

### ⚠️ The branch/image mismatch gotcha

**Not every component tracks the release branch being tested.** A component's `main.yaml` independently declares its own image URL/tag/branch — some intentionally stay on `main`/`latest` even during a versioned release run (observed live: `spark-operator`, `codeflare-sdk`, `distributed-workloads`, `trainer`, `workbench-images`, `model-registry-upstream`, `ai-pipelines`, `mcp-lifecycle-operator`).

**Before treating a failure as a real regression for the version under test, check that component's branch in `COMPONENTS_TESTS_CONFIG`.** If it's `main`/`latest` while the run is testing e.g. `3.5`, a failure there reflects unreleased upstream code against a 3.5 cluster — not necessarily a 3.5 product bug. General principle: a test image/branch must match the product version under test, or its failures aren't comparable to that version's actual quality.

## How the merged `testReport` is assembled

1. Each enabled shift-left component runs in its **own container** (`podman run` of that component's image with its resolved args) — effectively one isolated pytest invocation per component, each producing its own xunit XML file.
2. Exit code handling: `0`=pass, `1`=some tests failed → build `UNSTABLE` (not `FAILURE`), `5`=no tests collected → logged only, anything else → hard pipeline failure.
3. All per-component xunit files, plus the legacy ods-ci robot suite's xunit (if it ran), plus a global operator/cluster health-check xunit, get merged by the post-build step into the single JUnit test report shown at `/testReport/`.
4. Component containers can run in parallel (`PARALLEL=true`) or sequentially.

## Reading a `testReport` entry

Via `{build_url}/testReport/api/json`, each case has:

| Field | Meaning |
|---|---|
| `className` | Usually `<junit_suite_name>.<test_module>` — the suite name is the component name from its `main.yaml` (e.g. `Ai Safety Evalhub.TestEvalHubMcpRoute`) |
| `name` | The specific test function |
| `status` | `PASSED` \| `FAILED` \| `REGRESSION` \| `SKIPPED` |
| `errorDetails` / `errorStackTrace` | Full pytest failure output — always read this, not just the test name |
| `age` | Number of **consecutive builds** this test has been failing |
| `failedSince` | Build number where the failure streak started |

**`age`/`failedSince` are your flakiness signal.** `age: 1` on a fresh failure = could be new or a one-off flake, worth a re-run or comparing against the previous build. `age: 15+` = a persistent, reproducible issue — not infra noise, treat as a real bug to root-cause and fix/backport.

## The shared cluster/operator health check — cascading failure pattern

`opendatahub-tests` ships a shared module (`tests/cluster_health/test_operator_health.py`, marker `operator_health`) with tests like `test_data_science_cluster_healthy` that wait for the `DataScienceCluster` resource's `Ready` condition. Multiple component test groups each end up running this same shared check as part of their own session (commonly surfacing as a per-component-named suite like `Post <Component> Operator Health`).

**Consequence:** if the DSC is stuck `Not Ready` because of one broken/misbehaving component (e.g. `mlflowoperator` stuck in `Deleting`), **every** component group's health check fails simultaneously — you'll see the identical test name fail across many unrelated suites in one build.

**Triage rule:** if you see the same test name (e.g. `test_data_science_cluster_healthy`) failing across several different suites in one build, don't treat it as N separate bugs. Pull the full `errorDetails` from any one of them — it embeds the DSC's full `status.conditions` block — and find the specific component condition that's `False`/`NotReady`. That's the real root cause; the rest are collateral.

## Key parameters reference

| Param | Meaning |
|---|---|
| `RHOAI_VERSION_XY` / `RHOAI_VERSION` | Release train, e.g. `3.5`, `3.5-ea.1`, or `odh*` (ODH mode) |
| `CLUSTER_NAME`, `CLUSTER_TYPE`, `CLUSTER_ACTION_POST_EXECUTION`, `REUSE_CLUSTER_NAME` | Cluster lifecycle/identity |
| `INSTALL_CLUSTER`, `CREATE_IDP`, `DEPLOY_RHODS_OPERATOR`, `ADD_ICSP`, `DEPROVISION_AFTER_INSTALL_FAILURE` | Per-stage install toggles |
| `PRODUCT` (`RHODS`/`ODH`), `TEAM_NAME` | Metadata |
| `KSERVE_RAW_DEPLOYMENT` | Selects `rawKserve` vs default RHOAI mode — changes which `qualityGatesMap` branch applies |
| `QUALITY_GATES` | Gate(s) to run (e.g. `Smoke`) |
| `COMPONENTS_TESTS_CONFIG` | The shift-left test matrix string — see above |
| `PARALLEL` | Shift-left components run in parallel vs sequentially |
| `RUN_TESTS` | Legacy ods-ci robot-framework layer toggle |
| `UPGRADE_RHOAI`, `UPGRADE_TO_VERSION`, `UPGRADE_TO_UPDATE_CHANNEL`, `UPDATE_CHANNEL` | Upgrade-gate params |
| `SEND_SLACK_NOTIFICATIONS`, `SLACK_CHANNEL_ID`, `SLACK_THREAD_ID` | Notifications — sent **per shift-left component**, not one monolithic message |
| `REPORT_FAILED_TESTS_TO_JIRA`, `REPORT_SKIPPED_TESTS_TO_JIRA`, `TFA_JIRA_ID` | JIRA auto-filing (only wired for the `smoke` gate from the orchestrator) |
| `OVERRIDE_ODS_BUILD_URL` | Force a specific FBC fragment/build image regardless of matrix default |

## Secrets — what NOT to do

- Never hardcode a Jenkins base URL, username, or API token in a skill, script, or committed doc. Read them from environment variables or ask interactively (see `SKILL.md`).
- Jenkins credentials in this system are Vault-backed at runtime; kubeconfigs and env files are wrapped with password-masking before being written to any workspace. Don't paste raw kubeconfig/env dumps into issue reports or docs, even as "example output."
