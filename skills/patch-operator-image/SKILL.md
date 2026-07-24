---
name: patch-operator-image
description: >
  Patch the TrustyAI service operator deployment to use a candidate image for
  testing. Accepts an image URI, auto-detects which RELATED_IMAGE env var and
  ConfigMap key to update via pattern matching, patches both the deployment and
  configmap, adds the opendatahub.io/managed annotation, and restarts the
  rollout. Supports revert mode to restore original values.
  Trigger phrases include: "patch operator image", "swap operator image",
  "use candidate image", "patch trustyai image", "revert operator image",
  "restore operator image", "patch deployment image".
allowed-tools: Bash Read Write AskUserQuestion
---

# Patch Operator Image

Swap a TrustyAI operator image for hermetic candidate testing, with automatic revert.

## Constants

- **Deployment:** `trustyai-service-operator-controller-manager`
- **Namespace:** `redhat-ods-applications`
- **ConfigMap:** `trustyai-service-operator-config`
- **Container:** `manager`
- **Backup file:** `/tmp/sheltons-toolkit-operator-patch-backup.json`

## Input

`$ARGUMENTS` is one of:

- **An image URI** (patch mode) — e.g., `quay.io/rhoai/pull-request-pipelines:odh-trustyai-nemo-guardrails-server-rhel9-...-linux-x86-64`
- **A GitHub PR URL** — resolves the Konflux-built image automatically (see Step 0.5)
- **`revert`** — restore original values from backup
- **Empty** — show usage help listing known image patterns

Optional arch suffix (append to any mode): `--arch <ARCH>` where ARCH is `x86-64` (default), `aarch64`, or `s390x`. Used when resolving from PR URL.

## Steps

### Step 0: Parse Mode

Check if `$ARGUMENTS` contains `--arch`. If so, extract the arch value (`x86-64`, `aarch64`, or `s390x`) and remove it from the arguments. Default arch is `x86-64`.

If `$ARGUMENTS` (after removing `--arch`) starts with `https://github.com/`, treat it as a PR URL and go to Step 0.5.

If `$ARGUMENTS` is empty, Read `<skill-dir>/resources/image-mapping.json` and print a usage table:

```
Usage: /sheltons-toolkit:patch-operator-image <image-uri|revert>

Known image patterns:
  Pattern                      | Component
  -----------------------------|---------------------------
  trustyai-service-operator    | TrustyAI Service Operator
  nemo-guardrails-server       | NeMo Guardrails Server
  eval-hub                     | EvalHub
  ...
```

Then stop.

If `$ARGUMENTS` is `revert` or `--revert`, go to Step 6 (Revert).

Otherwise, treat `$ARGUMENTS` as the image URI and continue to Step 1.

### Step 0.5: Resolve PR to Image (conditional)

If `$ARGUMENTS` is a GitHub PR URL, resolve the Konflux-built image.

Extract `owner/repo` and PR number from the URL. Then:

```bash
gh pr view <NUMBER> --repo <OWNER/REPO> --json headRefOid,statusCheckRollup --jq '{sha: .headRefOid, checks: [.statusCheckRollup[] | select(.name != null) | select(.name | contains("Konflux")) | .name]}'
```

From the result:
1. Get the head commit SHA
2. Get the Konflux check name (e.g., `Konflux Production Internal / odh-ta-lmes-job-on-pull-request-57892`)
3. Extract the component: take the part after ` / `, then regex-match `(.+)-on-pull-request-\d+` — capture group 1 is the component (e.g., `odh-ta-lmes-job`)
4. Construct the image URI: `quay.io/rhoai/pull-request-pipelines:<component>-<full-sha>-linux-<ARCH>`

Use the arch from `--arch` flag (default `x86-64`).

If no Konflux check found, report error and stop.

If multiple Konflux checks exist, list them and ask the user which one to use.

Report:
```
Resolved from PR #<number>:
  Component: <component>
  SHA:       <sha>
  Arch:      <arch>
  Image:     quay.io/rhoai/pull-request-pipelines:<component>-<sha>-linux-<arch>
```

Use this as the image URI and continue to Step 1.

### Step 1: Prerequisites

Run these checks (fail fast on any):

```bash
oc whoami
```

```bash
oc get deployment trustyai-service-operator-controller-manager -n redhat-ods-applications -o name
```

If either fails, report the error and stop.

### Step 1.5: Verify Image Exists

Before patching, verify the image is actually available on the registry:

```bash
oc image info <IMAGE_URI> --filter-by-os=linux/amd64 2>&1 | head -5
```

If the output contains "manifest unknown", "unauthorized", or "not found", the image does not exist. Report:

```
ERROR: Image not found on registry.
  Image: <IMAGE_URI>
  
This likely means the Konflux build has not completed or has failed.
Check the build status before retrying.
```

Stop the workflow. Do not patch with a nonexistent image.

### Step 2: Match Image Pattern

Read `<skill-dir>/resources/image-mapping.json`.

Iterate the array **in order** (longest/most-specific patterns are listed first). For each entry, check if `entry.pattern` is a substring of the image URI. Stop at the **first match**.

If no match found, print the known patterns table and stop with an error.

Report the match:
```
Matched: <description>
  Env var:      <env_var>
  ConfigMap key: <configmap_key>
```

### Step 3: Save Current State

Read current values before patching.

For a regular env var match:

```bash
oc get deployment trustyai-service-operator-controller-manager -n redhat-ods-applications -o jsonpath='{.spec.template.spec.containers[?(@.name=="manager")].env[?(@.name=="<ENV_VAR>")].value}'
```

For a container image match (`is_container_image: true`):

```bash
oc get deployment trustyai-service-operator-controller-manager -n redhat-ods-applications -o jsonpath='{.spec.template.spec.containers[?(@.name=="manager")].image}'
```

