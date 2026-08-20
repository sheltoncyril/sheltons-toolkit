---
name: install-rhoai-nightly
description: >
  Install RHOAI nightly build on an OpenShift cluster from an FBC fragment image.
  Handles cluster type detection (ROSA HCP vs regular OCP), pull-secret
  workarounds, dependency operator installation (cert-manager, leader-worker-set,
  connectivity-link), DSC creation, and full readiness verification. Locates or
  clones the olminstall repo automatically.
  Trigger phrases include: "install rhoai", "install nightly", "install rhoai nightly",
  "setup rhoai", "deploy rhoai", "install fbc fragment", "rhoai install".
allowed-tools: Bash Read Write AskUserQuestion Skill
---

# Install RHOAI Nightly

Install a RHOAI nightly build from an FBC fragment image on a connected OpenShift cluster.

## Input

`$ARGUMENTS` format: `<fbc-fragment-image> [--channel <channel>]`

Examples:
```
quay.io/rhoai/rhoai-fbc-fragment:rhoai-3.5@sha256:3d60... --channel stable-3.5
quay.io/rhoai/rhoai-fbc-fragment:rhoai-3.5@sha256:3d60...
```

- `<fbc-fragment-image>` — required. The FBC fragment image URI (typically from Slack or email).
- `--channel <channel>` — optional. OLM subscription channel. If omitted, determined by extracting the FBC fragment's own catalog data (falls back to image-tag inference, then asks the user).

## Steps

### Step 0: Parse Input

Parse `$ARGUMENTS` to extract the image URI and optional `--channel` value.

If no image URI provided, print usage and stop:
```
Usage: /install-rhoai-nightly <fbc-fragment-image> [--channel <channel>]

Example:
  /install-rhoai-nightly quay.io/rhoai/rhoai-fbc-fragment:rhoai-3.5@sha256:abc123 --channel stable-3.5
```

**Channel detection** (when `--channel` not provided):

Don't guess the channel from the image tag alone — inspect the fragment's real catalog data. Tag-based guessing (`rhoai-3.5` → `stable-3.5`) is a heuristic that can silently resolve to the wrong CSV: a fragment can carry a `beta` channel still pinned to an early-access build (e.g. `3.5.0-ea.2`) alongside a `stable-3.5` channel that's already GA (`3.5.0`) — same fragment, same tag, different truth depending on which channel you pick.

**Primary method — extract and read the actual catalog:**

```bash
mkdir -p /tmp/fbc-inspect
oc image extract "<IMAGE>" --path /configs:/tmp/fbc-inspect --confirm
```

This works even though FBC images are typically scratch-based (no shell) — `oc image extract` reads the image layers directly, no `podman run` or `opm` needed. Requires only that you're logged in to a cluster (`oc login`) with registry pull access to the image.

Find the catalog file (usually `.../<pkg-name>/catalog.yaml`, occasionally JSON lines):

```bash
find /tmp/fbc-inspect -iname "catalog.yaml" -o -iname "catalog.json"
```

Parse every channel and the CSV its latest entry resolves to:

```bash
python3 -c "
import yaml
docs = list(yaml.safe_load_all(open('<catalog-file>')))
for d in docs:
    if d and d.get('schema') == 'olm.channel':
        entries = d.get('entries', [])
        latest = entries[-1]['name'] if entries else None
        print(d.get('name'), '->', latest)
"
```

(If the file is JSON lines instead of a single YAML doc, parse with `json.loads` per line instead of `yaml.safe_load_all`.)

Match the image tag's version against the channel names (tag `rhoai-3.5` → look for channels containing `3.5`; prefer an exact `stable-X.Y` match over `beta`/`fast`/`eus` variants unless the user asked for one of those tracks). Report the match plainly before proceeding, e.g.:

```
Found channel 'stable-3.5' -> rhods-operator.3.5.0
```

Clean up: `rm -rf /tmp/fbc-inspect`

**Fallback** (only if `oc image extract` fails — no cluster access yet, registry auth issue, or no matching channel found in the catalog): fall back to tag-based inference. Extract the tag (portion between `:` and `@`); if it matches `rhoai-X.Y`, derive channel `stable-X.Y`. Flag clearly that this is an unverified guess, not a confirmed match.

If both methods fail, ask the user with `AskUserQuestion`:
```
Could not determine channel from the FBC fragment or image tag. What channel should the subscription use?
Options: stable-3.5, stable-3.4, fast
```

Regardless of which path was taken (primary match, fallback, or ask-user), clean up before continuing: `rm -rf /tmp/fbc-inspect` — the extraction can partially populate this directory even on failure, and leaving it behind can confuse a later re-run of this step.

Store `IMAGE` and `CHANNEL` for subsequent steps.

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

