#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# install.sh — Install JBoss EAP Operator 3.2.13 + JBoss EAP 8 on OpenShift CRC
#
# Operator : Red Hat JBoss EAP Operator 3.2.13
# Catalog  : redhat-operators  (built in to every CRC cluster)
# Channel  : stable
# Image    : registry.redhat.io/jboss-eap-8/eap8-openjdk17-runtime-openshift-rhel8
#
# Prerequisites:
#   • crc start           (≥ 4 CPUs / 10 GB RAM)
#   • oc login            (kubeadmin or cluster-admin)
#   • Red Hat account     (free at https://access.redhat.com) for registry.redhat.io
#
# Usage:
#   ./install.sh                              # prompts for RH credentials
#   ./install.sh --rh-user U --rh-password P  # non-interactive
#   ./install.sh --uninstall                  # tear everything down
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

NAMESPACE="jboss-production"
OPERATOR_WAIT_SECONDS=180
SERVER_WAIT_SECONDS=300
INTERVAL=10
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PULL_SECRET_NAME="rh-registry-secret"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
step()  { echo -e "${CYAN}[STEP]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

# ── Argument parsing ──────────────────────────────────────────────────────────
RH_USER=""
RH_PASS=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --uninstall)
      info "Uninstalling JBoss EAP Operator and instance …"
      oc delete wildflyserver   jboss-instance     -n "$NAMESPACE" --ignore-not-found
      oc delete subscription    eap                -n "$NAMESPACE" --ignore-not-found
      oc delete subscription    wildfly            -n "$NAMESPACE" --ignore-not-found
      oc delete operatorgroup   jboss-operatorgroup -n "$NAMESPACE" --ignore-not-found
      CSV=$(oc get csv -n "$NAMESPACE" --no-headers 2>/dev/null \
        | grep -iE "eap|wildfly" | awk '{print $1}' || true)
      [[ -n "$CSV" ]] && oc delete csv "$CSV" -n "$NAMESPACE" --ignore-not-found
      oc delete secret "$PULL_SECRET_NAME" -n "$NAMESPACE" --ignore-not-found
      oc delete clusterrole        wildfly-operator --ignore-not-found
      oc delete clusterrolebinding wildfly-operator --ignore-not-found
      oc delete crd wildflyservers.wildfly.org --ignore-not-found
      oc delete namespace "$NAMESPACE" --ignore-not-found
      info "Uninstall complete."
      exit 0
      ;;
    --rh-user)      RH_USER="$2";  shift 2 ;;
    --rh-password)  RH_PASS="$2";  shift 2 ;;
    *) error "Unknown argument: $1. Use --rh-user / --rh-password / --uninstall" ;;
  esac
done

# ── Preflight ─────────────────────────────────────────────────────────────────
info "Checking prerequisites …"
command -v oc &>/dev/null || error "'oc' CLI not found."
oc whoami &>/dev/null      || error "Not logged in. Run 'oc login' first."
info "Logged in as: $(oc whoami)  |  Server: $(oc whoami --show-server)"

# Confirm the EAP operator package is available in redhat-operators
info "Verifying 'eap' package exists in redhat-operators catalog …"
EAP_PKG=$(oc get packagemanifest eap -n openshift-marketplace \
  -o jsonpath='{.metadata.name}' 2>/dev/null || true)
if [[ "$EAP_PKG" != "eap" ]]; then
  warn "'eap' package not found in redhat-operators on this cluster."
  warn "Available EAP/JBoss packages:"
  oc get packagemanifest -n openshift-marketplace --no-headers 2>/dev/null \
    | grep -iE "eap|jboss|wildfly" || echo "  (none found)"
  error "Cannot proceed without the 'eap' package. Check your CRC version or Red Hat subscription."
fi
info "  Package 'eap' found ✓"

# ── Step 1: Namespace ─────────────────────────────────────────────────────────
step "1/6 — Creating namespace '${NAMESPACE}' …"
oc apply -f "${SCRIPT_DIR}/00-namespace.yaml"
oc project "$NAMESPACE"

# ── Step 2: Pull secret for registry.redhat.io ────────────────────────────────
step "2/6 — Setting up Red Hat registry pull secret …"
if oc get secret "$PULL_SECRET_NAME" -n "$NAMESPACE" &>/dev/null; then
  info "  Pull secret '${PULL_SECRET_NAME}' already exists — skipping."
