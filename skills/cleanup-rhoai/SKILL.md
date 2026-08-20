---
name: cleanup-rhoai
description: >
  Clean up RHOAI from an OpenShift cluster. Standard mode removes RHOAI only
  (keeps dependency operators). Nuke mode removes RHOAI plus all dependency
  operators (cert-manager, leader-worker-set, connectivity-link, ServiceMesh,
  Serverless, etc.). Uses the olminstall repo's cleanup scripts. Locates or
  clones the olminstall repo automatically.
  Trigger phrases include: "cleanup rhoai", "clean up rhoai", "uninstall rhoai",
  "remove rhoai", "cleanup cluster", "nuke rhoai", "nuke cluster",
  "rhoai cleanup", "clean cluster".
allowed-tools: Bash Read AskUserQuestion
---

# Cleanup RHOAI

Remove RHOAI from an OpenShift cluster. Two modes: standard (RHOAI only) and nuke (RHOAI + all dependency operators).

## Input

`$ARGUMENTS` format: `[--nuke]`

- No args or empty: standard cleanup — removes RHOAI, keeps dependency operators (cert-manager, leader-worker-set, etc.)
- `--nuke`: complete cleanup — removes RHOAI AND all dependency operators (ServiceMesh, Serverless, Authorino, Limitador, cert-manager, Kueue, JobSet, Leader Worker Set, Connectivity Link, etc.)

## Steps

### Step 0: Parse Input

Check if `$ARGUMENTS` contains `--nuke`. Set `NUKE_MODE=true` or `NUKE_MODE=false`.

### Step 1: Preflight Checks

```bash
oc whoami
```

If this fails, stop with: "Not logged in to an OpenShift cluster. Run `oc login` first."

```bash
oc whoami --show-server
```

Store cluster URL and username.

### Step 2: Check if RHOAI is Installed

```bash
oc get csv -n redhat-ods-operator --no-headers 2>/dev/null | grep -i rhods
```

If empty, broaden the search:

```bash
oc get csv -A --no-headers 2>/dev/null | grep -iE 'rhods|rhoai|opendatahub'
```

If both are empty, report "RHOAI is not installed on this cluster." and stop.

If found, capture the CSV name and version for the confirmation message.

### Step 3: Locate olminstall Repo

Search these paths in order. Each is a separate Bash call:

```bash
ls -d ../olminstall/cleanup.sh 2>/dev/null
```

```bash
ls -d ~/Desktop/Work/olminstall/cleanup.sh 2>/dev/null
```

```bash
ls -d ~/olminstall/cleanup.sh 2>/dev/null
```

```bash
ls -d /tmp/olminstall/cleanup.sh 2>/dev/null
```