Report:
```
Preflight:
  Cluster: <server>
  User:    <whoami>
  OCP:     <server-version>
  Image:   <IMAGE>
  Channel: <CHANNEL>
```

### Step 2: Detect Cluster Type

```bash
oc get infrastructure cluster -o jsonpath='{.status.platformStatus.type}'
```

If result is `AWS`, this is a ROSA cluster. Set `IS_ROSA=true`. Otherwise set `IS_ROSA=false`.

Report: "Cluster type: AWS (ROSA) — pull-secret workaround will be checked" or "Cluster type: <type> — no pull-secret workaround needed".

### Step 3: Locate olminstall Repo

Search these paths in order. Each is a separate Bash call:

```bash
ls -d ../olminstall/setup.sh 2>/dev/null
```

```bash
ls -d ~/Desktop/Work/olminstall/setup.sh 2>/dev/null
```

```bash
ls -d ~/olminstall/setup.sh 2>/dev/null
```

```bash
ls -d /tmp/olminstall/setup.sh 2>/dev/null
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

After obtaining a path, validate it has the required scripts:

```bash
ls <path>/setup.sh
```

```bash
ls <path>/cleanup.sh
```

```bash
ls <path>/install-operator.sh
```

```bash
ls <path>/create-dsc.sh
```

If any is missing, report which file is missing and stop.

Store `OLMINSTALL_PATH`.

**Keep the repo current.** If `OLMINSTALL_PATH` is a git clone, `setup.sh` / `install-operator.sh` / `create-dsc.sh` get fixes over time — a stale clone can reintroduce already-fixed bugs. Check whether it's a git working copy:

```bash
test -d <OLMINSTALL_PATH>/.git && echo git || echo not-git
```

If it is a git clone, and the `OLMINSTALL_AUTO_UPDATE` preference is not already set, ask with `AskUserQuestion`:
```
The olminstall repo at <OLMINSTALL_PATH> may be out of date. Update it before installing?
```
Options:
- `Update` — pull once now
- `Always update` — pull now and on every future run without asking
- `No` — use the repo as-is

Honor the answer:
- `Update` or `Always update`: `git -C <OLMINSTALL_PATH> pull`
- `Always update`: also record the preference so future runs skip the prompt — set `OLMINSTALL_AUTO_UPDATE=1` (suggest the user add it to their shell profile) and treat it as "always pull" whenever it is set on subsequent runs.
- `No`: proceed without pulling.

If `OLMINSTALL_AUTO_UPDATE` is already set (`echo "${OLMINSTALL_AUTO_UPDATE:-unset}"` is not `unset`), skip the question and just run `git -C <OLMINSTALL_PATH> pull`. Never pull a path that isn't a git clone (e.g. a fresh `git clone` above is already current), and never pull a one-off path the user just typed without asking.

### Step 4: ROSA Pull-Secret Setup (conditional)

Skip this step entirely if `IS_ROSA` is `false`.

**4a.** Check if pull-secret-brew already exists:

```bash
oc get secret pull-secret-brew -n openshift-config -o name 2>/dev/null
```

If it exists, check if Kyverno is ready:

```bash
oc get deployment kyverno-admission-controller -n kyverno -o jsonpath='{.status.readyReplicas}' 2>/dev/null
```

If pull-secret-brew exists AND Kyverno has ready replicas, report "Pull-secret workaround already in place." and skip to Step 5.

**4b.** Check prerequisites:

```bash
command -v jq
```

```bash
command -v yq
```

If either is missing, stop with: "`jq` and `yq` are required for the pull-secret workaround. Install them first."

```bash
test -f ~/.docker/config.json
```

If missing, stop with instructions:
```
~/.docker/config.json not found. You need registry credentials for ROSA clusters.

1. For registry.redhat.io:
   - Create token: kinit <user>@IPA.REDHAT.COM && curl --negotiate -u : -X POST -H 'Content-Type: application/json' --data '{"description":"brew-pull-secret"}' https://employee-token-manager.registry.redhat.com/v1/tokens
   - Login: podman login --compat-auth-file ~/.docker/config.json registry.redhat.io

2. For quay.io:
   - Get encrypted password from: https://quay.io → Profile → Settings → CLI Configuration
   - Login: podman login --compat-auth-file ~/.docker/config.json quay.io
