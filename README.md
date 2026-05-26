# JBoss AI Monitor

An agentic AI application that continuously monitors a **JBoss/WildFly** instance running on **OpenShift**, automatically analyzes detected issues using an **RHOAI-hosted LLM** (any vLLM-compatible model configured via `RHOAI_MODEL_NAME`), and creates structured **JIRA tickets** with AI-generated root-cause analysis and resolution steps — all without human intervention.

---

## How It Works

```
OpenShift cluster A                   OpenShift cluster B (RHOAI)
(jboss-production namespace)          (my-first-model namespace)
┌─────────────────────────┐          ┌──────────────────────────────┐
│  jboss-instance-0       │          │  <RHOAI_MODEL_NAME> (vLLM)   │
│  (WildFly via Operator) │          │  InferenceService (RHOAI)    │
└─────────────────────────┘          └──────────────────────────────┘
         ▲                                         ▲
         │ watch                                   │ HTTPS /v1
         │                                         │
┌────────┴─────────────────────────────────────────┴───────────────┐
│  JBoss AI Monitor (jboss-monitoring namespace)                   │
│                                                                  │
│  ┌──────────┐  issues   ┌──────────┐  resolution  ┌───────────┐  │
│  │ 4 Monitor│──────────►│  Dedup   │─────────────►│   RHOAI   │  │
│  │ modules  │           └──────────┘              │   Agent   │  │
│  └──────────┘                                     └─────┬─────┘  │
│                                                         │        │
└─────────────────────────────────────────────────────────┼────────┘
                                                          │
                                                          ▼
                                               JIRA project KAN
                                               (auto-created tickets)
```

Every `CHECK_INTERVAL_SECONDS` (default: 60s) the monitor runs a full cycle across four detection layers. Any detected issue is sent to the RHOAI-hosted LLM for analysis. The structured response — including root cause, resolution steps, and prevention tips — is written directly into a JIRA ticket.

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
│   ├── main.py                  # MonitoringAgent — orchestrates all monitors, configurable interval loop
│   ├── config.py                # All config loaded from env vars with defaults
│   ├── models.py                # Issue, Resolution, JiraTicket dataclasses
│   ├── monitors/
│   │   ├── pod_monitor.py       # Kubernetes pod state detection
│   │   ├── alert_monitor.py     # AlertManager / Prometheus polling
│   │   ├── log_monitor.py       # Log error pattern matching
│   │   └── health_monitor.py    # HTTP health endpoint probing
│   ├── agent/
│   │   └── resolution_agent.py  # RHOAI LLM function-call integration
│   ├── jira/
│   │   └── jira_client.py       # JIRA REST API v3 ticket creation (ADF format)
│   └── utils/
│       └── dedup.py             # Sliding-window deduplication (default 2h)
├── k8s/
│   ├── namespace.yaml           # Creates jboss-monitoring namespace
│   ├── deployment.yaml          # OpenShift Deployment manifest
│   ├── configmap.yaml           # Non-sensitive configuration
│   ├── secret-template.yaml     # Credentials template (copy to secret.yaml, never commit filled)
│   ├── serviceaccount.yaml      # ServiceAccount + RBAC
│   └── jboss-operator/
│       ├── install.sh           # EAP Operator (OLM) + WildFlyServer installer
│       ├── 00-namespace.yaml
│       ├── 01-operatorgroup.yaml
│       ├── 02-subscription.yaml
│       ├── 03-wildflyserver.yaml  # WildFlyServer CR (quay.io/wildfly/wildfly:latest)
│       └── 04-wildfly-operator-direct.yaml  # Community WildFly Operator (no OLM)
├── Dockerfile                   # Multi-stage UBI9 Python image
├── requirements.txt
├── .env.example                 # Local dev environment template
└── test-stack.sh                # End-to-end smoke test
```

---

## Prerequisites

- Two OpenShift 4.x clusters (or one cluster for both workloads):
  - **Cluster A** — runs the JBoss/WildFly instance and the AI Monitor
  - **Cluster B** — runs RHOAI with a deployed vLLM-compatible model serving endpoint (e.g. llama-3.1-8b-instruct, granite-3.1-8b-instruct)
- `oc` CLI logged in as `kubeadmin`
- `docker` or `podman` CLI with access to your container registry (e.g. `quay.io`)
- Atlassian JIRA Cloud account + API token

---

## Deployment

### 1. Install WildFly via Operator

```bash
# Run the installer (handles namespace, operator, and WildFlyServer CR)
bash k8s/jboss-operator/install.sh
```

The installer creates the `jboss-production` namespace, installs the WildFly Operator, and deploys a WildFlyServer instance using `quay.io/wildfly/wildfly:latest`.

If OLM-based install fails, the community WildFly Operator can be installed directly:

```bash
oc apply -f k8s/jboss-operator/04-wildfly-operator-direct.yaml
oc apply -f k8s/jboss-operator/03-wildflyserver.yaml
```

### 2. Configure credentials

Copy the template, fill in real values, and apply:

```bash
# Create the jboss-monitoring namespace first
oc apply -f k8s/namespace.yaml

