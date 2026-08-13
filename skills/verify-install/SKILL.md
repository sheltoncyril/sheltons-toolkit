---
name: verify-install
description: >
  Verify RHOAI installation status on an OpenShift cluster. Checks operator CSV,
  DSC status, dependency operators, pod health, routes, and common issues.
  Trigger phrases include: "verify install", "check rhoai", "rhoai status",
  "is rhoai installed", "verify rhoai", "installation status", "health check".
allowed-tools: Bash Read AskUserQuestion
---

# Verify RHOAI Installation

Check the health and status of an RHOAI installation on an OpenShift cluster.

## Input

`$ARGUMENTS` format: `[--full]`

- No args: quick check (CSV, DSC, core pods)
- `--full`: comprehensive check (all dependency CSVs, routes, gateways, webhooks, CRDs, recent events, issues summary)

## Steps

### Step 1: Parse Input

Check if `$ARGUMENTS` contains `--full`. Set `FULL_MODE=true` or `FULL_MODE=false`.

### Step 2: Preflight

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

Store cluster URL, username, and OCP version.

### Step 3: CSV Check

```bash
oc get csv -n redhat-ods-operator --no-headers 2>/dev/null | grep -i rhods
```

If empty, broaden the search:

```bash
oc get csv -A --no-headers 2>/dev/null | grep -iE 'rhods|rhoai|opendatahub'
```

If both are empty, report:
```
RHOAI is not installed on this cluster.

  Cluster: <cluster-url>
  User:    <username>
```

Stop.

If found, extract the CSV name and phase:

```bash
oc get csv <CSV_NAME> -n redhat-ods-operator -o jsonpath='{.status.phase}'
```

Store `CSV_NAME` and `CSV_PHASE`.

### Step 4: DSC and DSCI Status

```bash
oc get dsc --no-headers 2>/dev/null
```

```bash
oc get dsci --no-headers 2>/dev/null
```

If a DSC exists, take its name from the `oc get dsc` output above as `<DSC_NAME>` (it is usually `default-dsc`, but do not assume this — use whatever name actually appears). Get its phase:

```bash
oc get dsc <DSC_NAME> -o jsonpath='{.status.phase}'
```

Get the DSC conditions for detail:

```bash
oc get dsc <DSC_NAME> -o jsonpath='{range .status.conditions[*]}{.type}={.status} ({.reason}){"\n"}{end}'
```

Store `DSC_NAME`, `DSC_PHASE`, and any condition details. Note which components have issues (e.g., `ReconcileFailed`, `PreConditionFailed`).

If no DSC exists, record: "No DSC found — RHOAI operator is installed but not configured."

### Step 5: Core Pod Health

Check pods in three namespaces. Each is a separate Bash call.

**redhat-ods-applications:**

```bash
oc get pods -n redhat-ods-applications --no-headers 2>/dev/null
```

**redhat-ods-monitoring:**

```bash
oc get pods -n redhat-ods-monitoring --no-headers 2>/dev/null
```

**redhat-ods-operator:**

```bash
oc get pods -n redhat-ods-operator --no-headers 2>/dev/null
```

For each namespace, count:
- **Running** pods (status column shows `Running`)
- **Completed** pods (status column shows `Completed`) — these are normal (Jobs)
- **Problematic** pods (anything else: `CrashLoopBackOff`, `Error`, `ImagePullBackOff`, `Pending`, `Init:*`, `ContainerCreating` stuck for a long time, etc.)

Store the counts and any problematic pod names with their status.

### Step 6: Quick Summary

Get the console URL first so it's available for the print template below:

```bash
oc whoami --show-console
```

Print the quick summary. This is always shown regardless of mode.

```
RHOAI Installation Status

  Cluster:    <cluster-url>
  User:       <username>
  OCP:        <ocp-version>

  Operator:   <CSV_NAME> (<CSV_PHASE>)
  DSC:        <DSC_NAME> (<DSC_PHASE>)
  Console:    <console-url>

Core Pods (redhat-ods-applications):
  Running:     <N>/<total>
  Completed:   <N>
  Failed:      <N>

Core Pods (redhat-ods-monitoring):
  Running:     <N>/<total>
  Completed:   <N>
  Failed:      <N>

Core Pods (redhat-ods-operator):
  Running:     <N>/<total>
  Completed:   <N>
  Failed:      <N>
```

