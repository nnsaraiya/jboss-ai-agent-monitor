#!/usr/bin/env bash
# =============================================================================
# test-stack.sh — End-to-end smoke test for the JBoss AI Monitor stack
# Run from your local machine with oc logged in to CRC.
# Usage: bash test-stack.sh
# =============================================================================

set -euo pipefail

NAMESPACE="jboss-monitoring"
MONITOR_DEPLOY="jboss-ai-monitor"
JIRA_URL="https://nnsaraiya.atlassian.net"
JIRA_PROJECT="KAN"
GREEN="\033[0;32m"; RED="\033[0;31m"; YELLOW="\033[1;33m"; NC="\033[0m"

pass() { echo -e "${GREEN}  ✅ PASS${NC} — $1"; }
fail() { echo -e "${RED}  ❌ FAIL${NC} — $1"; FAILURES=$((FAILURES+1)); }
warn() { echo -e "${YELLOW}  ⚠️  WARN${NC} — $1"; }

FAILURES=0

echo ""
echo "========================================================"
echo "  JBoss AI Monitor — End-to-End Stack Test"
echo "========================================================"
echo ""

# ── 1. Cluster connectivity ───────────────────────────────────────────────────
echo "[ 1 ] Cluster connectivity"
if oc whoami &>/dev/null; then
  USER=$(oc whoami)
  pass "Logged in as: $USER"
else
  fail "Not logged into OpenShift — run: oc login https://api.crc.testing:6443 -u kubeadmin"
  exit 1
fi

# ── 2. Namespace exists ───────────────────────────────────────────────────────
echo ""
echo "[ 2 ] Namespace"
if oc get namespace "$NAMESPACE" &>/dev/null; then
  pass "Namespace '$NAMESPACE' exists"
else
  fail "Namespace '$NAMESPACE' not found"
fi

# ── 3. JBoss EAP 8 pod running ──────────────────────────────────────────────────
echo ""
echo "[ 3 ] JBoss EAP 8 pod (via EAP Operator)"
# Try multiple label selectors — EAP Operator uses different labels across versions
JBOSS_READY=""
for SELECTOR in "app.kubernetes.io/managed-by=eap-operator" "app=jboss-instance" "app.kubernetes.io/name=jboss-instance"; do
  JBOSS_READY=$(oc get pods -n "$NAMESPACE" -l "$SELECTOR" \
    --field-selector=status.phase=Running \
    -o jsonpath='{.items[*].metadata.name}' 2>/dev/null || true)
  [[ -n "$JBOSS_READY" ]] && break
done

if [[ -n "$JBOSS_READY" ]]; then
  pass "JBoss pod running: $JBOSS_READY"
