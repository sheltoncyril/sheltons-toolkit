---
name: create-dsc
description: >
  Create a DataScienceCluster (DSC) on an OpenShift cluster with RHOAI.
  Without arguments, extracts default DSC from CSV annotation. Supports
  custom DSC YAML. Waits for Ready state. Locates olminstall automatically.
  Trigger phrases include: "create dsc", "create datasciencecluster",
  "setup dsc", "deploy dsc", "dsc create".
allowed-tools: Bash Read AskUserQuestion
---

# Create DataScienceCluster

Create a DataScienceCluster (DSC) resource on an OpenShift cluster running RHOAI, then wait for it to reach Ready state and for all pods to stabilize.

## Input

`$ARGUMENTS` format: `[path-to-custom-dsc.yaml]`

Examples:
```
/sheltons-toolkit:create-dsc
/sheltons-toolkit:create-dsc /tmp/my-custom-dsc.yaml
```

- `[path-to-custom-dsc.yaml]` -- optional. Path to a custom DSC YAML file to apply. If omitted, the default DSC is extracted from the `operatorframework.io/initialization-resource` annotation on the `rhods-operator` CSV.

## Steps

### Step 0: Parse Input

Parse `$ARGUMENTS` to extract the optional custom DSC YAML path.

If a path is provided, store it as `CUSTOM_DSC_PATH`. Otherwise, leave `CUSTOM_DSC_PATH` empty (the default DSC extraction path will be used in Step 5).

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
oc get csv -n default --no-headers 2>/dev/null | grep -i rhods
```

If no `rhods-operator` CSV found, stop with: "No rhods-operator CSV found. RHOAI must be installed before creating a DSC. Use `/sheltons-toolkit:install-rhoai-nightly` to install."

Report:
```
Preflight:
  Cluster: <server>
  User:    <whoami>
  CSV:     <csv-name>
  Mode:    custom DSC (<path>) | default DSC (from CSV annotation)
```

### Step 2: Check for Existing DSC

```bash
oc get dsc --no-headers 2>/dev/null
```

If output is non-empty, a DSC already exists. Ask the user with `AskUserQuestion`:

```
A DataScienceCluster already exists:
<dsc-output>

