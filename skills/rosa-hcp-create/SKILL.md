---
name: rosa-hcp-create
description: >
  Create a ROSA Hosted Control Plane (HyperShift) cluster on the shared OpenShift
  AI engineering infrastructure. Sets the fixed shared variables (OIDC config,
  installer/support/worker role ARNs, VPC subnet pairs), picks a subnet pair with
  the fewest tags to avoid AWS's 50-tag limit, ensures the cluster name is unique,
  runs the correct rosa create cluster command for --hosted-cp, and watches the
  install to Ready. Assumes rosa-hcp-preflight already passed.
  Trigger phrases include: "create a rosa cluster", "provision rosa hcp",
  "rosa create cluster", "spin up a hosted control plane cluster",
  "new rosa hcp cluster", "make me a rosa cluster".
allowed-tools: Bash Read Write AskUserQuestion Skill
---

# ROSA HCP Create

Provision a ROSA Hosted Control Plane cluster using the shared OpenShift AI
engineering AWS/OCM accounts. HyperShift clusters are ~1/3 the cost of OSD or
ROSA-classic, so prefer them for dev work.

**Caveat:** ROSA-hosted does not support Addons. If your use case needs the RHODS
**Addon**, you must use OSD instead. RHODS installed from OperatorHub
(self-managed) runs fine on ROSA-hosted.

## Input

`$ARGUMENTS` (all optional):

```
[<cluster-name>] [--machine-type <type>] [--version <x.y.z>]
```

- `<cluster-name>` — must be unique across all shared clusters. If omitted, ask.
- `--machine-type` — compute machine type (e.g. `m5.2xlarge`). If omitted, ask.
- `--version` — OpenShift version (e.g. `4.21.0`). If omitted, ask or use the
  latest available from `rosa list versions --hosted-cp`.

## Fixed shared variables

These never change while using the shared RHODS AWS/OCM accounts:

```bash
OIDC_CONFIG_ID=23c734st3pn7l167mq97d0ot8848lgrl
INSTALLER_ROLE=arn:aws:iam::585132637328:role/shared-rosa-hcp-HCP-ROSA-Installer-Role
SUPPORT_ROLE=arn:aws:iam::585132637328:role/shared-rosa-hcp-HCP-ROSA-Support-Role
WORKER_ROLE=arn:aws:iam::585132637328:role/shared-rosa-hcp-HCP-ROSA-Worker-Role
```

Shared VPC subnet pairs (private, public):

| Pair | PRIVATE_SUBNET | PUBLIC_SUBNET |
|------|----------------|---------------|
| A | `subnet-06f0819a60ec83b06` | `subnet-0f36103ff259bed5a` |
| B | `subnet-0a2ab6507448d7c17` | `subnet-06cddec8e0a71a16f` |
| C | `subnet-0866fb9d6b2c19f24` | `subnet-03e2fbd47aa625cc7` |
| D | `subnet-0ff7c007c4ddb3a9a` | `subnet-002bfa1d5944b0a79` |

## Steps

### Step 0: Confirm preflight

If it is not already established this session that preflight passed, run the
`rosa-hcp-preflight` skill first, or at minimum re-verify the identity gate:

```bash
aws sts get-caller-identity   # Account must be 585132637328, region us-east-1
rosa whoami                   # External ID 14351703, Org ID 1pwwsfazToamNegaehP6eaDg80K
rosa version                  # must say "up to date"
```

Do not continue if any of these are wrong — see `rosa-hcp-troubleshoot`.

### Step 1: Resolve cluster name (must be unique)

```bash
rosa list clusters
```

Ensure the chosen `<cluster-name>` is not already in the list. If a name was not
supplied, or it collides, ask the user for a unique one. Keep it short and
identifiable (e.g. `chef-dev-1`).

### Step 2: Resolve machine type and version

If not supplied:

```bash
rosa list versions --hosted-cp     # pick a supported version
```

Ask the user for the compute machine type if unknown. Set:

```bash
CLUSTER_NAME=<chosen-name>
MACHINE_POOL_TYPE=<chosen-machine-type>
CLUSTER_VERSION=<chosen-version>
```

### Step 3: Pick the subnet pair with the fewest tags

Each shared subnet accumulates one tag per cluster. AWS caps this at **50 tags
per subnet** (hard limit, cannot be raised), so a heavily-used pair causes
`TagLimitExceeded`. Pick the least-tagged pair automatically rather than guessing:

```bash
for s in subnet-06f0819a60ec83b06 subnet-0f36103ff259bed5a \
         subnet-0a2ab6507448d7c17 subnet-06cddec8e0a71a16f \
         subnet-0866fb9d6b2c19f24 subnet-03e2fbd47aa625cc7 \
         subnet-0ff7c007c4ddb3a9a subnet-002bfa1d5944b0a79; do
  n=$(aws ec2 describe-subnets --subnet-ids "$s" \
        --query 'length(Subnets[0].Tags)' --output text 2>/dev/null)
  printf '%-28s %s tags\n' "$s" "$n"
done
```

Choose the pair (A/B/C/D from the table) whose **private+public** subnets have the
lowest combined tag count and are safely under 50. Set:

```bash
PRIVATE_SUBNET=<private of chosen pair>
PUBLIC_SUBNET=<public of chosen pair>
```

If every pair is near 50, run `rosa-hcp-troubleshoot` to clear orphaned subnet
tags before creating the cluster.

### Step 4: Echo the variables (sanity check)

A missing/empty variable is the usual cause of a `500` error during create.
Confirm they are all set and correct:

```bash
echo "CLUSTER_NAME=$CLUSTER_NAME"
echo "MACHINE_POOL_TYPE=$MACHINE_POOL_TYPE"
echo "CLUSTER_VERSION=$CLUSTER_VERSION"
echo "OIDC_CONFIG_ID=$OIDC_CONFIG_ID"
echo "INSTALLER_ROLE=$INSTALLER_ROLE"
echo "SUPPORT_ROLE=$SUPPORT_ROLE"
echo "WORKER_ROLE=$WORKER_ROLE"
echo "PRIVATE_SUBNET=$PRIVATE_SUBNET"
echo "PUBLIC_SUBNET=$PUBLIC_SUBNET"
```

`echo $WORKER_ROLE` must print
`arn:aws:iam::585132637328:role/shared-rosa-hcp-HCP-ROSA-Worker-Role` exactly.

### Step 5: Create the cluster

```bash
rosa create cluster --sts --oidc-config-id "$OIDC_CONFIG_ID" \
  --cluster-name="$CLUSTER_NAME" --mode=auto --hosted-cp \
  --subnet-ids="$PRIVATE_SUBNET,$PUBLIC_SUBNET" \
  --compute-machine-type="$MACHINE_POOL_TYPE" \
  --role-arn="$INSTALLER_ROLE" --support-role-arn="$SUPPORT_ROLE" \
  --worker-iam-role="$WORKER_ROLE" --version "$CLUSTER_VERSION"
```

Expect it to end with "Cluster '<name>' has been created." and note that the
OIDC provider "already exists" (that is correct — it is shared).

If create fails, do not retry blindly — hand off to `rosa-hcp-troubleshoot`
(handles `500`, `TagLimitExceeded`, account-role incompatibility, missing OIDC).

### Step 6: Watch the install

Install takes about 10 minutes.

```bash
rosa describe cluster -c "$CLUSTER_NAME"
rosa logs install -c "$CLUSTER_NAME" --watch
```

Progress is also visible in the OCM UI cluster list. When the cluster reports
**Ready**, stop and tell the user the next step is `rosa-hcp-idp` to set up an
identity provider and grant cluster-admin (you cannot log in until then).
