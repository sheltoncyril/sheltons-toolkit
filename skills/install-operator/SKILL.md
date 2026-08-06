---
name: install-operator
description: >
  Install any individual RHOAI dependency operator on an OpenShift cluster
  using install-operator.sh. Supports 16 operators with configurable channel,
  source, and version. Locates or clones olminstall automatically.
  Trigger phrases include: "install operator", "install single operator",
  "add operator", "install kueue", "install serverless", "install cert-manager".
allowed-tools: Bash Read AskUserQuestion
---

# Install Operator

Install any individual RHOAI dependency operator on an OpenShift cluster using `install-operator.sh` from the olminstall repo.

## Input

`$ARGUMENTS` format: `<operator-name> [--channel <ch>] [--source <src>] [--version <ver>]`

- `<operator-name>` -- required. Must be one of the 16 supported operators listed below.
- `--channel <ch>` -- optional. OLM subscription channel. If omitted, uses the default from the operator's install YAML.
- `--source <src>` -- optional. CatalogSource name. If omitted, uses the default from the operator's install YAML.
- `--version <ver>` -- optional. Operator version (sets `startingCSV`). If omitted, installs the latest available in the channel.

Examples:
```
authorino-operator
rhods-operator --channel fast --source rhoai-catalog-dev
kueue-operator --channel stable-v1.3
serverless-operator --version 1.35.0
```

## Supported Operators

| Operator Name                     | Default Channel  | Default Source       |
|-----------------------------------|------------------|----------------------|
| authorino-operator                | stable           | redhat-operators     |
| cert-manager-operator             | stable-v1        | redhat-operators     |
| cluster-observability-operator    | stable           | redhat-operators     |
| custom-metrics-autoscaler         | stable           | redhat-operators     |
| jobset-operator                   | stable-v1.0      | redhat-operators     |
| kueue-operator                    | stable-v1.3      | redhat-operators     |
| leader-worker-set                 | stable-v1.0      | redhat-operators     |
| mariadb-operator                  | alpha            | community-operators  |
| openshift-pipelines-operator-rh   | latest           | redhat-operators     |
| opentelemetry-operator            | stable           | redhat-operators     |
| rhcl-operator                     | stable           | redhat-operators     |
| rhods-operator                    | fast             | rhoai-catalog-dev    |
| serverless-operator               | stable           | redhat-operators     |
| servicemeshoperator               | stable           | redhat-operators     |
| servicemeshoperator3              | stable           | redhat-operators     |
| tempo-operator                    | stable           | redhat-operators     |

## Steps

### Step 1: Parse and Validate Operator Name

Parse `$ARGUMENTS` to extract the operator name (first positional token) and optional `--channel`, `--source`, `--version` flags.

If no operator name provided, print the supported operators table above and stop:
```
Usage: /install-operator <operator-name> [--channel <ch>] [--source <src>] [--version <ver>]
```

Validate the operator name against the 16 supported operators. If invalid, print the table and stop with:
```
Unknown operator: <name>

Did you mean one of: <closest matches from the table>
```

Store `OPERATOR_NAME`, `CHANNEL` (may be empty), `SOURCE` (may be empty), `VERSION` (may be empty).

### Step 2: Preflight Checks

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
  Operator: <OPERATOR_NAME>
  Channel:  <CHANNEL or "default">
  Source:   <SOURCE or "default">
  Version:  <VERSION or "latest">