else
  if [[ -z "$RH_USER" ]]; then
    echo ""
    echo "  The JBoss EAP 8 image is hosted on registry.redhat.io"
    echo "  and requires a (free) Red Hat account."
    echo "  Sign up at: https://access.redhat.com"
    echo ""
    read -rp "  Red Hat username: " RH_USER
    read -rsp "  Red Hat password: " RH_PASS
    echo ""
  fi

  info "  Creating pull secret '${PULL_SECRET_NAME}' …"
  oc create secret docker-registry "$PULL_SECRET_NAME" \
    --docker-server=registry.redhat.io \
    --docker-username="$RH_USER" \
    --docker-password="$RH_PASS" \
    -n "$NAMESPACE"

  # Link the secret to the default and builder service accounts
  oc secrets link default "$PULL_SECRET_NAME" --for=pull -n "$NAMESPACE"
  oc secrets link builder "$PULL_SECRET_NAME"             -n "$NAMESPACE" 2>/dev/null || true
  info "  Pull secret created and linked ✓"
fi

# Also patch the global cluster pull secret so the operator can pull its own image
info "  Patching global cluster pull secret with registry.redhat.io credentials …"
EXISTING_PS=$(oc get secret pull-secret -n openshift-config \
  -o jsonpath='{.data.\.dockerconfigjson}' 2>/dev/null | base64 -d || echo '{"auths":{}}')