# Copy the template (never commit secret.yaml with real values)
cp k8s/secret-template.yaml k8s/secret.yaml

# Edit with your credentials
vi k8s/secret.yaml

oc apply -f k8s/secret.yaml -n jboss-monitoring
```

Required secret keys:

| Key | Value |
|---|---|
| `RHOAI_API_KEY` | Token from the **RHOAI cluster** — run `oc whoami -t` after logging into the RHOAI cluster |
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
RHOAI_API_URL: "https://<model-name>-<namespace>.apps.<rhoai-cluster>/v1"
RHOAI_MODEL_NAME: "<deployed-model-name>"     # As shown in RHOAI model server
DEDUP_WINDOW_MINUTES: "120"               # Suppress duplicate tickets for 2 hours
```

### 4. Build and push the image

```bash
docker build --platform linux/amd64 \
  -t quay.io/<your-username>/jboss-ai-monitor:1.0.0 .
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
  --serviceaccount=jboss-monitoring:jboss-ai-monitor \
  -n jboss-production
```

---

## Verifying the Deployment

```bash
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
Sleeping 30s until next cycle …
```

When an issue is detected:

```
Processing issue: [HIGH/health_failure] Health check failed …
Requesting resolution from RHOAI model …
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
| `JBOSS_INSTANCE_NAME` | ConfigMap | _(all pods)_ | Optional: watch only this WildFly CR name |
| `CHECK_INTERVAL_SECONDS` | ConfigMap | `60` | Monitoring cycle frequency |
| `HEALTH_CHECK_TIMEOUT` | ConfigMap | `10` | HTTP timeout for health probes (seconds) |
| `HEALTH_CHECK_URLS` | ConfigMap | _(auto-discover)_ | Comma-separated health URLs to probe |
| `HEALTH_CHECK_PATH` | ConfigMap | `/health/ready` | Path appended to auto-discovered service URLs |
| `LOG_TAIL_LINES` | ConfigMap | `300` | Number of recent log lines to fetch per pod per cycle |
| `LOG_ERROR_PATTERNS` | ConfigMap | `SEVERE,OutOfMemoryError,…` | Comma-separated regex patterns for log scanning |
| `ALERTMANAGER_URL` | ConfigMap | _(in-cluster default)_ | AlertManager endpoint for firing alerts |
| `PROMETHEUS_URL` | ConfigMap | _(in-cluster default)_ | Prometheus endpoint for active alert queries |
| `ALERT_NAME_FILTER` | ConfigMap | `WildFly\|JBoss\|EAP\|Helidon` | Regex to filter relevant alert names |
| `JIRA_URL` | ConfigMap | — | JIRA instance base URL |
| `JIRA_PROJECT_KEY` | ConfigMap | `OPS` | Target JIRA project |
| `JIRA_ISSUE_TYPE` | ConfigMap | `Task` | Issue type (must exist in your project) |
| `JIRA_LABELS` | ConfigMap | `jboss,openshift,automated` | Comma-separated labels applied to every ticket |
| `RHOAI_API_URL` | ConfigMap | — | RHOAI inference endpoint base URL on the RHOAI cluster (must end in `/v1`) |
| `RHOAI_MODEL_NAME` | ConfigMap | — | Deployed model name as shown in RHOAI |
| `RHOAI_MAX_TOKENS` | ConfigMap | `2048` | Max tokens per AI response |
| `DEDUP_WINDOW_MINUTES` | ConfigMap | `120` | Duplicate suppression window |
| `ENABLE_POD_MONITOR` | ConfigMap | `true` | Toggle pod crash detection |
| `ENABLE_ALERT_MONITOR` | ConfigMap | `true` | Toggle AlertManager polling |
| `ENABLE_LOG_MONITOR` | ConfigMap | `true` | Toggle log pattern scanning |
| `ENABLE_HEALTH_MONITOR` | ConfigMap | `true` | Toggle health endpoint probing |
| `LOG_LEVEL` | ConfigMap | `INFO` | Python logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`) |
| `RHOAI_API_KEY` | Secret | — | Token from the RHOAI cluster — use `oc whoami -t` for short-lived or create a `kubernetes.io/service-account-token` Secret for non-expiring token |
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