```

Check for required registry entries:

```bash
jq -e '.auths."quay.io"' ~/.docker/config.json
```

```bash
jq -e '.auths."registry.redhat.io"' ~/.docker/config.json
```

If either is missing, report which registry credentials are missing with login instructions and stop.

**4c.** Run the pull-secret workaround:

```bash
bash <skill-dir>/resources/pull_secret_workaround.sh
```

**4d.** Verify Kyverno readiness (script already waits, but double-check):

```bash
oc wait --for=condition=available --timeout=300s deployment/kyverno-admission-controller -n kyverno
```

### Step 5: Check for Existing RHOAI

```bash
oc get csv -n redhat-ods-operator --no-headers 2>/dev/null | grep -i rhods
```

If output is non-empty, RHOAI is already installed. Ask with `AskUserQuestion`:
```
RHOAI is already installed: <csv-name>
Clean up before installing? (yes / no / abort)
```

If yes, invoke the cleanup skill:
```
Use the Skill tool with skill: "sheltons-toolkit:cleanup-rhoai" and no args (standard cleanup).
```

If no, stop with: "Remove existing RHOAI first or use a clean cluster."

### Step 6: Run Install

Change to olminstall directory (required — `setup.sh` uses relative paths):

```bash
cd <OLMINSTALL_PATH>
```

Run the install in the background (`run_in_background: true`) — OLM catalog setup and subscription resolution routinely exceeds the Bash tool's 600000ms (10-minute) foreground cap:

```bash
bash setup.sh -t operator -u <CHANNEL> -i <IMAGE>
```

Wait for the background completion notification before moving to Step 7.

### Step 7: Wait for CSV

```bash
oc get csv -n redhat-ods-operator --no-headers 2>/dev/null | grep -i rhods
```

If no CSV found yet, wait and retry, up to 20 times (10 minutes total):

```bash
sleep 30
```

If no CSV appears after 20 attempts, first check whether the subscription actually resolved an InstallPlan:

```bash
oc get subscription rhoai-operator-dev -n redhat-ods-operator -o jsonpath='{.status.state} installplan={.status.installplan.name}{"\n"}'
```

If the subscription state is not `AtLatestKnown`/`UpgradePending` and no `installplan` is set, this is almost always a channel mismatch — the catalog image doesn't publish the channel in the subscription (common with EA/nightly builds that only exist in `beta`). Inspect the available channels and patch the subscription to a real one:

```bash
oc get subscription rhoai-operator-dev -n redhat-ods-operator -o jsonpath='{.spec.channel}{"\n"}'
```

```bash
oc patch subscription rhoai-operator-dev -n redhat-ods-operator --type merge -p '{"spec":{"channel":"<correct-channel>"}}'
```

Use the channel confirmed by the `oc image extract` inspection in Step 0 (that is authoritative for what this fragment publishes). After patching, re-enter the CSV wait loop above. If the subscription *did* resolve an InstallPlan but no CSV appeared, stop and report: "No rhods-operator CSV appeared after 10 minutes. Check the subscription and CatalogSource: `oc get subscription,catalogsource -n redhat-ods-operator`." Once a CSV name is found:

```bash
oc wait csv <CSV_NAME> -n redhat-ods-operator --for=jsonpath='{.status.phase}'=Succeeded --timeout=300s
```

If timeout, run diagnostics:

```bash
oc get csv -n redhat-ods-operator
```

Report status but continue — dependency operators may be needed first.

### Step 8: Install Dependency Operators

Check and install each. All `install-operator.sh` calls must run from the olminstall directory and in the background (`run_in_background: true`) — rhcl-operator additionally waits on authorino-operator and can take 5+ minutes, exceeding the Bash tool's 600000ms foreground cap. Wait for each background completion notification before checking the next operator.

```bash
cd <OLMINSTALL_PATH>
```

**8a. cert-manager:**

```bash
oc get csv -A --no-headers 2>/dev/null | grep cert-manager
```

If no output:

```bash
bash install-operator.sh cert-manager-operator
```

**8b. leader-worker-set:**

```bash
oc get csv -A --no-headers 2>/dev/null | grep leader-worker-set
```

If no output:

```bash
bash install-operator.sh leader-worker-set
```

**8c. connectivity-link (rhcl-operator):**

```bash
oc get csv -A --no-headers 2>/dev/null | grep rhcl
```

If no output:

```bash
bash install-operator.sh rhcl-operator
```

Report which operators were installed vs already present.

### Step 9: Create DSC

```bash
cd <OLMINSTALL_PATH>
```

Run in the background (`run_in_background: true`) — `create-dsc.sh`'s internal waits can take up to 1800s total, exceeding the Bash tool's 600000ms foreground cap:

```bash
bash create-dsc.sh
```

Wait for the background completion notification before moving to Step 10.

### Step 10: Wait for DSC Ready

```bash
oc wait dsc default-dsc --for=jsonpath='{.status.phase}'=Ready --timeout=600s
```

If timeout, run diagnostics:

```bash
oc get dsc default-dsc -o jsonpath='{.status.phase}'
```

```bash
oc get pods -n redhat-ods-applications --no-headers | grep -v Running | grep -v Completed
```

Report status. If not Ready, suggest checking dependency operators.

### Step 11: Print Summary

Gather info:

```bash
oc get csv -n redhat-ods-operator --no-headers | grep rhods
```

```bash
oc get dsc default-dsc -o jsonpath='{.status.phase}'
```

```bash
oc whoami --show-console
```

Print:
```
RHOAI Installation Complete

  Cluster:     <cluster-api-url>
  Console:     <console-url>
  Channel:     <CHANNEL>
  CSV:         <csv-name> (Succeeded)
  DSC Status:  Ready
  FBC Image:   <IMAGE>

