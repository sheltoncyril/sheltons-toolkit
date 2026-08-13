---
name: deploy-component-manifests
description: >
  Deploy custom component manifests into an OLM-deployed ODH/RHOAI operator.
  Builds kustomize overlays from a component operator repo, optionally overrides
  images in params.env, patches the ODH operator CSV to mount a PVC, copies
  manifests into the operator pod, and restarts. Supports revert to original
  manifests. Use for sustained dev work where the ODH operator should manage
  the component lifecycle with your custom manifests.
  Trigger phrases include: "deploy manifests", "swap manifests", "deploy component",
  "use custom manifests", "manifest approach", "OLM install", "revert manifests",
  "component dev install".
allowed-tools: Bash Read Write AskUserQuestion
---

# Deploy Component Manifests

Deploy custom component manifests into an OLM-deployed ODH/RHOAI operator using the kustomize overlay approach from `opendatahub-io/opendatahub-operator/hack/component-dev/`.

## Constants

- **Component map:** `<skill-dir>/resources/component-map.json`
- **Backup suffix:** `.bak` (appended to modified params.env files)
- **Manifest mount base:** `/opt/manifests/`
- **ODH operator label:** `name=opendatahub-operator`
- **RHOAI operator label:** `name=rhods-operator`
- **ODH operator namespace:** `openshift-operators`
- **RHOAI operator namespace:** `redhat-ods-operator`

## Input

`$ARGUMENTS` is one of:

- **A component repo path** (deploy mode) — e.g., `../trustyai-service-operator` or `/Users/scyril/Desktop/Work/trustyai-service-operator`
- **`revert`** — remove the PVC mount and restart the operator to use original manifests
- **Empty** — show usage help

Optional flags (append to deploy mode):

- `--overlay <name>` — which overlay to build (default: auto-detect from cluster)
- `--image <key>=<value>` — override an image in params.env. Can be specified multiple times. Format: `<params.env-key>=<image-uri>`
- `--operator-namespace <ns>` — namespace where the ODH/RHOAI operator runs (default: auto-detect)

## Steps

### Step 0: Parse Input

If `$ARGUMENTS` is empty, print usage and stop:

```
Usage: /sheltons-toolkit:deploy-component-manifests <component-repo-path> [options]

Options:
  --overlay <name>              Overlay to build (default: auto-detect from cluster)
  --image <key>=<value>         Override image in params.env (repeatable)
  --operator-namespace <ns>     Operator namespace (default: auto-detect)

Modes:
  <path>                        Deploy manifests from component repo
  revert                        Remove PVC mount and restore original manifests

Examples:
  /sheltons-toolkit:deploy-component-manifests ../trustyai-service-operator
  /sheltons-toolkit:deploy-component-manifests ../trustyai-service-operator --overlay rhoai --image lmes-pod-image=quay.io/rhoai/pull-request-pipelines:odh-ta-lmes-job-abc123-linux-x86-64
  /sheltons-toolkit:deploy-component-manifests revert
```

Then stop.

If `$ARGUMENTS` is `revert` or `--revert`, go to Step 10 (Revert).

Otherwise, extract the component repo path as the first positional argument. Parse any `--overlay`, `--image`, and `--operator-namespace` flags from the remaining arguments.

### Step 1: Validate Component Repo

Check that the component repo path exists and has a `config/overlays/` directory:

```bash
ls -d <component-repo-path>/config/overlays/
```

If it fails, report the error and stop.

Read `<skill-dir>/resources/component-map.json`. For each known component, check whether its `detection_file` exists AND contains its `detection_pattern`. For TrustyAI:

```bash
grep -q "trustyaiServiceImage" <component-repo-path>/config/overlays/odh/params.env
```

A bare file-existence check is not enough — any repo with a `params.env` at that path would otherwise be misidentified as TrustyAI. The pattern grep confirms it's actually the right component.

If no component matches, report:

```
ERROR: Could not identify component from repo at <path>.
Supported components: trustyai
```

Then stop.

Store the matched component name (e.g., `trustyai`) and its metadata from the component map.

### Step 2: Prerequisites

Run these checks (fail fast on any):

```bash
oc whoami
```

```bash
oc version --client
```

```bash
which kustomize
```

If `oc whoami` fails, report the error and stop. If `kustomize` is not installed, warn but continue (kustomize is not strictly required since the ODH operator runs it internally, but it is useful for validation).

