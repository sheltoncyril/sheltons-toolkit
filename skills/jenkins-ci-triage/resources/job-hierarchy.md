# Jenkins Job Hierarchy — RHOAI/ODH CI

Reference for how the internal RHOAI/ODH Jenkins CI is organized. This describes the job structure and orchestration model — the Jenkins base URL and credentials are supplied by the user at runtime (see `SKILL.md`), never hardcoded here.

## Job path formula

Every install+test leaf job lives at:

```
{product}[/{version}]/{clusterType}/{deploymentMode}/{provider}[/gpu/{vendor}]/{product}-{gate}
```

| Segment | Values |
|---|---|
| `product` | `rhoai` \| `odh` |
| `version` | e.g. `3.5`, `3.5-ea.1` — **RHOAI only**. ODH jobs have no version segment (ODH tracks nightly/main only) |
| `clusterType` | `managed` \| `selfmanaged` |
| `deploymentMode` | `cli` \| `live` \| `stage` \| `disconnected` \| `cli-oidc` |
| `provider` | `aws` \| `azure` \| `gcp` \| `psi` \| `rosa` \| `rosa_hcp` \| `ibm` |
| `gate` | `smoke` \| `sanity` \| `tier1` \| `tier2` \| `tier3` \| `known-issues` \| `upgrade` \| `customer-workflows` \| `master` \| GPU-flavor jobs |

Examples:
- `rhoai/3.5/selfmanaged/cli/aws/rhoai-smoke`
- `rhoai/3.5/selfmanaged/cli/aws/rhoai-sanity`
- `odh/selfmanaged/cli/gcp/odh-tier1`

Notes:
- Managed clusters are skipped for all RHOAI 3.x releases except ROSA HCP.
- OIDC (`cli-oidc`) folders only exist for versions > 3.0.
- Every leaf job — no matter the gate — runs the **same underlying pipeline** (`Jenkinsfile_rhoai_pipeline`). Only the injected parameters differ.
- A `rhoai-master` / `odh-master` job exists per folder — a manual convenience job that just triggers smoke/sanity/tier1/tier2/tier3/known-issues in that folder via booleans. Separate from the full matrix orchestrator below.

## The orchestrator: `test_matrix_run`

Lives at `DevOps/test_matrix_run`. This is what actually fans out a full regression run across providers.

1. Takes `RHOAI_VERSION_XY` (e.g. `3.5-ea.1`, or an `odh*` value → ODH mode) and reads a release-specific **test matrix** from a `rhoai-releases.yaml`-style config (or falls back to a manually typed provider table if `FETCH_TEST_MATRIX=false`).
2. Per release, the matrix lists provider entries: `provider`, `fips`, `ocp` version, `gates` (list), `managed`, optional `gpu`/`sno`/`region`/`upgrade` config.
3. For each provider it computes a cluster name, cluster type, job path, and hardware specs, then runs **one parallel Jenkins stage per provider**.
4. **Within a provider, gates run sequentially** as a chain of blocking `build job:` calls — e.g. AWS's `smoke` must finish before AWS's `sanity` starts. Different providers run fully concurrently with each other.
5. **Only the first gate in a provider's chain installs the cluster** (`INSTALL_CLUSTER`/`CREATE_IDP`/`DEPLOY_RHODS_OPERATOR`/`ADD_ICSP` all true only when `gateNumber == 0`). Every middle gate reuses the same cluster (`CLUSTER_ACTION_POST_EXECUTION = "Retain Cluster Ready"`). **Only the last gate hibernates** the cluster afterward. PSI clusters never hibernate.
   - This is why a `rhoai-smoke` build's "Started by upstream project" cause names a `test_matrix_run` build number, and why smoke/sanity/tier1 builds for the same provider on the same day share a cluster.
6. `Upgrade` gates are special-cased: they run smoke tests post-upgrade, inject `UPGRADE_*` params (from/to version, channel, deployment type), and can redirect the job path from `/cli/` to `/stage/` for OperatorHub-based upgrades.
7. ODH nightly runs get a `-odh-nightly` suffix appended to the gate name when resolving the downstream job.
8. One provider's failure (`build job:` throwing) marks the orchestrator build `FAILURE` but does **not** stop other providers' parallel branches.

## Manual/dev entry point: `rhoai-test-flow`

Lives at `DevOps/rhoai-test-flow`. Runs the exact same pipeline as every generated leaf gate job, but every parameter is exposed for manual entry — nothing is pre-filled by version/provider matrix logic.

Use this for **one-off/ad-hoc runs**: point it at an existing cluster (`INSTALL_CLUSTER=false` + a known `CLUSTER_NAME`) and enable just one component in `COMPONENTS_TESTS_CONFIG` with a custom image/branch override, without touching `test_matrix_run` or waiting for a full provider matrix. This is the tool to reach for when testing a candidate image or a single component's fix against a live cluster.

## Nightly auto-triggering

A nightly-autotrigger pipeline calls `build job: "DevOps/test_matrix_run", ...` directly — the automated entry point that fans out the full provider/gate matrix for a newly published nightly build. (Exact trigger source — UMB message listener vs. cron — wasn't conclusively pinned down; if it matters, check the nightly-autotrigger and build-info-collector pipeline definitions in the Jenkins pipeline repo.)

## Correlating related builds

Given one leaf build (e.g. `rhoai/3.5/selfmanaged/cli/aws/rhoai-smoke/48`):
- Its `causes[].shortDescription` (via `api/json`) names the upstream `test_matrix_run` build number that triggered it.
- Sibling gate builds for the same provider (e.g. `rhoai-sanity` right before/after) ran against the **same cluster** (`CLUSTER_NAME` param) if they're part of the same gate chain.
- Other providers' builds triggered by the same `test_matrix_run` number are independent parallel runs — useful for asking "did this fail on every cloud, or just AWS?" (see the main `SKILL.md` triage flow).