else
  # Fallback 1: check any StatefulSet (EAP Operator creates StatefulSets)
  SS=$(oc get statefulset -n "$NAMESPACE" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || true)
  if [[ -n "$SS" ]]; then
    READY=$(oc get statefulset "$SS" -n "$NAMESPACE" \
      -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
    if [[ "$READY" -ge 1 ]]; then
      pass "JBoss StatefulSet '$SS' has $READY ready replica(s)"
    else
      # Show actual pod states for diagnosis
      echo "      Pod states in namespace:"
      oc get pods -n "$NAMESPACE" -o wide 2>/dev/null | sed 's/^/      /'
      fail "JBoss StatefulSet '$SS' has 0 ready replicas — check pod state above"
    fi
  else
    # Fallback 2: look for any pod with 'jboss' or 'instance' in its name
    JBOSS_POD=$(oc get pods -n "$NAMESPACE" \
      -o jsonpath='{.items[*].metadata.name}' 2>/dev/null | tr ' ' '\n' | grep -E 'jboss|instance' | head -1 || true)
    if [[ -n "$JBOSS_POD" ]]; then
      PHASE=$(oc get pod "$JBOSS_POD" -n "$NAMESPACE" -o jsonpath='{.status.phase}' 2>/dev/null || echo "Unknown")
      if [[ "$PHASE" == "Running" ]]; then
        pass "JBoss pod '$JBOSS_POD' is Running"
      else
        fail "JBoss pod '$JBOSS_POD' phase: $PHASE (expected Running)"
      fi
    else
      echo "      All pods in namespace:"
      oc get pods -n "$NAMESPACE" 2>/dev/null | sed 's/^/      /'
      fail "No JBoss pods found — check if WildFlyServer CR exists: oc get wildflyserver -n $NAMESPACE"
    fi
  fi
fi

# ── 4. AI Monitor deployment running ─────────────────────────────────────────
echo ""
echo "[ 4 ] AI Monitor deployment"
MONITOR_READY=$(oc get deployment "$MONITOR_DEPLOY" -n "$NAMESPACE" \
  -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo "0")
if [[ "$MONITOR_READY" -ge 1 ]]; then
  pass "Deployment '$MONITOR_DEPLOY' has $MONITOR_READY ready replica(s)"
else
  fail "Deployment '$MONITOR_DEPLOY' has no ready replicas"
fi

# ── 5. ConfigMap values ───────────────────────────────────────────────────────
echo ""
echo "[ 5 ] ConfigMap settings"
CM="jboss-ai-monitor-config"

HEALTH_PATH=$(oc get configmap "$CM" -n "$NAMESPACE" \
  -o jsonpath='{.data.HEALTH_CHECK_PATH}' 2>/dev/null || echo "MISSING")
if [[ "$HEALTH_PATH" == "/health" ]]; then
  pass "HEALTH_CHECK_PATH = $HEALTH_PATH"
else
  fail "HEALTH_CHECK_PATH = '$HEALTH_PATH' (expected /health)"
fi

JIRA_CM_URL=$(oc get configmap "$CM" -n "$NAMESPACE" \
  -o jsonpath='{.data.JIRA_URL}' 2>/dev/null || echo "MISSING")
if [[ "$JIRA_CM_URL" == "$JIRA_URL" ]]; then
  pass "JIRA_URL = $JIRA_CM_URL"
else
  fail "JIRA_URL = '$JIRA_CM_URL' (expected $JIRA_URL)"
fi

JIRA_KEY=$(oc get configmap "$CM" -n "$NAMESPACE" \
  -o jsonpath='{.data.JIRA_PROJECT_KEY}' 2>/dev/null || echo "MISSING")
if [[ "$JIRA_KEY" == "$JIRA_PROJECT" ]]; then
  pass "JIRA_PROJECT_KEY = $JIRA_KEY"
else
  fail "JIRA_PROJECT_KEY = '$JIRA_KEY' (expected $JIRA_PROJECT)"
fi

# ── 6. Secret exists ─────────────────────────────────────────────────────────
echo ""
echo "[ 6 ] Secret"
if oc get secret jboss-ai-monitor-secret -n "$NAMESPACE" &>/dev/null; then
  pass "Secret 'jboss-ai-monitor-secret' exists"
  # Check required keys
  for KEY in RHOAI_API_KEY JIRA_USER JIRA_TOKEN; do
    VAL=$(oc get secret jboss-ai-monitor-secret -n "$NAMESPACE" \
      -o jsonpath="{.data.$KEY}" 2>/dev/null | base64 -d 2>/dev/null || echo "")
    if [[ -n "$VAL" ]]; then
      pass "Secret key '$KEY' is set"
    else
      fail "Secret key '$KEY' is missing or empty"
    fi
  done
else
  fail "Secret 'jboss-ai-monitor-secret' not found — run: oc apply -f k8s/secret-template.yaml -n $NAMESPACE"
fi

# ── 7. JBoss HTTP endpoint ──────────────────────────────────────────────────
echo ""
echo "[ 7 ] JBoss HTTP endpoint (from inside cluster)"
# Read jboss namespace and health URL from the live configmap
JBOSS_NS=$(oc get configmap jboss-ai-monitor-config -n "$NAMESPACE" \
  -o jsonpath='{.data.JBOSS_NAMESPACE}' 2>/dev/null || echo "$NAMESPACE")
PROBE_URL=$(oc get configmap jboss-ai-monitor-config -n "$NAMESPACE" \
  -o jsonpath='{.data.HEALTH_CHECK_URLS}' 2>/dev/null | cut -d',' -f1 | tr -d ' ')

if [[ -z "$PROBE_URL" ]]; then
  # Fall back to auto-discovering the loadbalancer service in the jboss namespace
  JBOSS_SVC=$(oc get svc -n "$JBOSS_NS" \
    -o jsonpath='{.items[*].metadata.name}' 2>/dev/null | \
    tr ' ' '\n' | grep -i 'loadbalancer\|jboss\|wildfly\|eap' | head -1 || echo "")
  if [[ -n "$JBOSS_SVC" ]]; then
    JBOSS_PORT=$(oc get svc "$JBOSS_SVC" -n "$JBOSS_NS" \
      -o jsonpath='{.spec.ports[0].port}' 2>/dev/null || echo "8080")
    PROBE_URL="http://${JBOSS_SVC}.${JBOSS_NS}.svc.cluster.local:${JBOSS_PORT}/"
  fi
fi

if [[ -n "$PROBE_URL" ]]; then
  # Capture only the 3-digit HTTP status code — strip pod deletion messages
  HTTP_CODE=$(oc run health-check-test --rm -i --restart=Never \
    --image=curlimages/curl:latest -n "$JBOSS_NS" \
    --command -- curl -s -o /dev/null -w "%{http_code}" \
    "$PROBE_URL" 2>/dev/null | grep -oE '[0-9]{3}' | head -1 || echo "ERR")
  if [[ "$HTTP_CODE" == "200" ]]; then
    pass "HTTP $HTTP_CODE — $PROBE_URL"
  elif [[ "$HTTP_CODE" == "ERR" || -z "$HTTP_CODE" ]]; then
    warn "Could not run curl pod in namespace '$JBOSS_NS' — check manually"
  else
    fail "HTTP $HTTP_CODE — $PROBE_URL (expected 200)"
  fi
else
  warn "No JBoss service found in namespace '$JBOSS_NS' — skipping"
fi

# ── 8. AI Monitor logs ────────────────────────────────────────────────────────
echo ""
echo "[ 8 ] AI Monitor recent logs (last 30 lines)"
# Get the label selector directly from the deployment to avoid label mismatch
MONITOR_SELECTOR=$(oc get deployment "$MONITOR_DEPLOY" -n "$NAMESPACE" \
  -o jsonpath='{.spec.selector.matchLabels}' 2>/dev/null | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print(','.join(f'{k}={v}' for k,v in d.items()))" 2>/dev/null || echo "")

MONITOR_POD=""
if [[ -n "$MONITOR_SELECTOR" ]]; then
  MONITOR_POD=$(oc get pods -n "$NAMESPACE" -l "$MONITOR_SELECTOR" \
    --field-selector=status.phase=Running \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null || echo "")
fi
# Fallback: find by deployment name prefix
if [[ -z "$MONITOR_POD" ]]; then
  MONITOR_POD=$(oc get pods -n "$NAMESPACE" \
    -o jsonpath='{.items[*].metadata.name}' 2>/dev/null | tr ' ' '\n' | \
    grep "^${MONITOR_DEPLOY}-" | head -1 || echo "")
fi
if [[ -n "$MONITOR_POD" ]]; then
  echo "      Pod: $MONITOR_POD"
  echo "      ┌─────────────────────────────────────────────────"
  oc logs "$MONITOR_POD" -n "$NAMESPACE" --tail=30 2>/dev/null | sed 's/^/      │ /'
  echo "      └─────────────────────────────────────────────────"

  # Check for key log signals
  LOGS=$(oc logs "$MONITOR_POD" -n "$NAMESPACE" --tail=100 2>/dev/null)

  if echo "$LOGS" | grep -q "resolution generated\|Successfully created JIRA\|Resolution received"; then
    pass "Full AI→JIRA pipeline executed at least once"
  elif echo "$LOGS" | grep -q "Requesting resolution from RHOAI model"; then
    warn "RHOAI call in progress — JIRA ticket may not yet be created"
  elif echo "$LOGS" | grep -q "RHOAI API call failed\|Connection error\|authentication"; then
    fail "RHOAI API error detected — check RHOAI_API_URL, RHOAI_MODEL_NAME, and RHOAI_API_KEY in the secret"
  elif echo "$LOGS" | grep -q "Starting monitoring\|Monitor cycle"; then
    warn "Monitor is running but no issues detected yet (normal if JBoss is healthy)"
  fi

  if echo "$LOGS" | grep -qi "error\|exception\|traceback" | head -3; then
    warn "Errors/exceptions found in logs — review above output"
  fi
else
  fail "No running AI Monitor pod found"
fi

# ── 9. JIRA connectivity ──────────────────────────────────────────────────────
echo ""
echo "[ 9 ] JIRA connectivity"
JIRA_USER_VAL=$(oc get secret jboss-ai-monitor-secret -n "$NAMESPACE" \
  -o jsonpath='{.data.JIRA_USER}' 2>/dev/null | base64 -d 2>/dev/null || echo "")
JIRA_TOKEN_VAL=$(oc get secret jboss-ai-monitor-secret -n "$NAMESPACE" \
  -o jsonpath='{.data.JIRA_TOKEN}' 2>/dev/null | base64 -d 2>/dev/null || echo "")
if [[ -n "$JIRA_USER_VAL" && -n "$JIRA_TOKEN_VAL" ]]; then
  HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -u "${JIRA_USER_VAL}:${JIRA_TOKEN_VAL}" \
    "${JIRA_URL}/rest/api/3/project/${JIRA_PROJECT}" 2>/dev/null || echo "ERR")
  if [[ "$HTTP_CODE" == "200" ]]; then
    pass "JIRA API reachable — project '$JIRA_PROJECT' found at $JIRA_URL"
  elif [[ "$HTTP_CODE" == "401" ]]; then
    fail "JIRA auth failed (401) — check JIRA_USER and JIRA_TOKEN in secret"
  elif [[ "$HTTP_CODE" == "404" ]]; then
    fail "JIRA project '$JIRA_PROJECT' not found (404) — check JIRA_PROJECT_KEY"
  else
    fail "JIRA returned HTTP $HTTP_CODE"
  fi
else
  warn "JIRA credentials not readable from secret — skipping JIRA connectivity test"
fi

# ── 10. Check for created JIRA tickets ───────────────────────────────────────
echo ""
echo "[ 10 ] Recent JIRA tickets in project $JIRA_PROJECT"
if [[ -n "$JIRA_USER_VAL" && -n "$JIRA_TOKEN_VAL" ]]; then
  TICKETS=$(curl -s \
    -u "${JIRA_USER_VAL}:${JIRA_TOKEN_VAL}" \
    -H "Content-Type: application/json" \
    "${JIRA_URL}/rest/api/2/search?jql=project%3D${JIRA_PROJECT}%20ORDER%20BY%20created%20DESC&maxResults=5&fields=summary,status,created" \
    2>/dev/null | python3 -c "
import sys, json
data = json.load(sys.stdin)
issues = data.get('issues', [])
if not issues:
    print('  No tickets found yet')
else:
    for i in issues:
        key = i['key']
        summary = i['fields']['summary'][:70]
        status = i['fields']['status']['name']
        print(f'  {key}: [{status}] {summary}')
" 2>/dev/null || echo "  Could not parse JIRA response")
  echo "$TICKETS"
  if echo "$TICKETS" | grep -q "KAN-"; then
    pass "JIRA tickets exist in project KAN"
  else
    warn "No tickets yet — the monitor will create one on the next detected issue"
  fi
fi

# ── Summary ───────────────────────────────────────────────────────────────────
echo ""
echo "========================================================"
if [[ $FAILURES -eq 0 ]]; then
  echo -e "${GREEN}  All tests passed! Stack is healthy. ✅${NC}"
else
  echo -e "${RED}  $FAILURES test(s) failed — see ❌ items above.${NC}"
fi
echo "========================================================"
echo ""

exit $FAILURES