Dependency Operators:
  cert-manager:       installed / already present
  leader-worker-set:  installed / already present
  rhcl-operator:      installed / already present
```

## Learned from Trial Runs

1. **`setup.sh` MUST run from the olminstall directory.** It references relative paths like `operator-catalogsource.yaml` and `operator/subscription.yaml.template` without `$BASE_DIR` prefix. Always `cd` into the olminstall directory before running it.

2. **Channel must match the FBC fragment version.** Using `fast` channel with a `rhoai-3.5` FBC fragment installs `rhods-operator.2.25.9` instead of `rhods-operator.3.5.0`. The channel in the subscription must correspond to the version track in the FBC catalog.

3. **Channel inference from image tag is a fallback, not the primary method.** Extract the tag between `:` and `@`; if it matches `rhoai-X.Y`, derive channel `stable-X.Y` — but only after `oc image extract` on the fragment itself fails or is unavailable. Confirmed by trial: `oc image extract "<image>" --path /configs:/tmp/fbc-inspect --confirm` pulls the real declarative catalog (usually at `configs/<pkg>/catalog.yaml`) even for scratch-based images with no shell — no `opm` or `podman run` needed. Reading `olm.channel` entries from it gives the actual CSV each channel resolves to, which is the only way to know for certain (see item 9).

4. **`install-operator.sh` handles Manual InstallPlan approval.** The `leader-worker-set` and `rhcl-operator` subscriptions use `installPlanApproval: Manual`. Helper functions in `utils/oc_approve.sh` handle auto-approving. This can take 2-5 minutes.

5. **DSC may take 10+ minutes to reach Ready.** Often a dependency operator (cert-manager, leader-worker-set, rhcl-operator) is missing. Install deps before creating the DSC.

6. **Pull-secret workaround is only needed on AWS (ROSA) clusters.** The script handles single-node vs multi-node internally. On single-node it uses `oc set data` directly, on multi-node it installs Kyverno for secret syncing.

7. **`jq` and `yq` are required for pull-secret setup.** The script checks for them but fails cryptically. Check early and provide clear instructions.

8. **`setup.sh` modifies `operator-catalogsource.yaml` in-place.** The `perl -i -pe` command replaces the image line. Safe to re-run — overwrites previous image.

9. **The same version tag can map to different real versions depending on channel.** Observed on a `rhoai-3.5` fragment: `beta` resolved to `rhods-operator.3.5.0-ea.2` (early access) while `stable-3.5` resolved to `rhods-operator.3.5.0` (GA) — both channels existed in the same fragment, same image tag. Guessing `stable-X.Y` from the tag happened to be right that time, but nothing guarantees it: some fragments only carry a `beta`/`fast`/`eus-X.Y` channel for a given version, or `stable-X.Y` might not be cut yet. Always extract and check before installing.

10. **A subscription that never resolves an InstallPlan is usually a channel mismatch, and is recoverable in-place.** If the CSV never appears, check `oc get subscription rhoai-operator-dev -n redhat-ods-operator -o jsonpath='{.status.state} {.status.installplan.name}'`. No installplan + a non-resolving state means the catalog image doesn't publish the subscribed channel — EA/nightly fragments frequently carry only a `beta` channel, not `stable-X.Y`. No need to tear down and re-run `setup.sh`: `oc patch subscription rhoai-operator-dev -n redhat-ods-operator --type merge -p '{"spec":{"channel":"beta"}}'` (or the real channel from the Step 0 `oc image extract`) makes OLM re-resolve and create the InstallPlan. This is why Step 0's fragment inspection is authoritative — it tells you which channel actually exists before the mismatch happens.

## Do Not

- Do not run `setup.sh` from a directory other than the olminstall repo root
- Do not default channel to `fast` — always confirm via `oc image extract` first, fall back to tag inference, then ask user
- Do not trust tag-based channel inference (`rhoai-X.Y` → `stable-X.Y`) as ground truth — it's a last-resort fallback; the fragment's actual `olm.channel` entries are authoritative
- Do not skip dependency operator installation — DSC will be stuck without them
- Do not run `create-dsc.sh` before dependency operators are installed
- Do not modify `~/.docker/config.json` — only read it for validation
- Do not assume the olminstall repo is already cloned
- Do not combine shell commands with `&&`, `;`, or `||`
- Do not proceed past preflight if `oc whoami` fails
- Do not assume `jq`/`yq` are installed — check before pull-secret step on ROSA clusters