If there are problematic pods, list them:
```
Problematic Pods:
  redhat-ods-applications:
    <pod-name>  <status>  <restarts>
  redhat-ods-monitoring:
    <pod-name>  <status>  <restarts>
```

If `FULL_MODE` is `false`, stop here.

### Step 7: Dependency CSVs (--full only)

Check each dependency operator. Each is a separate Bash call.

```bash
oc get csv -A --no-headers 2>/dev/null | grep cert-manager
```

```bash
oc get csv -A --no-headers 2>/dev/null | grep leader-worker-set
```

```bash
oc get csv -A --no-headers 2>/dev/null | grep rhcl
```

```bash
oc get csv -A --no-headers 2>/dev/null | grep servicemesh
```

```bash
oc get csv -A --no-headers 2>/dev/null | grep serverless
```

```bash
oc get csv -A --no-headers 2>/dev/null | grep authorino
```

```bash
oc get csv -A --no-headers 2>/dev/null | grep kueue
```

```bash
oc get csv -A --no-headers 2>/dev/null | grep jobset
```

For each, extract CSV name and phase. Some are optional (ServiceMesh, Serverless, Authorino, Kueue, JobSet) and may not be present.

Print:
```
Dependency Operators:
  cert-manager:          <csv-name> (<phase>) / Not installed
  leader-worker-set:     <csv-name> (<phase>) / Not installed
  connectivity-link:     <csv-name> (<phase>) / Not installed
  servicemesh:           <csv-name> (<phase>) / Not installed (optional)
  serverless:            <csv-name> (<phase>) / Not installed (optional)
  authorino:             <csv-name> (<phase>) / Not installed (optional)
  kueue:                 <csv-name> (<phase>) / Not installed (optional)
  jobset:                <csv-name> (<phase>) / Not installed (optional)
```

### Step 8: Dashboard and Routes (--full only)

```bash
oc get routes -n redhat-ods-applications --no-headers 2>/dev/null
```

```bash
oc get routes -n istio-system --no-headers 2>/dev/null
```

Print the route hosts, highlighting the RHOAI dashboard route if present.

```
Routes:
  Dashboard:  https://<dashboard-route-host>
  Other:      <route-name> -> <host>
```

### Step 9: CatalogSource Health (--full only)

```bash
oc get catalogsource -n openshift-marketplace --no-headers 2>/dev/null
```

```bash
oc get catalogsource -n redhat-ods-operator --no-headers 2>/dev/null
```

For any RHOAI-related CatalogSource, check its state:

```bash
oc get catalogsource <NAME> -n <NS> -o jsonpath='{.status.connectionState.lastObservedState}'
```

Print:
```
CatalogSources:
  <name> (<namespace>):  <state>
```

Flag any CatalogSource that is not in `READY` state.

### Step 10: Gateway Config (--full only)

```bash
oc get gateway -A --no-headers 2>/dev/null
```

```bash
oc get service -n istio-system --no-headers 2>/dev/null
```

Print any gateways and their status. If no gateways exist, print "No gateways found (KServe may use ClusterLocal)."

### Step 11: Webhooks (--full only)

```bash
oc get validatingwebhookconfigurations --no-headers 2>/dev/null | grep -iE 'odh|rhoai|rhods|opendatahub|trustyai|kserve'
```

```bash
oc get mutatingwebhookconfigurations --no-headers 2>/dev/null | grep -iE 'odh|rhoai|rhods|opendatahub|trustyai|kserve'
```

Print:
```
Webhooks:
  Validating:
    <webhook-name>
  Mutating:
    <webhook-name>
```

### Step 12: CRDs (--full only)

```bash
oc get crd --no-headers 2>/dev/null | grep -iE 'opendatahub|datasciencecluster|datascienceinitialize|inferenceservice|servingruntime|trustyai|featurestore|notebook'
```

Print:
```
RHOAI CRDs:
  <crd-name>
  <crd-name>
  ...
  Total: <N>
```

### Step 13: Recent Events and Issues Summary (--full only)

Check for recent warning events in RHOAI namespaces. Get the total count first so the tailed output isn't mistaken for the complete picture:

```bash
oc get events -n redhat-ods-applications --field-selector type=Warning --no-headers 2>/dev/null | wc -l
```

```bash
oc get events -n redhat-ods-applications --sort-by='.lastTimestamp' --field-selector type=Warning 2>/dev/null | tail -10
```

```bash
oc get events -n redhat-ods-operator --field-selector type=Warning --no-headers 2>/dev/null | wc -l
```

```bash
oc get events -n redhat-ods-operator --sort-by='.lastTimestamp' --field-selector type=Warning 2>/dev/null | tail -10
```

When reporting, show both: "showing last 10 of `<total>` warning events" — a high total with only a few distinct messages in the tail can still indicate a persistent underlying issue.

Compile an issues summary. Analyze all collected data and list any problems found:

```
Issues Found:
  - <issue description>
  - <issue description>
```

If no issues:
```
Issues Found:
  - None
```

Common issue patterns to flag:
- CSV phase is not `Succeeded`
- DSC phase is not `Ready` (but see caveat in "Learned from Trial Runs")
- Pods in `CrashLoopBackOff`, `Error`, `ImagePullBackOff`
- Required dependency operators missing (cert-manager, leader-worker-set, connectivity-link)
- CatalogSource not in `READY` state
- Warning events indicating persistent problems (not one-off transients)

## Learned from Trial Runs

1. **DSC phase `Ready=False` does not always mean broken.** The DSC reports `Ready=False` when any component has a non-`Available` condition. A common case is `trainer` showing `PreConditionFailed` because Kueue is not installed. If the user does not need training features, this is expected and safe to ignore. Report the specific component causing the non-Ready phase so the user can decide.

2. **Some dependency operators are optional.** `cert-manager`, `leader-worker-set`, and `connectivity-link` (rhcl) are required for core RHOAI. `ServiceMesh`, `Serverless`, `Authorino`, `Kueue`, and `JobSet` are only needed when specific components are enabled (KServe with RawDeployment, model serving, distributed training). Do not flag optional operators as missing unless related DSC components are explicitly enabled and failing.

3. **Distinguish Running, Completed, and problematic pods.** `Completed` pods are normal — they are finished Jobs (e.g., model registry database migrations, cleanup tasks). Only pods that are not `Running` or `Completed` are problematic. Do not count `Completed` pods as failures.

4. **Pod restart counts matter.** A pod showing `Running` with 50+ restarts is not healthy. Check the `RESTARTS` column and flag pods with high restart counts (>5) even if currently Running.

5. **The `redhat-ods-monitoring` namespace may not exist.** On some RHOAI versions or configurations, monitoring is not deployed. If the namespace does not exist, report "Namespace not found" rather than treating it as an error.

6. **CatalogSource can be in `redhat-ods-operator` or `openshift-marketplace`.** Nightly/pre-release installs put the CatalogSource in `redhat-ods-operator`. GA installs use the default `openshift-marketplace` CatalogSources. Check both namespaces.

7. **Multiple CSVs may exist during upgrades.** During an upgrade, both the old and new CSV may be present. The old one will be in `Replacing` phase and the new one in `Installing` or `Succeeded`. Report both when found.

8. **`oc get gateway` requires the Gateway API CRD.** On clusters without the Gateway API CRD installed, this command returns an error. Handle this gracefully and report "Gateway API not available on this cluster."

9. **Console URL may differ from API URL.** `oc whoami --show-console` returns the web console URL. The RHOAI dashboard route is a separate URL. Do not confuse the two.

## Do Not

- Do not combine shell commands with `&&`, `;`, or `||`
- Do not proceed past preflight if `oc whoami` fails
- Do not flag `Completed` pods as failures — they are finished Jobs
- Do not flag optional dependency operators as missing unless related DSC components are failing
- Do not treat DSC `Ready=False` as a hard failure — check which component is causing it and report specifics
- Do not assume all three RHOAI namespaces exist — handle missing namespaces gracefully
- Do not run any commands that modify cluster state — this skill is read-only
- Do not skip the quick summary even in `--full` mode — always print it first
- Do not treat Warning events as critical — many are transient and resolve themselves
- Do not report the OCP console URL as the RHOAI dashboard URL — they are different endpoints
