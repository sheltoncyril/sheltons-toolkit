---
name: configure-gateway
description: >
  Configure MaaS or llm-d inference gateway on an OpenShift cluster with RHOAI.
  Supports connected (LoadBalancer) and disconnected (ClusterIP + Route) modes.
  Also configures MaaS PostgreSQL. Locates olminstall automatically.
  Trigger phrases include: "configure gateway", "setup gateway", "maas gateway",
  "llmd gateway", "configure maas", "configure llm-d", "setup postgres".
allowed-tools: Bash Read AskUserQuestion
---

# Configure Gateway

Configure MaaS gateway, llm-d inference gateway, or MaaS PostgreSQL on an OpenShift cluster.

## Constants

- **MaaS Gateway name:** `maas-default-gateway`
- **llm-d Gateway name:** `openshift-ai-inference`
- **GatewayClass:** `openshift-default`
- **Ingress namespace:** `openshift-ingress`
- **MaaS Gateway service (disconnected):** `maas-default-gateway-openshift-default`
- **llm-d Gateway service (disconnected):** `openshift-ai-inference-openshift-default`

## Input

`$ARGUMENTS` format: `<maas|llmd|postgres> [--disconnected <mirror-registry>]`

Examples:
```
maas
llmd --disconnected mirror.example.com:5000
postgres
maas --disconnected registry.disconnected.local:8443
```

- `<maas|llmd|postgres>` -- required. Which component to configure.
- `--disconnected <mirror-registry>` -- optional. Enables disconnected mode: sets `MIRROR_REGISTRY` env var, configures ClusterIP service type instead of LoadBalancer, adds WASM insecure registries ConfigMap, and creates an OpenShift Route for external access.

## Steps

### Step 0: Parse Input

Parse `$ARGUMENTS` to extract the component and optional `--disconnected` flag with its mirror registry value.

If no component provided, print usage and stop:
```
Usage: /configure-gateway <maas|llmd|postgres> [--disconnected <mirror-registry>]

Components:
  maas       Configure MaaS gateway (GatewayClass + wildcard cert + Gateway)
  llmd       Configure llm-d inference gateway (GatewayClass + Gateway)
  postgres   Configure PostgreSQL for MaaS

Options:
  --disconnected <mirror-registry>   Enable disconnected mode (ClusterIP + Route)

Examples:
  /configure-gateway maas
  /configure-gateway llmd --disconnected mirror.example.com:5000
  /configure-gateway postgres
```

If component is not one of `maas`, `llmd`, or `postgres`, report error and stop.

Store `COMPONENT` and optionally `MIRROR_REGISTRY`.

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
oc version -o json | python3 -c "import json,sys; print(json.load(sys.stdin).get('openshiftVersion', 'unknown'))"
```

Report:
```
Preflight:
  Cluster:    <server>
  User:       <whoami>
  OCP:        <server-version>
  Component:  <COMPONENT>
  Mode:       connected | disconnected (<MIRROR_REGISTRY>)
```

### Step 2: Verify RHOAI Installed

```bash
oc get csv -n redhat-ods-operator --no-headers 2>/dev/null | grep -i rhods
```

If no output, ask with `AskUserQuestion`:
```
RHOAI does not appear to be installed (no rhods CSV found).
Gateway configuration typically requires RHOAI. Continue anyway? (yes / no)
```

If no, stop.

### Step 3: Check ServiceMesh and Gateway CRDs

For `maas` or `llmd` components, verify required CRDs exist:

```bash
oc get crd gateways.gateway.networking.k8s.io -o name 2>/dev/null
```

```bash
oc get crd gatewayclasses.gateway.networking.k8s.io -o name 2>/dev/null
```

If either CRD is missing, stop with:
```
Required Gateway API CRDs not found. Install the Service Mesh operator first.
Missing: <list of missing CRDs>

Install with: /install-rhoai-nightly (includes servicemeshoperator3)
Or manually: oc apply -f resources/install-servicemeshoperator3.yaml
```

For `postgres`, skip this step entirely.

### Step 4: Locate olminstall Repo

Search these paths in order. Each is a separate Bash call:

```bash
ls -d ../olminstall/configure-maas-gateway.sh 2>/dev/null
```

```bash
ls -d ~/Desktop/Work/olminstall/configure-maas-gateway.sh 2>/dev/null
```

```bash
ls -d ~/olminstall/configure-maas-gateway.sh 2>/dev/null
```

```bash
ls -d /tmp/olminstall/configure-maas-gateway.sh 2>/dev/null
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

After obtaining a path, validate it has the required scripts based on the component:

