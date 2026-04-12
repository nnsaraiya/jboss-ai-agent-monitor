# JBoss AI Monitor

An agentic AI application that continuously monitors a **JBoss EAP 8** instance running on **OpenShift** (CRC), automatically analyzes detected issues using **Claude AI**, and creates structured **JIRA tickets** with AI-generated root-cause analysis and resolution steps — all without human intervention.

---

## How It Works

```
OpenShift (jboss-production)          jboss-monitoring namespace
┌─────────────────────────┐          ┌──────────────────────────────────────┐
│  jboss-instance-0       │          │  JBoss AI Monitor (Python)           │
│  jboss-instance-1       │◄─────────│                                      │
│  (EAP 8 via Operator)   │  watch   │  ┌──────────┐  ┌──────────────────┐ │
└─────────────────────────┘          │  │ 4 Monitor│  │  Claude AI       │ │
                                     │  │ modules  │─►│  claude-opus-4-6 │ │
                                     │  └──────────┘  └────────┬─────────┘ │
                                     │                         │            │
                                     └─────────────────────────┼────────────┘
                                                               │
                                                               ▼
                                                    JIRA project KAN
                                                    (auto-created tickets)
```

Every 60 seconds the monitor runs a full cycle across four detection layers. Any detected issue is sent to Claude AI for analysis. The structured response — including root cause, resolution steps, and prevention tips — is written directly into a JIRA ticket.

---

## Monitors

| Monitor | What it detects |
|---|---|
| **Pod Monitor** | OOMKilled (exit 137), CrashLoopBackOff, Error, ImagePullBackOff, restart spikes |
| **Alert Monitor** | AlertManager / Prometheus firing alerts matching `WildFly\|JBoss\|EAP\|Helidon` |
| **Log Monitor** | Error patterns in pod logs: `OutOfMemoryError`, `WFLYCTL.*ERROR`, `DeploymentException`, `NullPointerException`, deadlocks, and more |
| **Health Monitor** | HTTP status on the JBoss service endpoint — detects server-down or unhealthy responses |

---

## Project Structure

```
jboss-ai-monitor/
├── src/
│   ├── main.py                  # MonitoringAgent — orchestrates all monitors, 60s loop
│   ├── config.py                # All config loaded from env vars with defaults
│   ├── models.py                # Issue, Resolution, JiraTicket dataclasses
│   ├── monitors/
│   │   ├── pod_monitor.py       # Kubernetes pod state detection
│   │   ├── alert_monitor.py     # AlertManager / Prometheus polling
│   │   ├── log_monitor.py       # Log error pattern matching
│   │   └── health_monitor.py    # HTTP health endpoint probing
│   ├── agent/
│   │   └── resolution_agent.py  # Claude AI tool-call integration
│   ├── jira/
│   │   └── jira_client.py       # JIRA REST API v3 ticket creation (ADF format)
│   └── utils/
│       └── dedup.py             # Sliding-window deduplication (default 2h)
├── k8s/
│   ├── deployment.yaml          # OpenShift Deployment manifest
│   ├── configmap.yaml           # Non-sensitive configuration
│   ├── secret-template.yaml     # Credentials template (do not commit with real values)
│   ├── serviceaccount.yaml      # ServiceAccount + RBAC
│   └── jboss-operator/
│       ├── install.sh           # 6-step EAP Operator + WildFlyServer installer
│       ├── 00-namespace.yaml
│       ├── 01-operatorgroup.yaml
│       ├── 02-subscription.yaml # EAP Operator 3.2.13 from redhat-operators
│       └── 03-wildflyserver.yaml
├── Dockerfile                   # Multi-stage UBI9 Python image
├── requirements.txt
└── test-stack.sh                # 10-point end-to-end smoke test
```

---

## Prerequisites

