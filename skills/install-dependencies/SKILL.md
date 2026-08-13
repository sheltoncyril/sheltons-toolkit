---
name: install-dependencies
description: >
  Install all RHOAI dependency operators via GitOps/Kustomize or Helm.
  Wraps setup-dependencies.sh (GitOps mode) and setup-helm.sh (Helm mode)
  from the olminstall repo. Locates or clones olminstall automatically.
  Trigger phrases include: "install dependencies", "setup dependencies",
  "install deps", "install rhoai dependencies", "setup deps".
allowed-tools: Bash Read AskUserQuestion
---

# Install Dependencies

Install all RHOAI dependency operators (Serverless, Service Mesh, Authorino, RHCL/Kuadrant, Kueue, JobSet, Leader Worker Set, Cert Manager, OpenTelemetry, Cluster Observability, Tempo, Custom Metrics Autoscaler, MariaDB) using GitOps/Kustomize or Helm via the olminstall repo scripts.

## Constants

- **GitOps script:** `setup-dependencies.sh`
- **Helm script:** `setup-helm.sh`
- **Default GitOps repo:** `https://github.com/opendatahub-io/odh-gitops.git`
- **Default branch:** `main`
- **Helm namespace:** `opendatahub-gitops`
- **Helm values (ODH):** `helm/values-odh.yaml`
- **Helm values (RHOAI):** `helm/values-rhoai.yaml`
- **Cloned repo directory:** `odh-gitops` (relative to olminstall root)

## Input

`$ARGUMENTS` format: `[--helm] [--branch <branch>] [--local] [--skip-monitoring] [--repo <url>] [--values <file>] [--set <key=value>] [--operator-type <odh|rhoai>]`

- No flags: GitOps mode with default branch `main`
- `--helm`: Use Helm mode via `setup-helm.sh` instead of GitOps/Kustomize mode
- `--branch <branch>`: Branch of the odh-gitops repository to use (default: `main`)
- `--local`: Use a local `odh-gitops` directory instead of cloning from remote
- `--skip-monitoring`: Skip monitoring operators (cluster-observability-operator, opentelemetry-product, tempo-product)
- `--repo <url>`: Custom GitOps repository URL (default: `https://github.com/opendatahub-io/odh-gitops.git`)
- `--values <file>`: (Helm only) Additional Helm values file to apply after defaults
- `--set <key=value>`: (Helm only) Custom Helm `--set` values (can be specified multiple times)
- `--operator-type <odh|rhoai>`: (Helm only) Required for Helm mode. Selects the default values file

## Steps

### Step 0: Parse Input

Parse `$ARGUMENTS` to extract flags.

If `$ARGUMENTS` is empty or only whitespace, default to GitOps mode with branch `main`.

Set defaults:
- `MODE=gitops`
- `BRANCH=main`
- `LOCAL=false`
- `SKIP_MONITORING=false`
- `REPO_URL=""` (let script use its default)
- `HELM_VALUES_FILE=""`
- `HELM_SET_VALUES=[]`
- `OPERATOR_TYPE=""`

If `--helm` is present, set `MODE=helm`.

If `MODE=helm` and `--operator-type` is not provided, ask with `AskUserQuestion`:
```
Helm mode requires an operator type. Which operator are you installing dependencies for?
Options: odh, rhoai
```

If `$ARGUMENTS` is `--help` or `-h`, print usage and stop:

```
Usage: /sheltons-toolkit:install-dependencies [options]

Modes:
  (default)            GitOps/Kustomize mode via setup-dependencies.sh
  --helm               Helm mode via setup-helm.sh

Options:
  --branch <branch>          odh-gitops branch (default: main)
  --local                    Use local odh-gitops directory instead of cloning
  --skip-monitoring          Skip monitoring operators (COO, OpenTelemetry, Tempo)
  --repo <url>               Custom GitOps repository URL
  --operator-type <odh|rhoai> (Helm only, required) Operator type for values file
  --values <file>            (Helm only) Additional Helm values file
  --set <key=value>          (Helm only) Custom Helm --set values (repeatable)

Examples:
  /sheltons-toolkit:install-dependencies
  /sheltons-toolkit:install-dependencies --branch rhoai-3.5
  /sheltons-toolkit:install-dependencies --skip-monitoring
  /sheltons-toolkit:install-dependencies --helm --operator-type rhoai
  /sheltons-toolkit:install-dependencies --helm --operator-type rhoai --branch rhoai-3.5 --skip-monitoring
  /sheltons-toolkit:install-dependencies --helm --operator-type odh --set components.dashboard.dsc.managementState=Removed
```