```

### Step 3: Locate olminstall Repo

Search these paths in order. Each is a separate Bash call:

```bash
ls -d ../olminstall/install-operator.sh 2>/dev/null
```

```bash
ls -d ~/Desktop/Work/olminstall/install-operator.sh 2>/dev/null
```

```bash
ls -d ~/olminstall/install-operator.sh 2>/dev/null
```

```bash
ls -d /tmp/olminstall/install-operator.sh 2>/dev/null
```

If none found, attempt clone:

```bash
git clone https://gitlab.cee.redhat.com/data-hub/olminstall.git /tmp/olminstall
```

If clone fails, ask user with `AskUserQuestion`:
```
Could not locate or clone the olminstall repo.
Please provide the full path to your local olminstall directory.
(Clone from: https://gitlab.cee.redhat.com/data-hub/olminstall -- VPN required)
```

Validate the required files exist:

```bash
ls <path>/install-operator.sh
```

```bash
ls <path>/resources/install-<OPERATOR_NAME>.yaml
```

If either is missing, report and stop. Store `OLMINSTALL_PATH`.

### Step 4: Check if Already Installed

Check whether a CSV for this operator already exists on the cluster:

```bash
oc get csv -A --no-headers 2>/dev/null | grep -i <OPERATOR_NAME>
```

If output is non-empty, the operator is already installed. Report the CSV name and status, then ask with `AskUserQuestion`:
```
<OPERATOR_NAME> is already installed: <csv-name> (<phase>)

Reinstall anyway? (yes / no)
```

If user says no, stop with: "Operator already installed. No changes made."

If user says yes, continue to Step 5.

### Step 5: Run install-operator.sh

Change to the olminstall directory (required -- the script uses `$BASE_DIR` relative to itself but marketplace and resource files are relative):

```bash
cd <OLMINSTALL_PATH>
```

Build the positional arguments for the script. The script takes: `OPERATOR_NAME [CHANNEL] [SOURCE] [VERSION]`. All positional, not flags.

- If only `OPERATOR_NAME` is set (no overrides), run with just the name.
- If `CHANNEL` is set, it becomes the second positional arg. If `SOURCE` or `VERSION` are also set, they follow in order. If `CHANNEL` is empty but `SOURCE` or `VERSION` are set, you must still pass the default channel as the second arg to maintain positional ordering.

To discover the default channel and source when needed for positional padding:

```bash
grep 'channel:' <OLMINSTALL_PATH>/resources/install-<OPERATOR_NAME>.yaml | awk -F': ' '{print $2}' | xargs
```

```bash
grep 'source:' <OLMINSTALL_PATH>/resources/install-<OPERATOR_NAME>.yaml | head -1 | awk -F': ' '{print $2}' | xargs
```

Run the install:

```bash
bash install-operator.sh <OPERATOR_NAME> [<CHANNEL>] [<SOURCE>] [<VERSION>]
```

Set timeout to 600000ms (10 minutes). The script handles marketplace cleanup, applies the subscription YAML, waits for the InstallPlan, approves it, waits for the CSV, and runs any post-install hooks.

If the script exits non-zero, capture the output and report the error. Common failures:
- InstallPlan not found within 100 seconds -- CatalogSource may be missing or operator not available in the channel.
- CSV not found within 600 seconds -- InstallPlan approval may have failed or the operator image pull is stuck.

### Step 6: Verify CSV

After the script completes successfully, verify the CSV is in Succeeded phase. The namespace to check depends on the operator:

| Operator                | CSV Namespace                              |
|-------------------------|--------------------------------------------|
| jobset-operator         | openshift-jobset-operator                  |
| leader-worker-set       | openshift-lws-operator                     |
| cert-manager-operator   | cert-manager-operator                      |
| rhcl-operator           | kuadrant-system                            |
| mariadb-operator        | openshift-operators                        |
| rhods-operator          | redhat-ods-operator                        |
| All others              | Check with `-A` flag                       |

```bash
oc get csv -n <NAMESPACE> --no-headers 2>/dev/null | grep -i <OPERATOR_NAME>
```

If the CSV shows `Succeeded`, the install is confirmed.

If the CSV shows `Installing` or `Pending`, wait:

```bash
oc get csv -n <NAMESPACE> -o jsonpath='{.items[*].status.phase}' 2>/dev/null
```

Report the actual status. Do not loop more than 3 times; if still not Succeeded, report and let the user investigate.

### Step 7: Print Summary

```
Operator Install Complete

  Cluster:   <cluster-url>
  Operator:  <OPERATOR_NAME>
  CSV:       <csv-name>
  Status:    Succeeded
  Channel:   <channel-used>
  Source:    <source-used>
  Version:   <version or "latest">
  Namespace: <namespace>
```

If the install failed or CSV is not Succeeded, adjust the summary:

```
Operator Install Finished (with issues)

  Cluster:   <cluster-url>
  Operator:  <OPERATOR_NAME>
  Status:    <actual-status>

Troubleshooting:
  oc get csv -A | grep <OPERATOR_NAME>
  oc get installplan -A | grep <OPERATOR_NAME>
  oc get pods -n <NAMESPACE>
```

## Learned from Trial Runs

1. **The script takes positional arguments, not flags.** The order is `OPERATOR_NAME CHANNEL SOURCE VERSION`. If you need to set VERSION but want the default channel, you must still pass the default channel and source as the second and third arguments. Read them from the install YAML.

2. **`install-operator.sh` must run from the olminstall directory.** Although `BASE_DIR` is derived from the script location, marketplace resource files and the `target/` directory are created relative to the repo root. Always `cd` first.

3. **Several operators install to dedicated namespaces, not `openshift-operators`.** The CSV wait logic in the script uses hardcoded namespace overrides for `jobset-operator` (openshift-jobset-operator), `leader-worker-set` (openshift-lws-operator), `cert-manager-operator` (cert-manager-operator), `rhcl-operator` (kuadrant-system), and `mariadb-operator` (openshift-operators). Checking the wrong namespace will show no CSV.

4. **rhcl-operator also waits for authorino-operator CSV.** The script waits for both `rhcl-operator` and `authorino-operator` CSVs in the `kuadrant-system` namespace. This is because RHCL depends on Authorino and installs it as a dependency. The total wait can be 5+ minutes.

5. **InstallPlan approval can take 60-100 seconds.** The `oc_wait_for_ip` function retries 10 times with 10-second sleeps. If the CatalogSource is slow to resolve the bundle, approval will be delayed. Do not set a short timeout.

6. **cert-manager uses Automatic InstallPlan approval.** Unlike the other 15 operators which use `Manual` approval, cert-manager-operator uses `installPlanApproval: Automatic`. The script still runs the approval flow but it is a no-op.

7. **mariadb-operator has a pinned version.** Its install YAML sets `startingCSV: mariadb-operator.v25.8.2` because it depends on exact mirrored images. Overriding the version may break the install on disconnected clusters.

8. **Post-install scripts exist for some operators.** The operators `authorino-operator`, `jobset-operator`, `leader-worker-set`, `rhcl-operator`, and `rhods-operator` have `post-install-<name>.sh` scripts that run automatically after the CSV is ready. These can add extra wait time.

9. **Marketplace cleanup runs before every install.** The script deletes stale marketplace jobs and configmaps for the operator. This prevents OLM resolution conflicts from previous install attempts. The marketplace file (`marketplace-<name>.txt`) lists bundle image names to match against.

## Do Not

- Do not reorder the positional arguments -- the script expects `NAME CHANNEL SOURCE VERSION` in exactly that order
- Do not combine shell commands with `&&`, `;`, or `||`
- Do not proceed if `oc whoami` fails
- Do not assume the olminstall repo is already cloned -- always search then fall back to clone
- Do not skip the `cd` into the olminstall directory before running the script
- Do not set a timeout shorter than 600000ms (10 minutes) -- operator installs with Manual approval can take several minutes
- Do not override mariadb-operator's version without warning the user about mirrored image dependencies
- Do not check the wrong namespace for the CSV -- use the namespace mapping table in Step 6
- Do not run the script with flag-style arguments (`--channel`) -- it only accepts positional arguments