Delete and recreate? (yes / no)
```

If yes:

```bash
oc delete dsc --all --timeout=120s
```

Wait for deletion to complete:

```bash
oc get dsc --no-headers 2>/dev/null
```

If the DSC is still present after delete, stop with: "Failed to delete existing DSC. Check for finalizers or stuck resources."

If no, stop with: "Keeping existing DSC. No changes made."

### Step 3: Locate olminstall Repo

Search these paths in order. Each is a separate Bash call:

```bash
ls -d /Users/scyril/Desktop/Work/olminstall/create-dsc.sh 2>/dev/null
```

```bash
ls -d ../olminstall/create-dsc.sh 2>/dev/null
```

```bash
ls -d ~/olminstall/create-dsc.sh 2>/dev/null
```

```bash
ls -d /tmp/olminstall/create-dsc.sh 2>/dev/null
```

If none found, attempt clone:

```bash
git clone https://gitlab.cee.redhat.com/data-hub/olminstall.git /tmp/olminstall
```

If clone fails (no VPN, no auth), ask user with `AskUserQuestion`:
```
Could not locate or clone the olminstall repo.
Please provide the full path to your local olminstall directory.
(Clone from: https://gitlab.cee.redhat.com/data-hub/olminstall -- VPN required)
```

After obtaining a path, validate it has the required files:

```bash
ls <path>/create-dsc.sh
```

```bash
ls <path>/utils/oc_wait.sh
```

If either is missing, report which file is missing and stop.

Store `OLMINSTALL_PATH`.

### Step 4: Validate Custom DSC File (conditional)

Skip this step if `CUSTOM_DSC_PATH` is empty.

```bash
test -f <CUSTOM_DSC_PATH>
```

If the file does not exist, stop with: "Custom DSC file not found: `<CUSTOM_DSC_PATH>`"

Validate the file contains a DataScienceCluster resource:

```bash
grep -q "kind: DataScienceCluster" <CUSTOM_DSC_PATH>
```

If not found, stop with: "File `<CUSTOM_DSC_PATH>` does not appear to contain a DataScienceCluster resource."

Report: "Custom DSC file validated: `<CUSTOM_DSC_PATH>`"

### Step 5: Run create-dsc.sh

Change to the olminstall directory (required -- `create-dsc.sh` sources relative paths):

```bash
cd <OLMINSTALL_PATH>
```

Run the script. If a custom DSC path was provided, pass it as the argument. Otherwise, run without arguments to use the default CSV annotation extraction.

With custom DSC:

```bash
bash create-dsc.sh <CUSTOM_DSC_PATH>
```

Without custom DSC (default):

```bash
bash create-dsc.sh
```

Use a 600000ms timeout for this command. The script internally calls `oc_wait_for_dsc` (polls up to 60 iterations at 10s each = 600s) and `oc_wait_for_pods` (polls up to 60 iterations at 20s each = 1200s).

If the script exits with a non-zero status, capture and report the error output. Common failures:
- "Cannot find csv with name 'rhods-operator*'" -- the operator is not installed or the CSV is not in the `default` namespace
- "File '...' doesn't exist" -- the custom DSC path is wrong
- "ERROR: 'dsc' with name 'default-dsc' was not found" -- the DSC did not reach Ready in time

### Step 6: Verify DSC Ready

After the script completes, independently verify the DSC status:

```bash
oc get dsc -o jsonpath='{.items[0].metadata.name}{" "}{.items[0].status.phase}'
```

If the phase is not `Ready`, run diagnostics:

```bash
oc get dsc -o yaml | grep -A 20 "conditions:"
```

```bash
oc get pods -n redhat-ods-applications --no-headers | grep -v Running | grep -v Completed
```

Report the DSC status and any pods not in Running/Completed state.

### Step 7: Verify Pods

```bash
oc get pods -n redhat-ods-applications --no-headers | grep -v Running | grep -v Completed
```

If output is non-empty, report the unhealthy pods but do not fail -- the DSC may still be reconciling.

If output is empty:

```bash
oc get pods -n redhat-ods-applications --no-headers | wc -l
```

Report: "All <count> pods in redhat-ods-applications are Running or Completed."

### Step 8: Print Summary

Gather info:

```bash
oc get dsc -o jsonpath='{.items[0].metadata.name}'
```

```bash
oc get dsc -o jsonpath='{.items[0].status.phase}'
```

```bash
oc get csv -n default --no-headers 2>/dev/null | grep -i rhods | awk '{print $1}'
```

```bash
oc get pods -n redhat-ods-applications --no-headers | wc -l
```

Print:

```
DSC Creation Complete

  Cluster:    <cluster-api-url>
  CSV:        <csv-name>
  DSC Name:   <dsc-name>
  DSC Status: <phase>
  Mode:       custom DSC (<path>) | default (from CSV annotation)
  Pods:       <count> pods in redhat-ods-applications (all healthy)
```

If any pods are unhealthy, append:

```
  Unhealthy Pods:
    <pod-name>  <status>
    ...
```

## Learned from Trial Runs

These are hard-won lessons from real cluster testing sessions.

1. **`create-dsc.sh` MUST run from the olminstall directory.** It uses `BASE_DIR=$(dirname $(readlink -f ${BASH_SOURCE[0]}))` and sources `utils/oc_wait.sh` relative to that. Running it via an absolute path works for the script itself, but the `cd` is still needed because dsc-workarounds scripts are discovered via `${BASE_DIR}/dsc-workarounds/*.sh` glob from the script's own location.

2. **The default DSC comes from the CSV annotation, not a static file.** When no argument is given, the script queries `oc get csv -n default` for a CSV whose name starts with `rhods-operator`, then extracts the `operatorframework.io/initialization-resource` annotation. This annotation contains the full DSC JSON. If the CSV is not in the `default` namespace, the script will fail.

3. **DSC name is always `default-dsc`.** The `oc_wait_for_dsc` call hardcodes the name `default-dsc`. Custom DSC files should use this name. If a custom DSC uses a different name, the wait will time out looking for `default-dsc`.

4. **The DSC wait can take 10+ minutes.** The `oc_wait_for_phase_ready` function polls 60 times with 10s sleep (up to 600s). This is normal -- components take time to reconcile, especially on first creation.

5. **Pod wait polls for up to 20 minutes.** The `oc_wait_for_pods` function polls 60 times with 20s sleep (up to 1200s). Pods in `Init`, `ContainerCreating`, or `PodInitializing` states are expected during this period.

6. **Dependency operators must be installed before DSC creation.** If cert-manager, leader-worker-set, or rhcl-operator are missing, the DSC will be stuck in a non-Ready state. The `/sheltons-toolkit:install-rhoai-nightly` skill handles this, but standalone DSC creation assumes deps are already in place.

7. **DSC workaround scripts run automatically.** The `create-dsc.sh` script globs `dsc-workarounds/*.sh` and runs each one after applying the DSC. These are ephemeral fixes for known issues in specific RHOAI versions. The directory may be empty.

8. **The script exits non-zero on wait timeout.** Both `oc_wait_for_dsc` and `oc_wait_for_pods` call `exit 1` if their conditions are not met within the polling window. The Bash tool call will show a non-zero exit code -- always report the full output so the user can diagnose the issue.

## Do Not

- Do not run `create-dsc.sh` from a directory other than the olminstall repo root
- Do not combine shell commands with `&&`, `;`, or `||`
- Do not proceed past preflight if `oc whoami` fails
- Do not skip the existing-DSC check -- applying a second DSC without deleting the first can cause reconciliation conflicts
- Do not assume the olminstall repo is already cloned -- always search and fall back to clone
- Do not use a custom DSC with a name other than `default-dsc` without warning the user that the wait will not work
- Do not set the Bash timeout below 600000ms for the `create-dsc.sh` call -- the internal waits need up to 600s for DSC plus 1200s for pods
- Do not assume dependency operators are installed -- if DSC fails to reach Ready, suggest checking for missing deps
- Do not silently swallow script errors -- always report the full output from `create-dsc.sh` on failure