### Step 3: Detect Platform and Overlay

If `--overlay` was not specified, auto-detect the platform from the cluster:

```bash
oc get dsci -o jsonpath='{.items[0].metadata.name}' 2>/dev/null
```

Then check if RHOAI or ODH:

```bash
oc get subscription -n redhat-ods-operator --no-headers 2>/dev/null | grep -q rhods
```

If the subscription exists, platform is `rhoai`. Otherwise, platform is `odh`.

Set the overlay to match the platform name.

Verify the overlay directory exists:

```bash
ls -d <component-repo-path>/config/overlays/<overlay>/
```

If it does not exist, list available overlays and stop:

```bash
ls <component-repo-path>/config/overlays/
```

### Step 4: Detect Operator Namespace

If `--operator-namespace` was not specified, set it based on platform:

- `rhoai` -> `redhat-ods-operator`
- `odh` -> `openshift-operators`

Verify the namespace exists and has the operator:

```bash
oc get deployment -n <operator-namespace> -l name=opendatahub-operator -o name 2>/dev/null
```

```bash
oc get deployment -n <operator-namespace> -l name=rhods-operator -o name 2>/dev/null
```

One of these must succeed. Store the operator label (`name=opendatahub-operator` or `name=rhods-operator`) for later use.

### Step 5: Apply Image Overrides

If `--image` flags were provided, apply each override to `config/overlays/<overlay>/params.env`.

First, back up the original:

```bash
cp <component-repo-path>/config/overlays/<overlay>/params.env <component-repo-path>/config/overlays/<overlay>/params.env.bak
```

For each `--image key=value`, verify the key exists in params.env:

```bash
grep -q "^<key>=" <component-repo-path>/config/overlays/<overlay>/params.env
```

If the key does not exist, report error and stop. Do not add unknown keys.

Then replace the value using the Edit tool on the params.env file. Replace the line `<key>=<old-value>` with `<key>=<new-value>`.

Report each override:

```
Image override applied:
  Key:       <key>
  Old value: <old-value>
  New value: <new-value>
```

### Step 6: Create PVC (Idempotent)

Read the component metadata from the component map. Use the `manifest_path` field as the component name for PVC naming.

Check if the PVC already exists:

```bash
oc get pvc <component>-manifests -n <operator-namespace> -o name 2>/dev/null
```

If it does not exist, create it:

```bash
oc apply -f - <<'EOF'
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: <component>-manifests
  namespace: <operator-namespace>
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 1Gi
EOF
```

### Step 7: Patch the CSV

Get the CSV name:

```bash
oc get csv -n <operator-namespace> -o name | grep -E "opendatahub|rhods" | head -1
```

Extract the CSV name (strip the `clusterserviceversion.operators.coreos.com/` prefix).

Check if the volumeMount already exists on the CSV:

```bash
oc get csv <CSV_NAME> -n <operator-namespace> -o jsonpath='{.spec.install.spec.deployments[0].spec.template.spec.containers[0].volumeMounts[*].mountPath}'
```

If the output contains `/opt/manifests/<component>`, the mount is already applied. Report this and skip the patch.

If the mount does NOT exist, first determine `fsGroup` dynamically — do not hardcode it, the operator namespace's allowed supplemental-group range varies per cluster (and a fixed value is rejected outright under the `restricted-v2` SCC on ROSA):

```bash
oc get namespace <operator-namespace> -o jsonpath='{.metadata.annotations.openshift\.io/sa\.scc\.supplemental-groups}'
```

This returns something like `1000700000/10000`. Take the first number before the `/` as `<FSGROUP>`. If the annotation is empty or missing, fall back to `1001`.

Apply the JSON patch:

```bash
oc patch csv <CSV_NAME> -n <operator-namespace> --type json -p '[
  {"op":"replace","path":"/spec/install/spec/deployments/0/spec/replicas","value":1},
  {"op":"replace","path":"/spec/install/spec/deployments/0/spec/strategy","value":{"type":"Recreate"}},
  {"op":"add","path":"/spec/install/spec/deployments/0/spec/template/spec/securityContext","value":{"fsGroup":<FSGROUP>}},
  {"op":"add","path":"/spec/install/spec/deployments/0/spec/template/spec/containers/0/volumeMounts/-","value":{"name":"<component>-manifests","mountPath":"/opt/manifests/<component>"}},
  {"op":"add","path":"/spec/install/spec/deployments/0/spec/template/spec/volumes/-","value":{"name":"<component>-manifests","persistentVolumeClaim":{"claimName":"<component>-manifests"}}}
]'
```