If none found, check for a user-configured clone URL (olminstall is an internal Red Hat repo — its URL is never hardcoded here, only sourced from the user's own environment):

```bash
echo "${OLMINSTALL_REPO_URL:-unset}"
```

If `/tmp/olminstall` exists but wasn't matched above (stale/partial clone from a prior run), check whether it is a git clone (non-empty output means it is):

```bash
ls -d /tmp/olminstall/.git 2>/dev/null
```

If it is a git clone, pull instead of cloning:

```bash
git -C /tmp/olminstall pull
```

Otherwise, if set, attempt clone:

```bash
git clone "$OLMINSTALL_REPO_URL" /tmp/olminstall
```

If unset or the clone fails, ask user with `AskUserQuestion`:
```
Could not locate or clone the olminstall repo.
Please provide either the full path to your local olminstall directory, or set OLMINSTALL_REPO_URL to its clone URL (internal — VPN required) and retry.
```

Validate the required script exists:

```bash
ls <path>/cleanup.sh
```

For nuke mode, also validate:

```bash
ls <path>/complete-cleanup.sh
```

Store `OLMINSTALL_PATH`.

**Keep the repo current.** If `OLMINSTALL_PATH` is a git clone, the cleanup scripts (`cleanup.sh`, `complete-cleanup.sh`, `remove-stuck-crds.sh`) get bug fixes over time — a stale local clone can carry the very bugs noted in "Learned from Trial Runs". Check whether it's a git working copy (non-empty output means it is a git clone):

```bash
ls -d <OLMINSTALL_PATH>/.git 2>/dev/null
```

If it is a git clone, and the `OLMINSTALL_AUTO_UPDATE` preference is not already set, ask with `AskUserQuestion`:
```
The olminstall repo at <OLMINSTALL_PATH> may be out of date. Update it before running cleanup?
```
Options:
- `Update` — pull once now
- `Always update` — pull now and on every future run without asking
- `No` — use the repo as-is

Honor the answer:
- `Update` or `Always update`: `git -C <OLMINSTALL_PATH> pull`
- `Always update`: also record the preference so future runs skip the prompt — set `OLMINSTALL_AUTO_UPDATE=1` (e.g. suggest the user add it to their shell profile) and treat it as "always pull" whenever it is set on subsequent runs.
- `No`: proceed without pulling.

If `OLMINSTALL_AUTO_UPDATE` is already set (`echo "${OLMINSTALL_AUTO_UPDATE:-unset}"` is not `unset`), skip the question and just run `git -C <OLMINSTALL_PATH> pull`. Never pull a repo that isn't a git clone, and never pull a path the user just typed in as a one-off without asking.

### Step 4: User Confirmation

Use `AskUserQuestion` to confirm.

For **standard mode**, present:
```
About to clean up RHOAI from the cluster.

  Cluster:  <cluster-url>
  User:     <username>
  CSV:      <csv-name>
  Mode:     Standard (RHOAI only, dependency operators kept)

This will remove the RHOAI operator, DSC, DSCI, and all RHOAI namespaces.

Proceed?
```

Options: `Yes, proceed` / `No, cancel`

For **nuke mode**, present:
```
About to perform COMPLETE cleanup of RHOAI and ALL dependency operators.

  Cluster:  <cluster-url>
  User:     <username>
  CSV:      <csv-name>
  Mode:     Nuke (RHOAI + all dependency operators)

This will remove RHOAI, ServiceMesh, Serverless, Authorino, Limitador,
cert-manager, Kueue, JobSet, Leader Worker Set, Connectivity Link,
and all related CRDs, webhooks, and cluster resources.

Proceed?
```

Options: `Yes, nuke it` / `No, cancel`

If user cancels, stop with: "Cleanup cancelled."

### Step 5: Run Cleanup

Change to olminstall directory:

```bash
cd <OLMINSTALL_PATH>
```

**Standard mode:**

```bash
bash cleanup.sh -t operator -g
```

Run this in the background (`run_in_background: true`) rather than a synchronous timeout — cleanup is documented to take 10-15 minutes (see Learned Lessons), which can exceed the Bash tool's 600000ms (10-minute) foreground cap. Wait for the background completion notification before moving to Step 6.

**Nuke mode:**

First, check if any dependency operators exist (workaround for `complete-cleanup.sh` bug):

```bash
oc get subscriptions -A --no-headers 2>/dev/null | grep -cE '(servicemesh|serverless|authorino|limitador|dns-operator|cert-manager|kueue|jobset|leaderworkerset|rhcl|connectivitylink)'
```

If count is 0, `complete-cleanup.sh` will crash with "operators[@]: unbound variable". Fall back to standard cleanup:

```bash
bash cleanup.sh -t operator -g
```

If count > 0, safe to run:

```bash
bash complete-cleanup.sh --yes
```

Run this in the background (`run_in_background: true`) — same reasoning as standard mode above.

### Step 6: Verify Cleanup

Run these checks. Each is a separate Bash call.

```bash
oc get csv -A --no-headers 2>/dev/null | grep -iE 'rhods|rhoai|opendatahub'
```

```bash
oc get namespaces --no-headers 2>/dev/null | grep -E '(redhat-ods|opendatahub|rhods)'
```

```bash
oc get dsc --no-headers 2>/dev/null
```

```bash
oc get dsci --no-headers 2>/dev/null
```

For nuke mode, also check:

```bash
oc get csv -A --no-headers 2>/dev/null | grep -iE '(servicemesh|serverless|authorino|cert-manager|kueue|jobset|leader-worker-set|rhcl)'
```

```bash
oc get namespaces --no-headers 2>/dev/null | grep Terminating
```

Also check for leftover RHOAI CRDs (these are the usual reason a namespace hangs in `Terminating` — the namespace can't finalize while stuck CRDs or their CR instances linger):

```bash
oc get crd --no-headers 2>/dev/null | grep -iE 'opendatahub|datasciencecluster|datascienceinitialization|trustyai|kserve|inferenceservice|servingruntime|featurestore'
```

### Step 7: Print Summary

```
RHOAI Cleanup Complete

  Cluster:    <cluster-url>
  Mode:       Standard / Nuke

Verification:
  RHOAI CSVs:        <none / N remaining>
  RHOAI namespaces:  <none / N remaining>
  DSC instances:     <none / N remaining>
  DSCI instances:    <none / N remaining>
  Stuck namespaces:  <none / N in Terminating>
```

For nuke mode, add:
```
  Dependency CSVs:   <none / N remaining>
```

If stuck `Terminating` namespaces or leftover RHOAI CRDs remain, try the olminstall helper **first** — it removes finalizers from stuck CRDs and their remaining CR instances, which is what usually blocks the namespace from finalizing. It must run with `-y` (without it the script prompts and hangs the Bash tool), and from the olminstall directory:

```bash
cd <OLMINSTALL_PATH>
```

```bash
bash remove-stuck-crds.sh -y
```

To scope it to a specific set of CRDs (e.g. only ServiceMesh leftovers), add `--pattern`:

```bash
bash remove-stuck-crds.sh -y --pattern 'maistra|servicemesh'
```

Re-check the namespaces afterward — clearing the stuck CRDs commonly lets a hung namespace finish terminating on its own.

Only if a namespace is *still* stuck after that, suggest the raw finalize edit as a **last resort** — it bypasses the owning controller's cleanup and can orphan cluster resources (ServiceMeshControlPlane, Istio CRs, etc.) behind the finalizer. Check `oc get namespace <ns> -o jsonpath='{.spec.finalizers}'` and the owning operator's logs first to understand why it's stuck. Only after `remove-stuck-crds.sh` and after confirming why the finalizer isn't clearing on its own, clear it directly:

```bash
oc get namespace <ns> -o json | jq '.spec.finalizers = []' | oc replace --raw "/api/v1/namespaces/<ns>/finalize" -f -
```

## Learned from Trial Runs

1. **`cleanup.sh` requires `-t operator` flag.** Without it, the script prints usage and exits with code 1. This is the most common mistake.

2. **`complete-cleanup.sh` has `operators[@]` unbound variable bug.** Line 241 crashes with "unbound variable" under `set -euo pipefail` when `detect_installed_operators()` finds no dependency operators (empty array). Workaround: check if dependency operators exist before running. If none, fall back to standard `cleanup.sh -t operator -g`.

3. **`complete-cleanup.sh` requires `--yes` for non-interactive use.** Without it, the script prompts for confirmation which hangs in the Bash tool.

4. **Cleanup can take 10-15 minutes.** The script performs graceful uninstall (if `-g`), then force-deletes subscriptions, CSVs, deployments, namespaces, CRDs, and webhooks. Set generous timeouts.

5. **The `-g` flag (graceful) on `cleanup.sh` is recommended.** It gives RHOAI a chance to run its own cleanup logic before force removal. Only works for `-t operator`.

6. **Stuck namespaces in Terminating state are common after nuke.** Usually caused by finalizers on ServiceMeshControlPlane, KnativeServing, or DataScienceCluster resources. The `complete-cleanup.sh` has logic to remove finalizers, but sometimes namespaces get stuck anyway.

7. **After cleanup, `redhat-ods-operator` namespace may already exist from a partial previous install.** The olminstall install scripts handle this with `--dry-run=client`.

8. **`remove-stuck-crds.sh` is the right tool for namespaces stuck in `Terminating`.** A namespace usually can't finalize because a RHOAI/dependency CRD is stuck in deletion (finalizer or a lingering CR instance). This script finds those CRDs, strips finalizers from the instances and the CRD, and force-deletes them — which frees the namespace. Prefer it over the raw `oc replace --raw .../finalize` hack, which only clears the namespace finalizer and can orphan the underlying resources. It requires `-y` for non-interactive use (same hang problem as `complete-cleanup.sh`), and supports `--pattern` to limit which CRDs it touches.

## Do Not

- Do not run `cleanup.sh` without `-t operator` — it will print usage and exit
- Do not run `complete-cleanup.sh` without `--yes` — it will hang waiting for input
- Do not run `complete-cleanup.sh` when no dependency operators are installed — it will crash
- Do not combine shell commands with `&&`, `;`, or `||`
- Do not proceed if `oc whoami` fails
- Do not skip user confirmation — cleanup is destructive and irreversible
- Do not assume cleanup will be fast — always set generous timeouts (10+ minutes)
- Do not delete the olminstall repo after cleanup — user may need it for reinstallation
