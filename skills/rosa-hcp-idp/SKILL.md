---
name: rosa-hcp-idp
description: >
  Set up an identity provider on a freshly-created ROSA Hosted Control Plane
  cluster and grant a user cluster-admin, so you can actually log in. Waits for
  the cluster to be Ready, creates an htpasswd identity provider via the rosa CLI,
  grants cluster-admin, and verifies oc login against the Control Plane API
  endpoint. Run after rosa-hcp-create reports Ready.
  Trigger phrases include: "set up identity provider", "add idp to rosa cluster",
  "grant cluster-admin", "can't log into my rosa cluster", "rosa htpasswd",
  "configure rosa login", "rosa idp".
allowed-tools: Bash Read AskUserQuestion
---

# ROSA HCP Identity Provider

A new ROSA HCP cluster has no way to log in until you add an identity provider.
Dev work requires authenticating as **cluster-admin**. This skill adds a simple
htpasswd IdP and grants cluster-admin.

## Input

`$ARGUMENTS`: `<cluster-name> [<username>]`

- `<cluster-name>` — required. The cluster from `rosa-hcp-create`.
- `<username>` — the admin user to create. If omitted, ask.

## Steps

### Step 1: Confirm the cluster is Ready

An IdP cannot be added until the cluster is Ready.

```bash
rosa describe cluster -c "<cluster-name>" | grep -iE 'state|api url|console url'
```

Wait until `State: ready`. Note the **Control Plane API endpoint** (API URL) from
this output — you will log in against it. The console URL and the "Cluster Roles
and Access" tab take several more minutes to appear after the API is up.

### Step 2: Create the htpasswd identity provider

You can do this in the OCM UI (cluster → **Access control > Identity providers**),
or with the rosa CLI (preferred here for reproducibility):

```bash
rosa create idp --cluster="<cluster-name>" --type=htpasswd \
  --name=htpasswd --username="<username>" --password='<password>'
```

Ask the user for a password rather than inventing one; do not echo it into logs
or command history unnecessarily. If they prefer the UI, point them to
**Access control > Identity providers** and continue at Step 3 once created.

### Step 3: Grant cluster-admin

```bash
rosa grant user cluster-admin --user="<username>" --cluster="<cluster-name>"
```

(In the OCM UI this is under **Access control > Cluster Roles and Access**, which
only appears a few minutes after the cluster is Ready.)

Propagation takes a short while — a minute or two is normal before login works.

### Step 4: Verify login

Get the API endpoint and log in:

```bash
API_URL=$(rosa describe cluster -c "<cluster-name>" -o json | \
  python3 -c 'import json,sys;print(json.load(sys.stdin)["api"]["url"])')
oc login -u "<username>" "$API_URL"
oc whoami
oc auth can-i '*' '*' --all-namespaces   # should print "yes" for cluster-admin
```

If login is rejected immediately after granting, wait a couple of minutes and
retry — IdP and role bindings take time to propagate.

### Step 5: Report

Tell the user: the cluster name, API URL, the admin username created, and that
they now have cluster-admin. If they intend to install a pre-release RHOAI build,
point them at the `install-rhoai-nightly` skill.