### Step 8: Wait for Operator Pod

The CSV patch triggers OLM to update the Deployment, but that update isn't instant — `oc wait` run immediately after the patch can match the still-running pre-patch pod and report false-positive readiness. First confirm the Deployment actually picked up the new spec:

```bash
oc get deployment <operator_deployment> -n <operator-namespace> -o jsonpath='{.spec.template.spec.containers[0].volumeMounts[*].mountPath}'
```

Poll (a few seconds apart, up to ~30s) until this includes `/opt/manifests/<component>`. If it never updates, OLM cached the old spec — see the "OLM caches the deployment spec" note below.

Then wait for the new pod to be ready:

```bash
oc wait --for=condition=Ready pod -l <operator-label> -n <operator-namespace> --timeout=120s
```

Where `<operator-label>` is `name=opendatahub-operator` or `name=rhods-operator` based on the detected platform.

### Step 9: Copy Manifests into PVC

Get the operator pod name:

```bash
oc get pod -l <operator-label> -n <operator-namespace> -o jsonpath='{.items[0].metadata.name}'
```

Copy the component config directory into the PVC mount inside the operator pod:

```bash
oc cp <component-repo-path>/config/. <operator-namespace>/<POD_NAME>:/opt/manifests/<component>/
```

Verify the copy succeeded:

```bash
oc exec -n <operator-namespace> <POD_NAME> -- ls /opt/manifests/<component>/
```

Then restart the operator so it re-reads the manifests:

```bash
oc rollout restart deployment -n <operator-namespace> -l <operator-label>
```

Wait for the rollout:

```bash
oc rollout status deployment -n <operator-namespace> -l <operator-label> --timeout=120s
```

### Step 9.5: Verify Deployment

Read the component metadata from the component map. Check that the component operator was redeployed with the new manifests:

```bash
oc get deployment <operator_deployment> -n <applications_namespace> -o jsonpath='{.spec.template.spec.containers[0].image}'
```

If `--image` overrides were applied, also check the RELATED_IMAGE env vars on the component operator deployment to confirm they picked up the new values.

Print summary:

```
Manifests deployed successfully.

  Component:          <component>
  Overlay:            <overlay>
  Operator namespace: <operator-namespace>
  PVC:                <component>-manifests
  CSV patched:        <CSV_NAME>
  Image overrides:    <count> applied

To revert: /sheltons-toolkit:deploy-component-manifests revert
```

### Step 10: Revert Mode

If `$ARGUMENTS` is `revert`:

**10a. Detect platform and operator namespace** (same as Steps 3-4).

**10b. Get the CSV name:**

```bash
oc get csv -n <operator-namespace> -o name | grep -E "opendatahub|rhods" | head -1
```

**10c. Find and remove the volumeMount and volume from the CSV.**

First, identify which volumeMount index corresponds to the component manifest path:

```bash
oc get csv <CSV_NAME> -n <operator-namespace> -o jsonpath='{.spec.install.spec.deployments[0].spec.template.spec.containers[0].volumeMounts}'
```

Find the index of the volumeMount with `mountPath` matching `/opt/manifests/<component>`. Similarly find the volume index.

Apply a JSON patch to remove them (use `"op":"remove"` with the correct indices):

```bash
oc patch csv <CSV_NAME> -n <operator-namespace> --type json -p '[
  {"op":"remove","path":"/spec/install/spec/deployments/0/spec/template/spec/containers/0/volumeMounts/<MOUNT_INDEX>"},
  {"op":"remove","path":"/spec/install/spec/deployments/0/spec/template/spec/volumes/<VOLUME_INDEX>"}
]'
```

Remove the volume index FIRST if it is higher than the mount index, or remove in descending index order, to avoid index shifting.

**10d. Delete the PVC:**

```bash
oc delete pvc <component>-manifests -n <operator-namespace>
```

**10e. Restart the operator:**

```bash
oc rollout restart deployment -n <operator-namespace> -l <operator-label>
```

