#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# fix-image-pull.sh — Fix ErrImagePull / ImagePullBackOff for jboss-instance
#
# Run this if the jboss-instance-0 pod gets stuck in ErrImagePull after
# install.sh completes. The EAP Operator creates the StatefulSet without
# imagePullSecrets; this script patches it and restarts the pod.
#
# Usage:
#   ./fix-image-pull.sh
#   ./fix-image-pull.sh --rh-user U --rh-password P   # re-create pull secret
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

NAMESPACE="jboss-production"
PULL_SECRET_NAME="rh-registry-secret"
STATEFULSET="jboss-instance"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; CYAN='\033[0;36m'; NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC}  $*"; }
step()  { echo -e "${CYAN}[STEP]${NC}  $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
error() { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }

RH_USER=""; RH_PASS=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --rh-user)     RH_USER="$2"; shift 2 ;;
    --rh-password) RH_PASS="$2"; shift 2 ;;
    *) error "Unknown argument: $1" ;;
  esac
done

# ── Preflight ─────────────────────────────────────────────────────────────────
oc whoami &>/dev/null || error "Not logged in. Run 'oc login' first."
oc project "$NAMESPACE" &>/dev/null || error "Namespace '${NAMESPACE}' not found."

# ── Step 1: Re-create pull secret if credentials supplied ──────────────────
if [[ -n "$RH_USER" && -n "$RH_PASS" ]]; then
  step "1 — Re-creating pull secret with supplied credentials …"
  oc delete secret "$PULL_SECRET_NAME" -n "$NAMESPACE" --ignore-not-found
  oc create secret docker-registry "$PULL_SECRET_NAME" \
    --docker-server=registry.redhat.io \
    --docker-username="$RH_USER" \
    --docker-password="$RH_PASS" \
    -n "$NAMESPACE"
  info "  Pull secret re-created ✓"
else
  step "1 — Verifying pull secret exists …"
  oc get secret "$PULL_SECRET_NAME" -n "$NAMESPACE" &>/dev/null || \
    error "Secret '${PULL_SECRET_NAME}' not found. Re-run with --rh-user / --rh-password."
  info "  Pull secret '${PULL_SECRET_NAME}' exists ✓"
fi

# ── Step 2: Link pull secret to every SA in the namespace ─────────────────
step "2 — Linking pull secret to all ServiceAccounts in '${NAMESPACE}' …"
for SA in $(oc get sa -n "$NAMESPACE" -o jsonpath='{.items[*].metadata.name}'); do
  if oc secrets link "$SA" "$PULL_SECRET_NAME" --for=pull \
       -n "$NAMESPACE" 2>/dev/null; then
    info "  Linked → SA '${SA}' ✓"
  fi
done

# ── Step 3: Patch the StatefulSet to set imagePullSecrets ──────────────────
step "3 — Patching StatefulSet '${STATEFULSET}' to add imagePullSecrets …"
CURRENT_IPS=$(oc get statefulset "$STATEFULSET" -n "$NAMESPACE" \
  -o jsonpath='{.spec.template.spec.imagePullSecrets}' 2>/dev/null || echo "")

if echo "$CURRENT_IPS" | grep -q "$PULL_SECRET_NAME"; then
  info "  imagePullSecrets already contains '${PULL_SECRET_NAME}' ✓"
else
  oc patch statefulset "$STATEFULSET" -n "$NAMESPACE" \
    --type=json \
    -p="[{\"op\":\"add\",\"path\":\"/spec/template/spec/imagePullSecrets\",\"value\":[{\"name\":\"${PULL_SECRET_NAME}\"}]}]"
  info "  StatefulSet patched ✓"
fi

# ── Step 4: Also update global cluster pull secret ──────────────────────────
step "4 — Checking global cluster pull secret …"
GLOBAL_PS=$(oc get secret pull-secret -n openshift-config \
  -o jsonpath='{.data.\.dockerconfigjson}' 2>/dev/null | base64 -d || echo '{}')

if echo "$GLOBAL_PS" | python3 -c "
import sys, json
ps = json.load(sys.stdin)
auths = ps.get('auths', {})
rh = auths.get('registry.redhat.io', {})
# Check if the auth token is non-empty
sys.exit(0 if rh.get('auth','') else 1)
" 2>/dev/null; then
  info "  Global pull secret has registry.redhat.io entry ✓"
else
  if [[ -n "$RH_USER" && -n "$RH_PASS" ]]; then
    warn "  Updating global pull secret with registry.redhat.io credentials …"
    RH_AUTH_B64=$(echo -n "${RH_USER}:${RH_PASS}" | base64)
    UPDATED=$(echo "$GLOBAL_PS" | python3 -c "
import sys, json
ps = json.load(sys.stdin)
ps.setdefault('auths', {})['registry.redhat.io'] = {'auth': '${RH_AUTH_B64}', 'email': ''}
print(json.dumps(ps))
")
    oc set data secret/pull-secret -n openshift-config \
      --from-literal=.dockerconfigjson="$UPDATED" && \
      info "  Global pull secret updated ✓" || \
      warn "  Could not update global pull secret (need cluster-admin). Continuing …"
  else
    warn "  registry.redhat.io not found in global pull secret."
    warn "  Re-run with --rh-user / --rh-password to fix it."
  fi
fi

# ── Step 5: Delete stuck pod so StatefulSet recreates it ──────────────────
step "5 — Restarting jboss-instance-0 …"
oc delete pod "${STATEFULSET}-0" -n "$NAMESPACE" --ignore-not-found
info "  Pod deleted — StatefulSet will recreate it momentarily."

# ── Step 6: Watch ─────────────────────────────────────────────────────────
echo ""
info "Watching pod startup (Ctrl+C to stop watching):"
echo ""
oc get pods -n "$NAMESPACE" -w &
WATCH_PID=$!

# Wait up to 3 minutes for the pod to be ready
ELAPSED=0; LIMIT=180; INTERVAL=10
while (( ELAPSED < LIMIT )); do
  sleep "$INTERVAL"; ELAPSED=$(( ELAPSED + INTERVAL ))
  READY=$(oc get pod "${STATEFULSET}-0" -n "$NAMESPACE" \
    -o jsonpath='{.status.containerStatuses[0].ready}' 2>/dev/null || echo "false")
  STATUS=$(oc get pod "${STATEFULSET}-0" -n "$NAMESPACE" \
    -o jsonpath='{.status.phase}' 2>/dev/null || echo "Pending")

  if [[ "$READY" == "true" ]]; then
    kill $WATCH_PID 2>/dev/null || true
    echo ""
    info "jboss-instance-0 is Ready ✓"
    break
  fi
  if [[ "$STATUS" == "ImagePullBackOff" || "$STATUS" == "ErrImagePull" ]]; then
    kill $WATCH_PID 2>/dev/null || true
    echo ""
    error "Still getting image pull errors. Check your Red Hat credentials and re-run with --rh-user / --rh-password."
  fi
done

# ── Final summary ─────────────────────────────────────────────────────────
kill $WATCH_PID 2>/dev/null || true
echo ""
oc get pods -n "$NAMESPACE"
echo ""
ROUTE=$(oc get route -n "$NAMESPACE" --no-headers 2>/dev/null \
  | grep jboss | awk '{print $2}' | head -1 || true)
[[ -n "$ROUTE" ]] && info "Health check: curl -k https://${ROUTE}/health/ready"