# Only patch if registry.redhat.io is not already present
if ! echo "$EXISTING_PS" | grep -q "registry.redhat.io"; then
  if [[ -n "$RH_USER" && -n "$RH_PASS" ]]; then
    RH_AUTH=$(echo -n "${RH_USER}:${RH_PASS}" | base64)
    PATCHED=$(echo "$EXISTING_PS" | python3 -c "
import sys, json, base64
ps = json.load(sys.stdin)
ps['auths']['registry.redhat.io'] = {
  'auth': '$(echo -n "${RH_USER}:${RH_PASS}" | base64)'
}
print(json.dumps(ps))
")
    oc set data secret/pull-secret -n openshift-config \
      --from-literal=.dockerconfigjson="$PATCHED" 2>/dev/null || \
      warn "  Could not patch global pull secret (may need cluster-admin). Continuing …"
    info "  Global pull secret updated ✓"
  fi
else
  info "  registry.redhat.io already in global pull secret ✓"
fi

# ── Step 3: OperatorGroup ─────────────────────────────────────────────────────
step "3/6 — Creating OperatorGroup …"
oc apply -f "${SCRIPT_DIR}/01-operatorgroup.yaml"

# ── Step 4: Subscription ──────────────────────────────────────────────────────
step "4/6 — Installing JBoss EAP Operator 3.2.13 via OLM …"
oc apply -f "${SCRIPT_DIR}/02-subscription.yaml"

info "Waiting up to ${OPERATOR_WAIT_SECONDS}s for EAP Operator CSV to reach Succeeded …"
ELAPSED=0
CSV_NAME=""
while true; do
  CSV_NAME=$(oc get csv -n "$NAMESPACE" --no-headers 2>/dev/null \
    | grep -i "eap-operator" | awk '{print $1}' || true)
  CSV_STATUS=$(oc get csv -n "$NAMESPACE" --no-headers 2>/dev/null \
    | grep -i "eap-operator" | awk '{print $NF}' || true)

  if [[ "$CSV_STATUS" == "Succeeded" ]]; then
    info "CSV '${CSV_NAME}' reached Succeeded ✓"
    break
  fi

  if (( ELAPSED >= OPERATOR_WAIT_SECONDS )); then
    warn "CSV not ready after ${OPERATOR_WAIT_SECONDS}s."
    warn "Current status: '${CSV_STATUS:-<not found>}'"
    warn "Debug with:"
    warn "  oc describe subscription eap -n ${NAMESPACE}"
    warn "  oc get csv -n ${NAMESPACE}"
    warn "  oc get installplan -n ${NAMESPACE}"
    read -rp "Continue anyway? [y/N] " yn
    [[ "${yn,,}" == "y" ]] || exit 1
    break
  fi

  printf "  … CSV: '%-30s'  status: '%-15s'  (%ds)\r" \
    "${CSV_NAME:-pending}" "${CSV_STATUS:-pending}" "$ELAPSED"
  sleep "$INTERVAL"; ELAPSED=$(( ELAPSED + INTERVAL ))
done

# ── Step 5: WildFlyServer CR ───────────────────────────────────────────────────
step "5/6 — Creating WildFlyServer CR (JBoss EAP 8 instance) …"
oc apply -f "${SCRIPT_DIR}/03-wildflyserver.yaml"

info "Waiting up to ${SERVER_WAIT_SECONDS}s for jboss-instance pod to be Ready …"
ELAPSED=0
while true; do
  POD_LINE=$(oc get pods -n "$NAMESPACE" \
    -l "app.kubernetes.io/name=jboss-instance" \
    --no-headers 2>/dev/null | head -1 || true)
  READY=$(echo "$POD_LINE" | awk '{print $2}')
  POD_STATUS=$(echo "$POD_LINE" | awk '{print $3}')

  if [[ "$READY" =~ ^[0-9]+/[0-9]+$ ]]; then
    CUR="${READY%%/*}"; TOT="${READY##*/}"
    if (( CUR == TOT && TOT > 0 )); then
      info "JBoss EAP 8 pod is Ready ✓  (${READY})"
      break
    fi
  fi

  # Surface image pull errors early
  if [[ "$POD_STATUS" == "ImagePullBackOff" || "$POD_STATUS" == "ErrImagePull" ]]; then
    warn "Image pull error detected — check registry.redhat.io credentials:"
    warn "  oc describe pod -n ${NAMESPACE} -l app.kubernetes.io/name=jboss-instance"
    warn "  oc get secret ${PULL_SECRET_NAME} -n ${NAMESPACE}"
    break
  fi

  if (( ELAPSED >= SERVER_WAIT_SECONDS )); then
    warn "Pod not ready after ${SERVER_WAIT_SECONDS}s. Check:"
    warn "  oc get pods -n ${NAMESPACE}"
    warn "  oc describe wildflyserver jboss-instance -n ${NAMESPACE}"
    warn "  oc logs -n ${NAMESPACE} -l app.kubernetes.io/name=jboss-instance"
    break
  fi

  printf "  … pod status: '%-12s'  ready: '%-5s'  (%ds elapsed)\r" \
    "${POD_STATUS:-Pending}" "${READY:--/-}" "$ELAPSED"
  sleep "$INTERVAL"; ELAPSED=$(( ELAPSED + INTERVAL ))
done

# ── Step 6: Summary ───────────────────────────────────────────────────────────
step "6/6 — Installation summary"
echo ""
printf "  %-18s %s\n" "Namespace:"  "$NAMESPACE"
printf "  %-18s %s\n" "Operator CSV:" "${CSV_NAME:-eap-operator.v3.2.13}"
echo ""
echo -e "  ${CYAN}Pods:${NC}"
oc get pods -n "$NAMESPACE" 2>/dev/null || true
echo ""
echo -e "  ${CYAN}Services:${NC}"
oc get svc -n "$NAMESPACE" 2>/dev/null || true
echo ""
echo -e "  ${CYAN}Routes (external HTTPS):${NC}"
oc get route -n "$NAMESPACE" 2>/dev/null || true
echo ""
echo -e "  ${CYAN}WildFlyServer status:${NC}"
oc get wildflyserver jboss-instance -n "$NAMESPACE" 2>/dev/null || true
echo ""

# Health check URL
ROUTE_HOST=$(oc get route -n "$NAMESPACE" --no-headers 2>/dev/null \
  | grep jboss | awk '{print $2}' | head -1 || true)
if [[ -n "$ROUTE_HOST" ]]; then
  echo "  External health check:"
  echo "    curl -k https://${ROUTE_HOST}/health/ready"
  echo ""
fi

info "Done! JBoss EAP 8 (Operator 3.2.13) is running on OpenShift CRC."
info ""
info "AI Monitor config to update in k8s/configmap.yaml:"
info "  JBOSS_NAMESPACE:        \"${NAMESPACE}\""
info "  JBOSS_LABEL_SELECTOR:   \"app.kubernetes.io/managed-by=wildfly-operator\""
info "  HEALTH_CHECK_PATH:      \"/health/ready\""