- OpenShift CRC (`crc start`) or an OpenShift 4.x cluster
- `oc` CLI logged in as `kubeadmin`
- `docker` CLI with access to `quay.io` (or your own registry)
- Red Hat account with `registry.redhat.io` access (for EAP 8 image)
- Anthropic API key with credits — [console.anthropic.com](https://console.anthropic.com/settings/billing)
- Atlassian JIRA Cloud account + API token

---

## Deployment

### 1. Install JBoss EAP 8 via Operator

```bash
# Login to registry.redhat.io with your Red Hat account first
docker login registry.redhat.io -u <your-rh-email>

# Create pull secret from your docker config
oc create secret generic rh-registry-pull-secret \
  --from-file=.dockerconfigjson=$HOME/.docker/config.json \
  --type=kubernetes.io/dockerconfigjson \
  -n jboss-production

# Run the installer
bash k8s/jboss-operator/install.sh
```

The installer creates the `jboss-production` namespace, installs the Red Hat EAP Operator 3.2.13 via OLM, and deploys a 2-replica WildFlyServer instance.

### 2. Configure credentials

Copy `k8s/secret-template.yaml`, fill in your real values, and apply:

```bash
# Edit the file — never commit real credentials
vi k8s/secret-template.yaml

oc apply -f k8s/secret-template.yaml -n jboss-monitoring
```

Required secret keys:

| Key | Value |
|---|---|
| `ANTHROPIC_API_KEY` | From [console.anthropic.com/settings/api-keys](https://console.anthropic.com/settings/api-keys) |
| `JIRA_USER` | Your Atlassian account email |
| `JIRA_TOKEN` | From [id.atlassian.com/manage-profile/security/api-tokens](https://id.atlassian.com/manage-profile/security/api-tokens) |

### 3. Review configuration

Key settings in `k8s/configmap.yaml`:

```yaml
JBOSS_NAMESPACE: "jboss-production"       # Namespace where JBoss pods run
HEALTH_CHECK_URLS: "http://jboss-instance-loadbalancer.jboss-production.svc.cluster.local:8080/"
JIRA_URL: "https://<your-org>.atlassian.net"
JIRA_PROJECT_KEY: "KAN"                   # Your JIRA project key
JIRA_ISSUE_TYPE: "Task"                   # Must match a valid type in your project
CLAUDE_MODEL: "claude-opus-4-6"
DEDUP_WINDOW_MINUTES: "120"               # Suppress duplicate tickets for 2 hours
```

### 4. Build and push the image

```bash
docker build -t quay.io/<your-username>/jboss-ai-monitor:1.0.0 .
docker push quay.io/<your-username>/jboss-ai-monitor:1.0.0
```

Update `k8s/deployment.yaml` with your image path, then:

```bash
oc apply -f k8s/configmap.yaml -n jboss-monitoring
oc apply -f k8s/serviceaccount.yaml -n jboss-monitoring
oc apply -f k8s/deployment.yaml -n jboss-monitoring
```

### 5. Grant cross-namespace read access

The monitor pod runs in `jboss-monitoring` but watches pods in `jboss-production`:

```bash
oc create role jboss-monitor-reader \
  --verb=get,list,watch \
  --resource=pods,pods/log,services,endpoints \
  -n jboss-production

oc create rolebinding jboss-monitor-reader-binding \
  --role=jboss-monitor-reader \
  --serviceaccount=jboss-monitoring:jboss-ai-monitor-sa \
  -n jboss-production
```

---

## Verifying the Deployment

```bash
# Run the full 10-point smoke test
bash test-stack.sh

# Tail live logs
oc logs -f deployment/jboss-ai-monitor -n jboss-monitoring
```

A healthy cycle looks like:

```
── Starting monitoring cycle ──────────────────────────
PodMonitor: 0 issue(s)
AlertMonitor: 0 issue(s)
LogMonitor: 0 issue(s)
HealthMonitor: probed 1 endpoint(s), found 0 issue(s)
No issues detected this cycle.
Sleeping 60s until next cycle …
```

When an issue is detected:

```
Processing issue: [HIGH/health_failure] Health check failed …
Requesting resolution from Claude AI …
Resolution received (confidence: high, 8 steps)
JiraClient: created ticket KAN-6 — https://<org>.atlassian.net/browse/KAN-6
```

---

## Environment Variables Reference

All variables are loaded from the ConfigMap and Secret. Every variable has a default so the app starts without requiring all of them.

| Variable | Source | Default | Description |
|---|---|---|---|
| `JBOSS_NAMESPACE` | ConfigMap | `default` | Namespace where JBoss pods run |
| `JBOSS_LABEL_SELECTOR` | ConfigMap | `app.kubernetes.io/managed-by=wildfly-operator` | Label selector for JBoss pods |
| `CHECK_INTERVAL_SECONDS` | ConfigMap | `60` | Monitoring cycle frequency |
| `HEALTH_CHECK_URLS` | ConfigMap | _(auto-discover)_ | Comma-separated health URLs |
| `HEALTH_CHECK_PATH` | ConfigMap | `/health` | Path for auto-discovered health checks |
| `JIRA_URL` | ConfigMap | — | JIRA instance base URL |
| `JIRA_PROJECT_KEY` | ConfigMap | `OPS` | Target JIRA project |
| `JIRA_ISSUE_TYPE` | ConfigMap | `Task` | Issue type (must exist in your project) |
| `CLAUDE_MODEL` | ConfigMap | `claude-opus-4-6` | Anthropic model to use |
| `CLAUDE_MAX_TOKENS` | ConfigMap | `2048` | Max tokens per AI response |
| `DEDUP_WINDOW_MINUTES` | ConfigMap | `120` | Duplicate suppression window |
| `ENABLE_POD_MONITOR` | ConfigMap | `true` | Toggle pod crash detection |
| `ENABLE_ALERT_MONITOR` | ConfigMap | `true` | Toggle AlertManager polling |
| `ENABLE_LOG_MONITOR` | ConfigMap | `true` | Toggle log pattern scanning |
| `ENABLE_HEALTH_MONITOR` | ConfigMap | `true` | Toggle health endpoint probing |
| `ANTHROPIC_API_KEY` | Secret | — | Anthropic API key |
| `JIRA_USER` | Secret | — | JIRA account email |
| `JIRA_TOKEN` | Secret | — | JIRA API token |

---

## Operational Commands

```bash
# View live logs
oc logs -f deployment/jboss-ai-monitor -n jboss-monitoring

# Restart after config change
oc rollout restart deployment/jboss-ai-monitor -n jboss-monitoring

# Apply updated configmap
oc apply -f k8s/configmap.yaml -n jboss-monitoring

# Patch a single config value
oc patch configmap jboss-ai-monitor-config -n jboss-monitoring \
  --type=merge -p '{"data":{"CHECK_INTERVAL_SECONDS":"30"}}'

# Check JBoss pods
oc get pods -n jboss-production

# View JBoss logs
oc logs jboss-instance-0 -n jboss-production

# Scale monitor down (maintenance)
oc scale deployment/jboss-ai-monitor --replicas=0 -n jboss-monitoring
```

---

## Architecture Notes

**AI tool-calling**: The `resolution_agent.py` uses `tool_choice={"type":"any"}` to force Claude to always respond via a structured JSON tool call rather than free-form text. This guarantees a parseable `Resolution` object with consistent fields every time.

**Deduplication**: Issues are fingerprinted by MD5 hash of `(issue_type + title + severity)`. Within the dedup window, repeat occurrences are detected and logged but no new JIRA ticket is created.

**ADF descriptions**: JIRA Cloud REST API v3 requires Atlassian Document Format for rich text. The `jira_client.py` builds ADF nodes (headings, paragraphs, code blocks) to produce well-structured tickets with the AI analysis inline.

**OpenShift SCC compliance**: The deployment uses `runAsNonRoot: true` only — no hardcoded UIDs — so it passes the `restricted-v2` Security Context Constraint on OpenShift CRC.

**Health endpoint**: The EAP 8 runtime image (`eap8-openjdk17-runtime-openshift-rhel8`) does not expose the WildFly management interface (port 9990) on the pod network. Use port 8080 for basic liveness checking, or deploy an application with MicroProfile Health for full UP/DOWN/LIVE status at `/health`.

---

## Image

```
quay.io/nnsaraiya/jboss-ai-monitor/jboss-ai-monitor:1.0.0
```

Built from `registry.ubi.io/ubi9/python-311` (UBI9), multi-stage. Public registry — no pull secret needed for the monitor image itself.

---

## License

Apache 2.0