```bash
oc rollout status deployment -n <operator-namespace> -l <operator-label> --timeout=120s
```

**10f. Restore params.env if modified:**

Check if a backup exists:

```bash
ls <component-repo-path>/config/overlays/<overlay>/params.env.bak
```

If it exists, restore it:

```bash
cp <component-repo-path>/config/overlays/<overlay>/params.env.bak <component-repo-path>/config/overlays/<overlay>/params.env
```

```bash
rm <component-repo-path>/config/overlays/<overlay>/params.env.bak
```

Note: for revert mode, the agent should ask the user for the component repo path if it was not stored from the deploy run. Use AskUserQuestion if needed.

**10g. Print summary:**

```
Revert complete.

  Component:          <component>
  CSV restored:       <CSV_NAME>
  PVC deleted:        <component>-manifests
  params.env restored: <yes|no>

The operator will now use its built-in manifests.
```

## Learned from Trial Runs

These are hard-won lessons from real cluster testing sessions.

**The CSV patch is NOT idempotent.** If you apply the JSON patch to add a volumeMount when one already exists at that path, the CSV will have duplicate mounts and the operator pod will fail to start. Always check if the volumeMount already exists before applying the patch (Step 7).

**The ODH operator runs kustomize internally.** Do not pre-build the kustomize output. Copy the raw `config/` directory structure into the PVC mount. The operator processes it with its own kustomize invocation from `/opt/manifests/<component>/`.

**PVC is RWO.** The PVC uses `ReadWriteOnce` access mode. The operator must run with `replicas=1` and a `Recreate` strategy (not `RollingUpdate`) to avoid two pods contending for the same PVC. The CSV patch sets both.

**fsGroup is required for oc cp.** Without `securityContext.fsGroup` set on the pod spec, `oc cp` into the PVC mount will fail with permission denied errors. The CSV patch sets this, reading the value from the namespace's `sa.scc.supplemental-groups` annotation (see Step 7) rather than hardcoding it.

**Operator labels differ between platforms.** For RHOAI the operator deployment label is `name=rhods-operator`. For ODH it is `name=opendatahub-operator`. Always detect and use the correct label.

**params.env is the single source of truth for component images.** The ODH operator reads `params.env` from the overlay directory and uses the `imageParamMap` in the component's Go code to map those keys to `RELATED_IMAGE_*` env vars. Overriding params.env is the correct way to swap images in this workflow.

**The operator namespace differs between platforms.** RHOAI uses `redhat-ods-operator`. ODH uses `openshift-operators`. Auto-detection via the subscription check is reliable.

**After copying manifests, the operator pod must be restarted.** The operator reads manifests at startup. Simply copying new files into the PVC is not enough — the pod must be restarted to re-read them.

**JSON patch index shifting.** When removing volumeMounts and volumes by index, remove the higher index first. If you remove index 2 before index 5, index 5 shifts to index 4 and your second remove targets the wrong entry.

**oc cp requires the namespace/pod format.** The `oc cp` command requires the format `<namespace>/<pod-name>:<path>`, not just `<pod-name>:<path>`.

**Manifest approach patches the ConfigMap but NOT the deployment env vars.** The ODH/RHOAI operator injects `RELATED_IMAGE_*` env vars from its own CSV, not from the component's params.env. The params.env generates the ConfigMap via kustomize `configMapGenerator`, but the deployment env vars are set by the ODH operator from the CSV's deployment spec. To fully swap a component image, you need BOTH this skill (for ConfigMap + CRDs + RBAC) AND `patch-operator-image` (for the deployment env var). Or patch the RHOAI CSV env vars directly.

**OLM caches the deployment spec.** After patching the CSV, OLM may not immediately update the deployment's ReplicaSet. If the pod fails to start, delete the stale RS to force recreation. Or patch the deployment directly as a fallback.

## Do Not

- Do not apply the CSV patch if the volumeMount already exists
- Do not pre-build kustomize output — copy raw `config/` for the operator to process
- Do not modify the component repo's params.env without creating a `.bak` backup
- Do not combine shell commands with `&&`, `;`, or `||`
- Do not proceed if `oc whoami` fails
- Do not add unknown keys to params.env — only override existing keys
- Do not use `RollingUpdate` strategy — the RWO PVC requires `Recreate`
- Do not remove JSON patch indices in ascending order — remove highest index first to avoid shifting