For `maas`:
```bash
ls <path>/configure-maas-gateway.sh
```

For `llmd`:
```bash
ls <path>/configure-llmd-gateway.sh
```

For `postgres`:
```bash
ls <path>/configure-maas-postgres.sh
```

If the script is missing, report which file is missing and stop.

Store `OLMINSTALL_PATH` (the directory, not the script path).

### Step 5: Run Configuration Script

Build and execute the command based on the component.

**For `maas`:**

```bash
cd <OLMINSTALL_PATH> && bash configure-maas-gateway.sh
```

If disconnected mode, prepend `MIRROR_REGISTRY`:

```bash
cd <OLMINSTALL_PATH> && MIRROR_REGISTRY=<mirror-registry> bash configure-maas-gateway.sh
```

**For `llmd`:**

```bash
cd <OLMINSTALL_PATH> && bash configure-llmd-gateway.sh
```

If disconnected mode, prepend `MIRROR_REGISTRY`:

```bash
cd <OLMINSTALL_PATH> && MIRROR_REGISTRY=<mirror-registry> bash configure-llmd-gateway.sh
```

**For `postgres`:**

```bash
cd <OLMINSTALL_PATH> && bash configure-maas-postgres.sh
```

The `postgres` script does not use `MIRROR_REGISTRY`. If `--disconnected` was passed with `postgres`, ignore it and note: "PostgreSQL configuration does not use disconnected mode; --disconnected flag ignored."

Monitor the output for errors. If the script exits non-zero, report the error output and stop.

### Step 6: Verify Resources

Run verification commands based on the component. Each is a separate Bash call.

**For `maas`:**

```bash
oc get gateway maas-default-gateway -n openshift-ingress -o wide
```

```bash
oc get gateway maas-default-gateway -n openshift-ingress -o jsonpath='{.status.conditions[?(@.type=="Programmed")].status}'
```

If disconnected:

```bash
oc get configmap maas-default-gateway-config -n openshift-ingress -o name
```

```bash
oc get route maas-default-gateway -n openshift-ingress -o jsonpath='{.spec.host}'
```

Also confirm the ClusterIP service (disconnected mode replaces the LoadBalancer service with this one):

```bash
oc get service maas-default-gateway-openshift-default -n openshift-ingress -o jsonpath='{.spec.type}'
```

**For `llmd`:**

```bash
oc get gateway openshift-ai-inference -n openshift-ingress -o wide
```

```bash
oc get gateway openshift-ai-inference -n openshift-ingress -o jsonpath='{.status.conditions[?(@.type=="Programmed")].status}'
```

If disconnected:

```bash
oc get configmap openshift-ai-inference-config -n openshift-ingress -o name
```

```bash
oc get route openshift-ai-inference -n openshift-ingress -o jsonpath='{.spec.host}'
```

Also confirm the ClusterIP service (disconnected mode replaces the LoadBalancer service with this one):

```bash
oc get service openshift-ai-inference-openshift-default -n openshift-ingress -o jsonpath='{.spec.type}'
```

**For `postgres`:**

```bash
oc get pods -l app=postgresql -A --no-headers 2>/dev/null
```

### Step 7: Print Summary

Gather info and print a summary.

**For `maas` (connected):**

```bash
oc get ingresses.config.openshift.io cluster -o jsonpath='{.spec.domain}'
```

```
MaaS Gateway configured successfully.

  Gateway:      maas-default-gateway
  Namespace:    openshift-ingress
  GatewayClass: openshift-default
  Status:       Programmed
  Mode:         connected (LoadBalancer)
  Domain:       maas.<cluster-domain>
  HTTPS:        enabled (wildcard cert)
```

**For `maas` (disconnected):**

```
MaaS Gateway configured successfully.

  Gateway:      maas-default-gateway
  Namespace:    openshift-ingress
  GatewayClass: openshift-default
  Status:       Programmed
  Mode:         disconnected (ClusterIP + Route)
  Route:        <route-host>
  ConfigMap:    maas-default-gateway-config
  Mirror:       <MIRROR_REGISTRY>
```

**For `llmd` (connected):**

```
llm-d Inference Gateway configured successfully.

  Gateway:      openshift-ai-inference
  Namespace:    openshift-ingress
  GatewayClass: openshift-default
  Status:       Programmed
  Mode:         connected (LoadBalancer)
```

**For `llmd` (disconnected):**

```
llm-d Inference Gateway configured successfully.

  Gateway:      openshift-ai-inference
  Namespace:    openshift-ingress
  GatewayClass: openshift-default
  Status:       Programmed
  Mode:         disconnected (ClusterIP + Route)
  Route:        <route-host>
  ConfigMap:    openshift-ai-inference-config
  Mirror:       <MIRROR_REGISTRY>
```

