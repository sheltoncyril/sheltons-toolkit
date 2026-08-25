---
name: rosa-hcp-destroy
description: >
  Safely tear down a ROSA Hosted Control Plane cluster in the shared OpenShift AI
  engineering account. Deletes the cluster, waits for it to be gone, then deletes
  ONLY that cluster's operator roles by prefix — and never the shared OIDC
  provider, which is required by everyone's clusters. Guards against the two
  destructive mistakes: deleting the shared OIDC provider (kills all clusters) and
  leaving orphaned operator roles behind (accumulate toward AWS's 5000-role limit).
  Trigger phrases include: "destroy rosa cluster", "delete rosa hcp cluster",
  "tear down my cluster", "remove rosa cluster", "clean up operator roles",
  "rosa delete cluster".
allowed-tools: Bash Read AskUserQuestion
---

# ROSA HCP Destroy

Tear down a ROSA HCP cluster cleanly. Two rules govern everything here:

> **NEVER delete the shared OIDC provider.** It is shared across the whole RHOAI
> org. Running `rosa delete oidc-provider` (config `23c734st3pn7l167mq97d0ot8848lgrl`)
> will break authentication for **everyone's** clusters. Do not run it, ever.

> **Always delete the cluster's operator roles.** AWS caps the account at 5000
> IAM roles. Orphaned operator roles from un-cleaned deletions accumulate until
> no new clusters can be created.

## Input

`$ARGUMENTS`: `<cluster-name>`

## Steps

### Step 0: Confirm the target and the account

This is destructive and outward-facing (shared account). Confirm before acting:

```bash
aws sts get-caller-identity          # Account must be 585132637328
rosa describe cluster -c "<cluster-name>" | grep -iE 'name|state|id'
```

Show the user the cluster name and state and get explicit confirmation to
destroy **this specific cluster**. Do not proceed on a partial/ambiguous name.

### Step 1: Delete the cluster

```bash
rosa delete cluster --cluster "<cluster-name>"
```

Note the `rosa delete operator-roles --prefix ...` command it prints on completion
— you will need that prefix in Step 3. It will also print a
`rosa delete oidc-provider` command: **ignore that one. Do not run it.**

### Step 2: Wait for the cluster to be fully deleted

Operator roles cannot be removed until the cluster is gone.

```bash
rosa logs uninstall -c "<cluster-name>" --watch 2>/dev/null || true
# then poll until it disappears from the list:
rosa list clusters | grep -i "<cluster-name>" || echo "cluster deleted"
```

Wait until the cluster no longer appears in `rosa list clusters`.

### Step 3: Delete ONLY the operator roles (by this cluster's prefix)

Use the prefix rosa printed in Step 1. If unsure of the exact prefix, list roles
and identify the ones belonging to this cluster:

```bash
rosa list operator-roles 2>/dev/null | grep -i "<cluster-name>"
```

Then:

```bash
rosa delete operator-roles --prefix "<cluster-prefix>" --mode auto
```

Confirm the prefix matches **only** the destroyed cluster before running. Do not
delete roles belonging to other clusters.

### Step 4: Do NOT touch the OIDC provider

Explicitly skip the `rosa delete oidc-provider` step. State clearly in the final
report that the shared OIDC provider was intentionally left in place.

### Step 5: Report

Confirm: cluster deleted, operator roles for its prefix deleted, shared OIDC
provider left intact. If the operator-roles deletion was skipped for any reason,
flag it loudly — orphaned roles count against the 5000-role account limit.