**Multi-cluster setup**: The AI Monitor and JBoss instance run on one OpenShift cluster while the RHOAI model serving endpoint runs on a separate RHOAI cluster. The monitor reaches the model over HTTPS using the external route URL. The `RHOAI_API_KEY` must be a token from the RHOAI cluster, obtained by running `oc whoami -t` after logging into that cluster.

**AI function-calling**: The `resolution_agent.py` uses the OpenAI-compatible `tools` API with `tool_choice={"type":"function","function":{"name":"provide_resolution"}}` to force the RHOAI-hosted model to always respond via a structured JSON function call rather than free-form text. This guarantees a parseable `Resolution` object with consistent fields every time. HTTP/2 is disabled (`http2=False`) for compatibility with OpenShift passthrough routes. Model output is post-processed by `_clean_list()` and `_clean_text()` to strip common LLM artifacts (escaped unicode, embedded numbering, bare URLs, leaked field names).

**Switching models**: Only `RHOAI_API_URL`, `RHOAI_MODEL_NAME`, and `RHOAI_API_KEY` need updating to point to a different model or cluster. The model must support OpenAI-compatible function calling (vLLM serves this on `/v1/chat/completions`).

**Deduplication**: Issues are fingerprinted by MD5 hash of `(issue_type + title + severity)`. Within the dedup window, repeat occurrences are detected and logged but no new JIRA ticket is created.

**ADF descriptions**: JIRA Cloud REST API v3 requires Atlassian Document Format for rich text. The `jira_client.py` builds ADF nodes (headings, paragraphs, code blocks) to produce well-structured tickets with the AI analysis inline.

**OpenShift SCC compliance**: The deployment uses `runAsNonRoot: true` only — no hardcoded UIDs — so it passes the `restricted-v2` Security Context Constraint on OpenShift 4.x.

**Health endpoint**: The WildFly community image exposes port 8080 for application traffic. Use `/health` for MicroProfile Health status (UP/DOWN/LIVE) if your application includes the MicroProfile Health extension.

---

## Image

```
quay.io/nnsaraiya/jboss-ai-monitor/jboss-ai-monitor:1.0.1
```

Built from `registry.access.redhat.com/ubi9/python-311` (UBI9), multi-stage. Public registry — no pull secret needed for the monitor image itself.

---

## License

Apache 2.0