**For `postgres`:**

```
MaaS PostgreSQL configured successfully.

  Script source: https://raw.githubusercontent.com/red-hat-data-services/ods-ci/master/ods_ci/tasks/Resources/Database/configure_maas_postgres.sh
```

## Learned from Trial Runs

These are hard-won lessons from real cluster testing sessions.

1. **Scripts must run from the olminstall directory.** Both `configure-maas-gateway.sh` and `configure-llmd-gateway.sh` use `BASE_DIR=$(dirname $(readlink -f ${BASH_SOURCE[0]}))` to locate templates in `resources/` and utilities in `utils/`. Running via an absolute path works, but the `cd && bash` pattern is safest because some template resolution depends on the working directory when `readlink -f` fails on macOS.

2. **GatewayClass must exist before Gateway.** Both scripts apply `gateway-class-instance.yaml` first. If a previous run partially failed, the GatewayClass may already exist -- this is fine because `oc apply` is idempotent.

3. **The MaaS gateway uses wildcard TLS certs from the ingress controller.** It reads `spec.defaultCertificate.name` from the `default` IngressController. If no custom cert is configured, it falls back to the `router-certs-default` secret. This means HTTPS works out of the box on clusters with default certs.

4. **Disconnected mode creates three extra resources per gateway.** A ConfigMap (sets ClusterIP service type and WASM insecure registries), a modified Gateway spec (with `infrastructure.parametersRef`), and a Route (TLS edge termination). All three must exist for disconnected access to work.

5. **The ConfigMap template is shared between MaaS and llm-d.** Both use `disconnected-llmd-gateway-configmap.yaml.template` with placeholder substitution for `GATEWAY_NAME`, `INGRESS_NS`, and `MIRROR_REGISTRY`. The MaaS script substitutes `maas-default-gateway` as the gateway name.

6. **The Route template is also shared.** `disconnected-llmd-gateway-route.yaml.template` uses `GATEWAY_NAME`, `INGRESS_NS`, and `GATEWAY_SERVICE` placeholders. The service name follows the pattern `<gateway-name>-<gatewayclass-name>` (e.g., `maas-default-gateway-openshift-default`).

7. **Gateway Programmed condition can take up to 5 minutes.** The MaaS script waits with `--timeout=5m`, while the llm-d script uses `--timeout=120s`. If it times out, the gateway is not necessarily broken -- it may still be provisioning.

8. **The MaaS gateway binds to a specific hostname.** It uses `maas.<cluster-domain>` for both HTTP and HTTPS listeners. The llm-d gateway does not set a hostname -- it accepts all traffic.

9. **The postgres script is a thin wrapper.** It downloads and executes `configure_maas_postgres.sh` from the `ods-ci` repo on GitHub. It requires internet access (even on "disconnected" clusters, the script itself needs to be fetched). The `--disconnected` flag has no effect on it.

10. **The `target/` directory is used for generated files.** Both gateway scripts create templated YAML in `<olminstall>/target/`. This directory is gitignored. Re-running overwrites previous generated files.

11. **The `oc_wait_for_route` function is required.** Both gateway scripts source `utils/oc_wait.sh` which provides `oc_wait_for_route`. This function waits for the Route's Admitted condition. Without it, the script would fail on the route wait step in disconnected mode.

12. **MaaS gateway has `opendatahub.io/managed: "false"` labels and annotations.** This prevents the RHOAI operator from reconciling and overwriting the gateway configuration. The llm-d gateway does not have this annotation -- it uses the `serving.kserve.io/gateway: kserve-ingress-gateway` label instead, which ties it to KServe.

## Do Not

- Do not run the scripts from a directory other than the olminstall repo root
- Do not combine shell commands with `&&`, `;`, or `||` except for the `cd <OLMINSTALL_PATH> && bash <script>` pattern in Step 5 (required because cwd resets between Bash calls)
- Do not proceed past preflight if `oc whoami` fails
- Do not skip the CRD check for `maas` or `llmd` -- the scripts will fail silently or create broken resources without Gateway API CRDs
- Do not assume `MIRROR_REGISTRY` applies to the `postgres` component -- it does not
- Do not assume the olminstall repo is already cloned
- Do not modify the template files in `resources/` -- the scripts handle substitution into `target/`
- Do not delete files in the `target/` directory -- they are useful for debugging and are overwritten on re-runs
- Do not set `MIRROR_REGISTRY` to a URL with a scheme (e.g., `https://`) -- the scripts expect `host:port` format only
