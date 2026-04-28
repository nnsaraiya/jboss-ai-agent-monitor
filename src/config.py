"""
config.py — Loads all runtime configuration from environment variables.
Every setting has a sensible default so the agent can start with minimal config
and be tuned via ConfigMap/Secret in OpenShift.
"""

import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class Config:
    # ── OpenShift / Kubernetes ────────────────────────────────────────────────
    namespace: str = os.environ.get("JBOSS_NAMESPACE", "default")
    # WildFly/JBoss CR name — leave blank to watch ALL pods in the namespace
    jboss_instance_name: str = os.environ.get("JBOSS_INSTANCE_NAME", "")
    # Label selector that identifies JBoss/EAP pods managed by the operator
    jboss_label_selector: str = os.environ.get(
        "JBOSS_LABEL_SELECTOR",
        "app.kubernetes.io/managed-by=wildfly-operator",
    )

    # ── Polling intervals ─────────────────────────────────────────────────────
    check_interval_seconds: int = int(os.environ.get("CHECK_INTERVAL_SECONDS", "60"))
    health_check_timeout: int = int(os.environ.get("HEALTH_CHECK_TIMEOUT", "10"))

    # ── Health endpoint monitoring ────────────────────────────────────────────
    # Comma-separated list of health URLs to probe; can also be auto-discovered
    health_check_urls: List[str] = field(
        default_factory=lambda: [
            u.strip()
            for u in os.environ.get("HEALTH_CHECK_URLS", "").split(",")
            if u.strip()
        ]
    )
    # MicroProfile Health path (WildFly Operator exposes this by default)
    health_check_path: str = os.environ.get("HEALTH_CHECK_PATH", "/health/ready")

    # ── Log monitoring ────────────────────────────────────────────────────────
    log_error_patterns: List[str] = field(
        default_factory=lambda: [
            p.strip()
            for p in os.environ.get(
                "LOG_ERROR_PATTERNS",
                (
                    "SEVERE,"
                    "OutOfMemoryError,"
                    "java.lang.OutOfMemoryError,"
                    "DeploymentException,"
                    "WFLYCTL.*ERROR,"
                    "Caused by:,"
                    "StackOverflowError,"
                    "NullPointerException,"
                    "ClassNotFoundException,"
                    "NoClassDefFoundError,"
                    "ConnectException,"
                    "SocketTimeoutException,"
                    "Deadlock detected,"
                    "WFLYEJB.*timeout,"
                    "MSC000001"
                ),
            ).split(",")
            if p.strip()
        ]
    )
    # How many recent log lines to fetch per pod per cycle
    log_tail_lines: int = int(os.environ.get("LOG_TAIL_LINES", "300"))

    # ── Prometheus / AlertManager ─────────────────────────────────────────────
    # In-cluster URL for the OpenShift monitoring AlertManager
    alertmanager_url: str = os.environ.get(
        "ALERTMANAGER_URL",
        "http://alertmanager-main.openshift-monitoring.svc.cluster.local:9093",
    )
    # Prometheus query URL (used to pull active alerts)
    prometheus_url: str = os.environ.get(
        "PROMETHEUS_URL",
        "http://prometheus-k8s.openshift-monitoring.svc.cluster.local:9090",
    )
    # PromQL filter — matches alert labels that belong to JBoss/EAP/WildFly
    alert_name_filter: str = os.environ.get(
        "ALERT_NAME_FILTER",
        "WildFly|JBoss|EAP|Helidon",
    )

    # ── JIRA ──────────────────────────────────────────────────────────────────
    jira_url: str = os.environ.get("JIRA_URL", "")
    jira_user: str = os.environ.get("JIRA_USER", "")
    jira_token: str = os.environ.get("JIRA_TOKEN", "")
    jira_project_key: str = os.environ.get("JIRA_PROJECT_KEY", "OPS")
    jira_issue_type: str = os.environ.get("JIRA_ISSUE_TYPE", "Task")
    jira_labels: List[str] = field(
        default_factory=lambda: [
            lbl.strip()
            for lbl in os.environ.get("JIRA_LABELS", "jboss,openshift,automated").split(",")
            if lbl.strip()
        ]
    )

    # ── RHOAI (Red Hat OpenShift AI) ──────────────────────────────────────────
    # Base URL of the RHOAI model-serving inference endpoint (must end in /v1)
    # e.g. https://llama-3-8b-instruct-predictor.apps.your-cluster.example.com/v1
    rhoai_api_url: str = os.environ.get("RHOAI_API_URL", "")
    rhoai_api_key: str = os.environ.get("RHOAI_API_KEY", "")
    rhoai_model_name: str = os.environ.get("RHOAI_MODEL_NAME", "")
    rhoai_max_tokens: int = int(os.environ.get("RHOAI_MAX_TOKENS", "2048"))

    # ── Deduplication ─────────────────────────────────────────────────────────
    # Don't re-open a JIRA for the same fingerprint within this window
    dedup_window_minutes: int = int(os.environ.get("DEDUP_WINDOW_MINUTES", "120"))

    # ── Feature flags ─────────────────────────────────────────────────────────
    enable_pod_monitor: bool = os.environ.get("ENABLE_POD_MONITOR", "true").lower() == "true"
    enable_alert_monitor: bool = os.environ.get("ENABLE_ALERT_MONITOR", "true").lower() == "true"
    enable_log_monitor: bool = os.environ.get("ENABLE_LOG_MONITOR", "true").lower() == "true"
    enable_health_monitor: bool = os.environ.get("ENABLE_HEALTH_MONITOR", "true").lower() == "true"

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = os.environ.get("LOG_LEVEL", "INFO")


def load_config() -> Config:
    return Config()