Then stop.

### Step 1: Preflight Checks

Run these checks. Each is a separate Bash call.

```bash
oc whoami
```

If this fails, stop with: "Not logged in to an OpenShift cluster. Run `oc login` first."

```bash
oc whoami --show-server
```

```bash
oc version
```

```bash
which git
```

If `git` is not found, stop with: "`git` is required. Install it first."

```bash
which make
```

If `make` is not found and `MODE=gitops`, stop with: "`make` is required for GitOps mode. Install it first."

If `MODE=helm`, also check:

```bash
which helm
```

If `helm` is not found, stop with: "`helm` is required for Helm mode. Install it first."

Report preflight summary:
```
Preflight:
  Cluster: <server>
  User:    <whoami>
  OCP:     <server-version>
  Mode:    GitOps / Helm
  Branch:  <branch>
```

### Step 2: Locate olminstall Repo

Search these paths in order. Each is a separate Bash call:

```bash
ls -d ../olminstall/setup-dependencies.sh 2>/dev/null
```

```bash
ls -d ~/Desktop/Work/olminstall/setup-dependencies.sh 2>/dev/null
```

```bash
ls -d ~/olminstall/setup-dependencies.sh 2>/dev/null
```

```bash
ls -d /tmp/olminstall/setup-dependencies.sh 2>/dev/null
```

