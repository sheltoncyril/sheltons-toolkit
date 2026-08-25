---
name: rosa-hcp-troubleshoot
description: >
  Diagnose and fix common failures when creating ROSA Hosted Control Plane
  clusters on the shared OpenShift AI engineering infrastructure. Covers stale
  rosa CLI, 500 errors from unset variables, TagLimitExceeded (50-tag subnet cap)
  including orphaned-tag cleanup, account-role version incompatibility, missing
  OIDC config (wrong account), and rh-aws-saml-login / kinit / VPN credential
  errors. Always starts from the "are you on the latest rosa CLI and the right
  accounts" check, because that resolves most issues.
  Trigger phrases include: "rosa cluster failed", "rosa create error",
  "TagLimitExceeded", "rosa 500 error", "oidc config not found",
  "rh-aws-saml-login error", "kinit error", "clear orphaned subnet tags",
  "rosa hcp troubleshoot", "account role not compatible".
allowed-tools: Bash Read AskUserQuestion
---

# ROSA HCP Troubleshoot

Diagnose ROSA HCP creation failures. **The vast majority of problems are solved by
updating to the very latest rosa CLI from GitHub** — always rule that out first.

## Step 0: Always start here

```bash
rosa version                     # must say "Your ROSA CLI is up to date."
aws sts get-caller-identity      # Account must be 585132637328, ARN = your name
aws configure get region         # must be us-east-1
rosa whoami                      # External ID 14351703, Org ID 1pwwsfazToamNegaehP6eaDg80K
```

If `rosa version` is stale, update from <https://github.com/openshift/rosa/releases>
and retry the failing command before anything else. If accounts are wrong, fix
those (see `rosa-hcp-preflight`) — most "weird" errors are really wrong-account
errors.

Then match the symptom below.

## Symptom: generic error, cause unknown

You were probably on an old rosa CLI. Update it (GitHub, not console.redhat.com)
and retry. It changes ~weekly.

## Symptom: `500` error during `rosa create cluster`

Either the rosa service is having an outage (unlikely), or one of the subnet/role
variables did not make it into the command. Echo them and check each:

```bash
echo "OIDC_CONFIG_ID=$OIDC_CONFIG_ID"
echo "INSTALLER_ROLE=$INSTALLER_ROLE"
echo "SUPPORT_ROLE=$SUPPORT_ROLE"
echo "WORKER_ROLE=$WORKER_ROLE"     # expect arn:aws:iam::585132637328:role/shared-rosa-hcp-HCP-ROSA-Worker-Role
echo "PRIVATE_SUBNET=$PRIVATE_SUBNET"
echo "PUBLIC_SUBNET=$PUBLIC_SUBNET"
```

Any empty or wrong value → re-set it (see `rosa-hcp-create`) and retry.

## Symptom: `TagLimitExceeded` — "must not have more than 50 user tags"

The shared subnets are tagged once per cluster; AWS caps this at 50 per subnet
(hard limit). Two fixes, in order:

1. **Switch to a less-tagged subnet pair.** Count tags on all shared subnets and
   pick the lightest pair:
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
   Set `PRIVATE_SUBNET`/`PUBLIC_SUBNET` to the lightest pair and retry create.

2. **If every pair is near 50, clear orphaned tags** (tags left by deleted
   clusters). See the next section.

## Clearing orphaned subnet tags

Uses the bundled helper `scripts/rosa_cleanup.py` (needs `boto3`:
`pip3 install boto3`). It lists `kubernetes.io/cluster/*` tags on each shared
subnet and, cross-referenced against the currently-live clusters, prints
`aws ec2 delete-tags` commands **only** for clusters that no longer exist.

```bash
# 1. Verify identity FIRST — you are about to modify shared infra.
aws sts get-caller-identity

# 2. Capture the live cluster names so we never delete a live cluster's tag.
LIVE_CLUSTERS="$(rosa list clusters -o json 2>/dev/null | \
  python3 -c 'import json,sys;print(",".join(c["name"] for c in json.load(sys.stdin)))')"
export LIVE_CLUSTERS

# 3. Generate cleanup commands for orphaned tags across all shared subnets.
#    <skill-dir> is this skill's base directory (given in the skill invocation header).
for SUBNET in subnet-06f0819a60ec83b06 subnet-0f36103ff259bed5a \
              subnet-0a2ab6507448d7c17 subnet-06cddec8e0a71a16f \
              subnet-0866fb9d6b2c19f24 subnet-03e2fbd47aa625cc7 \
              subnet-0ff7c007c4ddb3a9a subnet-002bfa1d5944b0a79; do
  python3 <skill-dir>/scripts/rosa_cleanup.py "$SUBNET"
done
```

Review the emitted `aws ec2 delete-tags ...` commands, confirm none reference a
live cluster, then run them. They produce no output; re-run the loop to confirm —
if it prints nothing, all orphaned tags are cleared. Update the "Last cleaned"
note in the source doc afterwards.

## Symptom: account role not compatible with the OpenShift version

```
E: Account role 'arn:aws:iam::585132637328:role/shared-rosa-hcp-Installer-Role'
   is not compatible with version openshift-v4.x.y. Run 'rosa create account-roles' ...
```

Do **not** run `rosa create account-roles` yourself — the shared roles are managed
and this needs temporary AWS admin. Post in `#team-openshift-ai-devel` and tag
`@gshereme`; it is usually a one-minute fix.

## Symptom: OIDC config not found

```
E: There was a problem retrieving OIDC Config '23c734st3pn7l167mq97d0ot8848lgrl': ... not found
```

You are almost certainly in the wrong AWS and/or OCM account. Re-verify Step 0.
Do **not** create a new OIDC config — the shared one is required.

## Symptom: `rh-aws-saml-login` / `kinit` / VPN errors

- `CalledProcessError: Command '['kinit', '']' returned non-zero exit status 1`
  → run `kinit <user>@IPA.REDHAT.COM` first.
- `kinit <user>@IPA.REDHAT.COM` fails → verify/reset your IPA password at
  <https://token.redhat.com/> (reset: <https://identity.corp.redhat.com/resetipa>).
- `kinit: krb5_get_init_creds: unable to reach any KDC in realm IPA.REDHAT.COM`
  → connect to the VPN, then retry.
- `ValueError: No AWS accounts found` → your SSO needs access to more than one AWS
  account (the login page should show an account picker). Request the app-interface
  access fix in `#rhoai-devtestops-requests`.

## Still stuck

Post in `#team-openshift-ai-devel` with the exact commands you ran and the output
of: `aws sts get-caller-identity | cat`, `aws configure get region`,
`rosa version`, `rosa whoami`.