Read the ConfigMap value:

```bash
oc get configmap trustyai-service-operator-config -n redhat-ods-applications -o jsonpath='{.data.<CONFIGMAP_KEY>}'
```

Note: if the configmap key contains hyphens, use the bracket notation: `{.data['<key>']}`

Read the current managed annotation:

```bash
oc get deployment trustyai-service-operator-controller-manager -n redhat-ods-applications -o jsonpath='{.metadata.annotations.opendatahub\.io/managed}'
```

Write all values to the backup file using the Write tool at `/tmp/sheltons-toolkit-operator-patch-backup.json`:

```json
{
  "timestamp": "<ISO-8601>",
  "new_image_uri": "<the image being patched in>",
  "matched_pattern": "<pattern>",
  "matched_description": "<description>",
  "is_container_image": false,
  "env_var_name": "<ENV_VAR>",
  "env_var_original_value": "<original value>",
  "configmap_key": "<key>",
  "configmap_original_value": "<original value>",
  "managed_annotation_original": "<true|false|empty string>"
}
```

### Step 4: Apply Patch

Run these three commands sequentially. Do NOT combine with `&&` or `;`.

**4a. Add managed annotation:**

```bash
oc annotate deployment trustyai-service-operator-controller-manager opendatahub.io/managed="false" -n redhat-ods-applications --overwrite
```

**4b. Patch the image:**

For a regular env var:

```bash
oc set env deployment/trustyai-service-operator-controller-manager <ENV_VAR>=<IMAGE_URI> -n redhat-ods-applications -c manager
```

For a container image (`is_container_image: true`):

```bash
oc set image deployment/trustyai-service-operator-controller-manager manager=<IMAGE_URI> -n redhat-ods-applications
```

**4c. Patch the ConfigMap:**

```bash
oc patch configmap trustyai-service-operator-config -n redhat-ods-applications --type merge -p '{"data":{"<CONFIGMAP_KEY>":"<IMAGE_URI>"}}'
```

### Step 5: Rollout and Verify

Restart the deployment and wait for rollout:

```bash
oc rollout restart deployment/trustyai-service-operator-controller-manager -n redhat-ods-applications
```

```bash
oc rollout status deployment/trustyai-service-operator-controller-manager -n redhat-ods-applications --timeout=120s
```

After rollout completes, verify by reading back the patched value (same jsonpath as Step 3). Confirm it matches the new image URI.

Print summary:

```
Patch applied successfully.

  Component:    <description>
  Old image:    <original value>
  New image:    <new image URI>
  Backup saved: /tmp/sheltons-toolkit-operator-patch-backup.json

To revert: /sheltons-toolkit:patch-operator-image revert
```

### Step 6: Revert Mode

Read `/tmp/sheltons-toolkit-operator-patch-backup.json` using the Read tool. If the file does not exist, report error and stop.

Restore the env var or container image to its original value (use the same `oc set env` or `oc set image` command from Step 4b but with the original value).

Restore the ConfigMap key to its original value (same `oc patch configmap` from Step 4c with the original value).

Restore the managed annotation to its original state:
- If original was `"true"`, set it back to `"true"`
- If original was `"false"`, leave it (already `"false"`)
- If original was empty string (annotation didn't exist), remove it:

```bash
oc annotate deployment trustyai-service-operator-controller-manager opendatahub.io/managed- -n redhat-ods-applications
```

Rollout restart and wait (same as Step 5).

Delete the backup file:

```bash
rm /tmp/sheltons-toolkit-operator-patch-backup.json
```

Print summary:

```
Revert complete.

  Component:      <description>
  Restored image: <original value>
```

## Learned from Trial Runs

These are hard-won lessons from real cluster testing sessions.

**Deployment name is not obvious.** The deployment is `trustyai-service-operator-controller-manager`, not `trustyai-service-operator`. The container inside it is called `manager`.

**`opendatahub.io/managed` may already be `"false"`.** On some clusters (e.g., hermetic testing environments), the annotation and label are already set to `"false"`. The `--overwrite` flag on `oc annotate` handles this idempotently.

**ConfigMap and deployment env vars can diverge.** The deployment has `RELATED_IMAGE_*` env vars and the ConfigMap `trustyai-service-operator-config` has its own keys. They often hold different values (e.g., env var may have a PR pipeline tag while ConfigMap has the registry.redhat.io SHA256 digest). Both must be patched for the operator to use the candidate image when spawning sub-components.

**The `oc set env` command triggers a rollout automatically** on a Deployment. Doing `oc rollout restart` after is still correct to ensure all changes (annotation + env + configmap) are picked up cleanly, but be aware the env change alone already starts a new rollout.

**Konflux build failure means no image on quay.io.** Always verify the image exists (Step 1.5) before patching. A failed or in-progress Konflux build produces no image, and the operator will create pods that go into `ImagePullBackOff`.

**Konflux image tag pattern:** `<component>-<full-40-char-git-sha>-linux-<arch>` pushed to `quay.io/rhoai/pull-request-pipelines`. The component name is extracted from the GitHub check name by stripping `-on-pull-request-<number>`.

**Pattern matching order matters.** `trustyai-service` is a substring of `trustyai-service-operator`. The image-mapping.json array is ordered longest-first so `trustyai-service-operator` matches before the shorter `trustyai-service`.

## Do Not

- Do not patch without saving backup first
- Do not patch in any namespace other than `redhat-ods-applications`
- Do not combine shell commands with `&&`, `;`, or `||`
- Do not proceed if `oc whoami` fails
- Do not skip the rollout restart — env var changes need a pod restart to take effect
- Do not delete the backup file in patch mode (only delete on successful revert)
- Do not patch with an image that hasn't been verified to exist on the registry
