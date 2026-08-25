---
name: rosa-hcp-preflight
description: >
  Verify every prerequisite for creating a ROSA Hosted Control Plane (HyperShift)
  cluster in the shared OpenShift AI engineering AWS/OCM accounts, before any
  cluster is created. Checks aws/ocm/rosa/oc CLIs are installed, that credentials
  point at the correct shared accounts (AWS 585132637328 in us-east-1, OCM org
  7081269 / external ID 14351703), that the rosa CLI is the latest GitHub build,
  and that the shared OIDC config and account roles exist. Reports a pass/fail
  checklist and refuses to proceed to cluster creation until everything is green.
  Trigger phrases include: "rosa preflight", "check rosa prerequisites",
  "verify rosa login", "am I logged into the right account", "rosa hcp preflight",
  "check aws ocm rosa", "ready to create a rosa cluster".
allowed-tools: Bash Read AskUserQuestion
---

# ROSA HCP Preflight

Confirm you can talk to the shared OpenShift AI engineering AWS and OCM accounts,
with the correct identities, before creating a ROSA Hosted Control Plane cluster.
Most cluster-creation failures are actually "wrong account" or "stale rosa CLI"
problems — this skill catches them up front.

Run this before `rosa-hcp-create`. Do not create a cluster until every check
below passes.

## Shared account constants

These never change as long as you are using the shared RHODS AWS and OCM accounts:

| Thing | Expected value |
|-------|----------------|
| AWS account ID | `585132637328` |
| AWS region | `us-east-1` (required) |
| SAML profile | `iaps-rhods-odh-dev` |
| OCM account number (browser) | `7081269` |
| OCM Organization External ID | `14351703` |
| OCM Organization ID | `1pwwsfazToamNegaehP6eaDg80K` |
| OCM Organization Name | `Red Hat, Inc.` |
| Shared OIDC config ID | `23c734st3pn7l167mq97d0ot8848lgrl` |

## Steps

### Step 1: CLIs installed

Check each tool is on `$PATH`:

```bash
for bin in aws ocm rosa oc; do
  if command -v "$bin" >/dev/null 2>&1; then
    printf 'OK    %-5s %s\n' "$bin" "$(command -v "$bin")"
  else
    printf 'FAIL  %-5s not found on PATH\n' "$bin"
  fi
done
```

Fixes for anything missing:
- `aws` — install the AWS CLI.
- `ocm` / `oc` — download from <https://console.redhat.com/openshift/downloads>.
- `rosa` — see Step 4 (must be the latest GitHub build, not the console.redhat.com one).

### Step 2: AWS identity points at the shared account

```bash
aws sts get-caller-identity
aws configure get region
```

Requirements:
- `Account` must be exactly `585132637328`. If it is anything else, the caller is
  in the wrong AWS account — stop and fix credentials.
- `Arn` must contain the user's own name (e.g. `.../585132637328-rhoai-dev/<you>`),
  **not** `osdCcsAdmin`.
- Region must be `us-east-1`.

If credentials are missing or expired, refresh them with the SAML helper:

```bash
export $(rh-aws-saml-login --output env iaps-rhods-odh-dev)
```

Note: the SAML token is a short-lived STS token. If cluster creation later fails
with an auth/expiry error, re-run this command to refresh. On macOS you must
export **all** variables the tool prints. See `rosa-hcp-troubleshoot` for
`rh-aws-saml-login` / `kinit` / VPN errors.

### Step 3: OCM login points at the shared org

```bash
ocm whoami
```

Confirm `organization.id` is `1pwwsfazToamNegaehP6eaDg80K`. If not logged in or in
the wrong org:

```bash
ocm login --url production --use-auth-code
```

We always use the **production** environment for these clusters.

### Step 4: rosa CLI is logged in AND up to date

```bash
rosa whoami
rosa version
```

- The last three lines of `rosa whoami` must match **exactly**:
  ```
  OCM Organization External ID: 14351703
  OCM Organization ID:          1pwwsfazToamNegaehP6eaDg80K
  OCM Organization Name:        Red Hat, Inc.
  ```
  A wrong External ID means the wrong OCM account; a wrong Organization ID means
  the wrong environment. If either is off, the browser session used the wrong
  login — log into <https://console.redhat.com/openshift> in a fresh incognito tab
  as the account showing **Account number: 7081269**, then:
  ```bash
  rosa login --use-auth-code --url=https://api.openshift.com
  ```
- `rosa version` must say **"Your ROSA CLI is up to date."** The rosa CLI changes
  roughly weekly and a stale CLI is the single most common cause of failures.
  Always install the latest **from GitHub** (releases at
  <https://github.com/openshift/rosa/releases>), not from console.redhat.com. If
  it is out of date, update it and re-run this step.

### Step 5: Shared OIDC config and account roles exist

```bash
rosa list oidc-providers 2>/dev/null | grep -i 23c734st3pn7l167mq97d0ot8848lgrl \
  && echo "OK    shared OIDC config present" \
  || echo "WARN  shared OIDC config 23c734st3pn7l167mq97d0ot8848lgrl not visible — likely wrong AWS/OCM account (recheck Steps 2-4)"

rosa list account-roles 2>/dev/null | grep -i 'shared-rosa-hcp-HCP-ROSA' \
  && echo "OK    shared HCP account roles present" \
  || echo "WARN  shared HCP account roles not found — post in #team-openshift-ai-devel"
```

If the OIDC config is not visible, you are almost certainly in the wrong AWS
and/or OCM account — go back to Steps 2–4. Do **not** try to create a new OIDC
config; the shared one is required.

### Step 6: Report

Print a compact checklist of each step's result (OK / FAIL / WARN) and a single
verdict line:

- **All green** → "Preflight passed. Safe to run `rosa-hcp-create`."
- **Any FAIL** → list the failed checks and the exact fix, and stop. Do not
  proceed to cluster creation.

Do not create a cluster from this skill — hand off to `rosa-hcp-create` only after
a clean pass.
