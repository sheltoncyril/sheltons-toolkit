---
name: configure-disconnected
description: >
  Configure RHOAI operators for disconnected/air-gapped OpenShift environments.
  Handles RHCL operator WASM shim patching, pull secret propagation, and mirror
  registry configuration. Locates olminstall automatically.
  Trigger phrases include: "configure disconnected", "disconnected setup",
  "air-gapped setup", "mirror registry", "configure rhcl disconnected".
allowed-tools: Bash Read AskUserQuestion
---

# Configure Disconnected

Configure the RHCL operator for disconnected/air-gapped OpenShift environments by running `configure-disconnected-rhcl.sh` from the olminstall repository.

## Input

`$ARGUMENTS` is required:

- **A mirror registry URL** — e.g., `mirror.example.com:5000`

If `$ARGUMENTS` is empty, print usage help and stop:

```
Usage: /sheltons-toolkit:configure-disconnected <mirror-registry-url>

Example:
  /sheltons-toolkit:configure-disconnected mirror.example.com:5000

The mirror registry URL is required. This is the address of the registry
that mirrors Red Hat container images in your disconnected environment.
```

## Steps

### Step 1: Parse Input

Extract the mirror registry URL from `$ARGUMENTS`. Strip any trailing slashes. Validate that it looks like a registry address (contains at least a hostname, optionally a port). If it starts with `http://` or `https://`, strip the scheme prefix and warn the user that only the host:port portion is used.

### Step 2: Preflight Checks

Run these checks sequentially. Fail fast on any.

**2a. Cluster access:**

```bash
oc whoami
```

If this fails, report the error and stop. The user must be logged in to an OpenShift cluster.

**2b. Cluster connectivity:**

```bash
oc cluster-info 2>&1 | head -3
```

Report the cluster URL so the user can confirm they are targeting the correct cluster.

### Step 3: Verify RHCL Operator Installed

Check that the rhcl-operator has a CSV in Succeeded state:

```bash
oc get csv -A --no-headers | grep 'rhcl-operator.*Succeeded'
```

If no output, report:

```
ERROR: No Succeeded rhcl-operator CSV found on this cluster.

The RHCL operator must be installed and in Succeeded state before
running disconnected configuration. Install RHOAI first.
```

Stop the workflow.

If found, report the CSV name and namespace.

### Step 4: Locate olminstall Repository

Search for the olminstall repository containing `configure-disconnected-rhcl.sh`. Check these locations in order:

1. `$HOME/Desktop/Work/olminstall`
2. `$HOME/olminstall`
3. Sibling directory to the sheltons-toolkit repo (i.e., `<sheltons-toolkit-parent>/olminstall`)
4. Current working directory if it contains `configure-disconnected-rhcl.sh`

```bash
SCRIPT_NAME="configure-disconnected-rhcl.sh"
for candidate in "$HOME/Desktop/Work/olminstall" "$HOME/olminstall" "$(dirname "$(dirname "$(pwd)")")/olminstall" "."; do
  if [[ -f "${candidate}/${SCRIPT_NAME}" ]]; then
    echo "Found: ${candidate}/${SCRIPT_NAME}"
    break
  fi
done
```

Store the matched `<candidate>` directory as `OLMINSTALL_PATH` — Step 6 refers to it as `<path-to-olminstall>`.

If not found in any location, report:

```
ERROR: Could not locate olminstall repository.

Expected to find configure-disconnected-rhcl.sh in one of:
  - ~/Desktop/Work/olminstall
  - ~/olminstall
  - <sheltons-toolkit-parent>/olminstall

Clone the repository and try again.
```

Stop the workflow.

### Step 5: Check jq Available

The script uses `jq` to manipulate pull secret JSON. Verify it is installed:

```bash
which jq && jq --version
```

If `jq` is not found, report:

```
ERROR: jq is required but not found in PATH.

Install jq:
  brew install jq          # macOS
  sudo dnf install jq      # RHEL/Fedora
  sudo apt-get install jq  # Debian/Ubuntu
```

Stop the workflow.

### Step 6: Set MIRROR_REGISTRY and Run Script

Export the environment variable and execute the script:

```bash
export MIRROR_REGISTRY="<mirror-registry-url>"
bash "<path-to-olminstall>/configure-disconnected-rhcl.sh"
```

Capture both stdout and stderr. If the script exits with a non-zero status, report the full output and stop.

If the script prints "Skipping rhcl-operator disconnected configuration", treat this as a soft failure. Report the reason (extracted from the script output) and stop.

### Step 7: Verify Configuration

After the script completes successfully, verify the changes took effect.

**7a. Resolve the Subscription's namespace (`SUB_NS`).** Do not assume it equals the CSV namespace from Step 3 — Subscriptions aren't copied across namespaces the way CSVs are, so the Subscription named `rhcl-operator` lives in exactly one namespace. Find it directly:

```bash
oc get subscription -A --no-headers 2>/dev/null | grep rhcl-operator
```

Take the namespace (first column) as `SUB_NS`.

**7b. Subscription env vars:**

```bash
oc get subscription rhcl-operator -n <SUB_NS> -o jsonpath='{.spec.config.env}' | jq .
```

The script's own 10s sleep (see Learned Lessons) is a fixed delay, not a readiness check — on a loaded cluster it can be too short for OLM to have propagated the env vars yet. If `RELATED_IMAGE_WASMSHIM` doesn't yet contain the mirror registry URL and a `sha256:` digest, or `PROTECTED_REGISTRY` doesn't match, retry this command a few times (a few seconds apart, up to ~30s total) before treating it as a real failure.

**7c. Pull secret exists:**

```bash
oc get secret wasm-plugin-pull-secret -n openshift-ingress -o name
```

Confirm the secret exists in the `openshift-ingress` namespace.

**7d. Operator pod status:**

```bash
oc get pods -n <SUB_NS> -l app.kubernetes.io/name=rhcl-operator --no-headers
```

Confirm at least one pod is in `Running` state. If pods are in `CrashLoopBackOff` or `ImagePullBackOff`, report a warning.

### Step 8: Print Summary

```
Disconnected configuration complete.

  Cluster:          <cluster-url>
  Mirror registry:  <mirror-registry-url>
  RHCL CSV:         <csv-name> (namespace: <csv-ns>)
  Subscription NS:  <sub-ns>
  WASM image:       oci://<mirror-registry>/rhcl-1/wasm-shim-rhel9@sha256:<digest>
  Pull secret:      wasm-plugin-pull-secret in openshift-ingress
  Operator pods:    <count> Running

To verify WASM shim is working, check the WasmPlugin resources:
  oc get wasmplugin -A
```

## Learned from Trial Runs

These are hard-won lessons from real cluster testing sessions.

**MIRROR_REGISTRY must not include a scheme.** The script constructs OCI URIs as `oci://${MIRROR_REGISTRY}/rhcl-1/...`. If the env var contains `https://`, the resulting URI becomes `oci://https://mirror.example.com/...` which is invalid and causes silent pull failures. Always strip the scheme before passing.

**The RHCL CSV can exist in multiple namespaces.** OLM copies the CSV into every namespace the operator serves. The script handles this by checking `olm.copiedFrom` to find the original namespace where the Subscription lives. Do not assume the CSV namespace equals the Subscription namespace.

**The Subscription name is always `rhcl-operator`.** This is the OLM convention for RHCL. Do not attempt to discover it dynamically from the CSV — use the hardcoded name.

**Sleep after Subscription patch is intentional.** The script sleeps 10 seconds after patching the Subscription to allow OLM to propagate env var changes to the operator deployment. Do not remove this sleep or attempt to optimize it away.

**Pull secret name is hardcoded in the Kuadrant operator.** The secret must be named exactly `wasm-plugin-pull-secret` in the `openshift-ingress` namespace. The Kuadrant operator looks for this specific name — using any other name will cause WASM module pull failures in disconnected environments.

**The script exits 0 on most errors.** The script uses `exit 0` even when it skips configuration due to missing prerequisites (no CSV, no digest, etc.). This is intentional — it is called as part of a larger install pipeline where individual operator configurations are optional. Check stdout for "Skipping" messages to detect these soft failures.

**jq is required but not declared as a dependency.** The pull secret copy step pipes through `jq` to strip metadata fields. If jq is missing, the script fails mid-execution after already patching the Subscription, leaving the cluster in a partially configured state. Always verify jq availability before running.

**The WASM digest comes from CSV relatedImages, not from the registry.** The script extracts the sha256 digest from the CSV's `.spec.relatedImages` array (specifically the entry named `wasmshim`). It does not query the mirror registry. If the CSV does not have this related image entry, the script cannot determine what to mirror.

**Re-running is safe.** The Subscription patch uses `--type=merge` which is idempotent, and the pull secret creation checks for existence before creating. The script can be run multiple times without harm.

## Do Not

- Do not run the script without setting `MIRROR_REGISTRY` — the script exits silently with code 0 and does nothing
- Do not include `http://` or `https://` in the mirror registry URL
- Do not assume the CSV namespace is where the Subscription lives — always check `olm.copiedFrom`
- Do not skip the jq availability check — a missing jq causes partial configuration
- Do not combine shell commands with `&&`, `;`, or `||` — run each command separately
- Do not proceed if `oc whoami` fails — cluster access is required for every step
- Do not modify the pull secret name — it must be exactly `wasm-plugin-pull-secret`
- Do not treat script exit code 0 as success — check stdout for "Skipping" messages
- Do not run this before the RHCL operator is installed and in Succeeded state