If none found, check for a user-configured clone URL (olminstall is an internal Red Hat repo — its URL is never hardcoded here, only sourced from the user's own environment):

```bash
echo "${OLMINSTALL_REPO_URL:-unset}"
```

If set, attempt clone:

```bash
git clone "$OLMINSTALL_REPO_URL" /tmp/olminstall
```

If unset or the clone fails (no VPN, no auth), ask user with `AskUserQuestion`:
```
Could not locate or clone the olminstall repo.
Please provide either the full path to your local olminstall directory, or set OLMINSTALL_REPO_URL to its clone URL (internal — VPN required) and retry.
```

After obtaining a path, validate it has the required scripts. For GitOps mode:

```bash
ls <path>/setup-dependencies.sh
```

For Helm mode:

```bash
ls <path>/setup-helm.sh
```

If the required script is missing, report which file is missing and stop.

Store `OLMINSTALL_PATH`.

### Step 3: Check Existing Dependencies

Check which dependency operators are already installed. Each is a separate Bash call.

```bash
oc get csv -A --no-headers 2>/dev/null | grep -i serverless
```

```bash
oc get csv -A --no-headers 2>/dev/null | grep -i servicemesh
```

```bash
oc get csv -A --no-headers 2>/dev/null | grep -i authorino
```

```bash
oc get csv -A --no-headers 2>/dev/null | grep -iE 'rhcl|kuadrant|connectivity'
```

```bash
oc get csv -A --no-headers 2>/dev/null | grep -i kueue
```

```bash
oc get csv -A --no-headers 2>/dev/null | grep -i jobset
```

```bash
oc get csv -A --no-headers 2>/dev/null | grep -iE 'leader-worker-set|leaderworkerset'
```

```bash
oc get csv -A --no-headers 2>/dev/null | grep -i cert-manager
```

```bash
oc get csv -A --no-headers 2>/dev/null | grep -i opentelemetry
```

```bash
oc get csv -A --no-headers 2>/dev/null | grep -i 'cluster-observability'
```

```bash
oc get csv -A --no-headers 2>/dev/null | grep -i tempo
```

```bash
oc get csv -A --no-headers 2>/dev/null | grep -iE 'custom-metrics|keda'
```

```bash
oc get csv -A --no-headers 2>/dev/null | grep -i mariadb
```

Report a summary table of which operators are already present and which are missing:
```
Existing dependency operators:
  Serverless:                 <installed version / not found>
  Service Mesh:               <installed version / not found>
  Authorino:                  <installed version / not found>
  RHCL (Kuadrant):            <installed version / not found>
  Kueue:                      <installed version / not found>
  JobSet:                     <installed version / not found>
  Leader Worker Set:          <installed version / not found>
  Cert Manager:               <installed version / not found>
  OpenTelemetry:              <installed version / not found>
  Cluster Observability:      <installed version / not found>
  Tempo:                      <installed version / not found>
  Custom Metrics Autoscaler:  <installed version / not found>
  MariaDB:                    <installed version / not found>
```

### Step 4: Run Script

Change to the olminstall directory (required -- scripts use relative paths):

```bash
cd <OLMINSTALL_PATH>
```

If `LOCAL=true`, confirm `odh-gitops` actually exists before passing `-l` -- the script fails immediately otherwise:

```bash
test -d <OLMINSTALL_PATH>/odh-gitops
```

If it does not exist, stop and report: "`--local` was requested but `<OLMINSTALL_PATH>/odh-gitops` does not exist. Clone/place it there first, or drop `--local` to let the script clone it."

**GitOps mode:**

Build the command flags:
- Always start with `bash setup-dependencies.sh`
- Add `-b <BRANCH>` if branch is not `main`
- Add `-r <REPO_URL>` if a custom repo URL was provided
- Add `-l` if `LOCAL=true`
- Add `-M` if `SKIP_MONITORING=true`

```bash
bash setup-dependencies.sh <flags>
```

Run this in the background (`run_in_background: true`) rather than a synchronous timeout -- installing 16 dependency operators sequentially (some with Manual InstallPlan approval taking 2-5 minutes each, see Learned Lessons) can exceed the Bash tool's 600000ms (10-minute) foreground cap. Wait for the background completion notification before moving to Step 5.

**Helm mode:**

Build the command flags:
- Always start with `bash setup-helm.sh -o <OPERATOR_TYPE>`
- Add `-b <BRANCH>` if branch is not `main`
- Add `-r <REPO_URL>` if a custom repo URL was provided
- Add `-l` if `LOCAL=true`
- Add `-M` if `SKIP_MONITORING=true`
- Add `-f <HELM_VALUES_FILE>` if a custom values file was provided
- Add `-s <key=value>` for each custom set value

```bash
bash setup-helm.sh -o <OPERATOR_TYPE> <flags>
```

Run this in the background (`run_in_background: true`) -- same reasoning as GitOps mode above.

If the script exits with a non-zero code, capture stderr output and report the error. Do not retry automatically. Present the error to the user and suggest checking:
- Network connectivity to the GitOps repo
- Whether the branch exists
- Whether `oc` is still authenticated (`oc whoami`)
- OCP cluster health (`oc get nodes`)

### Step 5: Verify CSVs

After the script completes successfully, verify that the dependency operator CSVs are in `Succeeded` phase. Each is a separate Bash call.

```bash
oc get csv -A --no-headers 2>/dev/null | grep -i serverless
```

```bash
oc get csv -A --no-headers 2>/dev/null | grep -i servicemesh
```

```bash
oc get csv -A --no-headers 2>/dev/null | grep -i authorino
```

```bash
oc get csv -A --no-headers 2>/dev/null | grep -iE 'rhcl|kuadrant|connectivity'
```

```bash
oc get csv -A --no-headers 2>/dev/null | grep -i kueue
```

```bash
oc get csv -A --no-headers 2>/dev/null | grep -i jobset
```

```bash
oc get csv -A --no-headers 2>/dev/null | grep -iE 'leader-worker-set|leaderworkerset'
```

```bash
oc get csv -A --no-headers 2>/dev/null | grep -i cert-manager
```

If `SKIP_MONITORING` is `false`, also check:

```bash
oc get csv -A --no-headers 2>/dev/null | grep -i opentelemetry
```

```bash
oc get csv -A --no-headers 2>/dev/null | grep -i 'cluster-observability'
```

```bash
oc get csv -A --no-headers 2>/dev/null | grep -i tempo
```

Check for any CSVs not in `Succeeded` phase:

```bash
oc get csv -A --no-headers 2>/dev/null | grep -v Succeeded | grep -v Replacing
```

If any dependency CSVs are missing or not `Succeeded`, report which ones failed but do not stop. The user may need to investigate manually.

### Step 6: Print Summary

Print a summary table showing the final state of all dependency operators:

```
Dependency Installation Complete

  Cluster:          <cluster-url>
  Mode:             GitOps / Helm
  Branch:           <branch>
  Skip Monitoring:  yes / no

Operator Status:
  Operator                      Status            Version
  ----------------------------  ----------------  ----------------
  Serverless                    Succeeded         <version>
  Service Mesh                  Succeeded         <version>
  Authorino                     Succeeded         <version>
  RHCL (Kuadrant)               Succeeded         <version>
  Kueue                         Succeeded         <version>
  JobSet                        Succeeded         <version>
  Leader Worker Set             Succeeded         <version>
  Cert Manager                  Succeeded         <version>
  OpenTelemetry                 Succeeded / skip  <version>
  Cluster Observability         Succeeded / skip  <version>
  Tempo                         Succeeded / skip  <version>
  Custom Metrics Autoscaler     Succeeded         <version>
  MariaDB                       Succeeded         <version>

Failed / Missing:
  <list any that are not Succeeded, or "none">
```

If there are failures, suggest:
```
For failed operators, check:
  oc describe csv <csv-name> -n <namespace>
  oc get installplan -A | grep <operator>
  oc get events -n <namespace> --sort-by='.lastTimestamp' | tail -20
```

## Learned from Trial Runs

These are hard-won lessons from real cluster testing sessions.

**Scripts MUST run from the olminstall directory.** Both `setup-dependencies.sh` and `setup-helm.sh` use `BASE_DIR=$(dirname $(readlink -f ${BASH_SOURCE[0]}))` and source utilities via relative paths. They also clone `odh-gitops` into the current working directory. Always `cd` into the olminstall directory before running either script.

**GitOps mode runs `make` against the odh-gitops repo.** The `apply_and_verify_dependencies` function in `utils/gitops.sh` calls `make -C odh-gitops apply-and-verify-dependencies`. The `odh-gitops` directory must exist (either cloned by the script or pre-existing with `-l` flag). If `make` is not installed, the script fails with a cryptic error.

**Helm mode iterates 5 times with a 60-second sleep.** The `helm_install` function in `utils/helm.sh` runs `helm upgrade --install` five times with a 60-second sleep between iterations. This is intentional -- CRDs and operators need multiple reconciliation passes. Total runtime is 5+ minutes minimum.

**Authorino TLS setup runs after dependencies.** Both modes call `setup_authorino_tls` after the main install. In GitOps mode this runs `K8S_CLI=oc make -C odh-gitops prepare-authorino-tls` followed by another `apply-and-verify-dependencies`. In Helm mode it runs the `scripts/prepare-authorino-tls.sh` script from the odh-gitops repo. If Authorino TLS setup fails, the whole script exits non-zero.

**The `-l` flag expects `odh-gitops` in the current directory.** When `-l` (local) is passed, the scripts skip cloning and expect a directory named `odh-gitops` to exist in the current working directory (which should be the olminstall repo root). If it does not exist, the script fails immediately.

**Monitoring operators are three separate things.** The `-M` flag skips cluster-observability-operator, opentelemetry-product, and tempo-product. In GitOps mode this works by removing lines from `odh-gitops/dependencies/operators/kustomization.yaml`. In Helm mode this sets `--set` flags to disable them. The kustomization.yaml modifications are made in-place on the cloned repo, so they do not persist across re-clones.

**Helm mode requires `-o odh` or `-o rhoai`.** Without the `-o` flag, `setup-helm.sh` prints usage and exits with code 1. This selects the values file (`helm/values-odh.yaml` or `helm/values-rhoai.yaml`) which determines which dependencies are enabled.

**`setup-dependencies.sh` modifies the cloned odh-gitops in-place.** When `-M` is passed, it uses `sed -i` to remove monitoring entries from `kustomization.yaml` and `verify-dependencies.sh` inside the cloned `odh-gitops` directory. This is safe because the directory is re-cloned on the next run (unless `-l` is used).

**InstallPlan approvals may be Manual.** Some dependency operators (leader-worker-set, rhcl-operator) use `installPlanApproval: Manual`. The odh-gitops kustomize/Helm templates handle auto-approving these, but this can take 2-5 minutes per operator. Do not treat slow progress as a failure.

## Do Not

- Do not run `setup-dependencies.sh` or `setup-helm.sh` from a directory other than the olminstall repo root
- Do not run `setup-helm.sh` without the `-o` flag -- it will print usage and exit
- Do not combine shell commands with `&&`, `;`, or `||`
- Do not proceed past preflight if `oc whoami` fails
- Do not assume the olminstall repo is already cloned -- always search and fall back to cloning
- Do not run the install script as a synchronous foreground call -- dependency installation of 16 operators can exceed the Bash tool's 600000ms (10-minute) foreground cap; use `run_in_background: true`
- Do not skip the Authorino TLS verification -- if it fails, RHOAI components that depend on Authorino will not work
- Do not use `-l` flag unless you have confirmed `odh-gitops` exists in the olminstall directory
- Do not retry the script automatically on failure -- present the error to the user for investigation
- Do not assume monitoring operators are always needed -- respect the `--skip-monitoring` flag
