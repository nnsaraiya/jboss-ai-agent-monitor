"""
alert_monitor.py — Polls Prometheus AlertManager for firing alerts
related to JBoss / WildFly / EAP instances in OpenShift.

The agent queries the AlertManager API endpoint:
  GET /api/v2/alerts?filter=<label_filter>

It also falls back to querying Prometheus directly via the
ALERTS{} metric if AlertManager is unavailable.
"""

import logging
import re
from typing import Any, Dict, List

import requests

from src.config import Config
from src.models import Issue, IssueSeverity, IssueType

logger = logging.getLogger(__name__)

# Map Prometheus severity labels to our IssueSeverity
_SEVERITY_MAP = {
    "critical": IssueSeverity.CRITICAL,
    "high": IssueSeverity.HIGH,
    "warning": IssueSeverity.MEDIUM,
    "info": IssueSeverity.LOW,
}


def _map_severity(labels: Dict[str, str]) -> IssueSeverity:
    raw = labels.get("severity", "warning").lower()
    return _SEVERITY_MAP.get(raw, IssueSeverity.MEDIUM)


class AlertMonitor:
    def __init__(self, config: Config) -> None:
        self._cfg = config
        self._name_re = re.compile(config.alert_name_filter, re.IGNORECASE)

    def check(self) -> List[Issue]:
        """Return Issues for each currently firing alert matching the filter."""
        issues: List[Issue] = []

        # ── Try AlertManager first ─────────────────────────────────────────
        alerts = self._fetch_alertmanager_alerts()

        # ── Fall back to Prometheus ALERTS{} metric ────────────────────────
        if alerts is None:
            alerts = self._fetch_prometheus_alerts()

        if alerts is None:
            logger.warning("AlertMonitor: could not reach AlertManager or Prometheus")
            return issues

        for alert in alerts:
            labels: Dict[str, str] = alert.get("labels", {})
            annotations: Dict[str, str] = alert.get("annotations", {})
            alert_name = labels.get("alertname", "UnknownAlert")

            # Filter by name pattern
            if not self._name_re.search(alert_name):
                # Also check namespace label
                ns = labels.get("namespace", "")
                if ns != self._cfg.namespace:
                    continue

            summary = annotations.get("summary", alert_name)
            description = annotations.get("description", annotations.get("message", ""))
            pod_name = labels.get("pod", labels.get("pod_name", None))

            issues.append(
                Issue(
                    issue_type=IssueType.ALERT_FIRING,
                    severity=_map_severity(labels),
                    title=f"Alert firing: {alert_name}",
                    description=(
                        f"Prometheus alert '{alert_name}' is firing.\n"
                        f"Summary: {summary}\n"
                        f"Details: {description}"
                    ),
                    raw_data={
                        "alert_name": alert_name,
                        "labels": labels,
                        "annotations": annotations,
                        "state": alert.get("status", {}).get("state", "firing"),
                    },
                    namespace=labels.get("namespace", self._cfg.namespace),
                    pod_name=pod_name,
                )
            )

        logger.info("AlertMonitor: found %d firing alert(s)", len(issues))
        return issues

    # ── Internal helpers ───────────────────────────────────────────────────

    def _fetch_alertmanager_alerts(self) -> List[Dict[str, Any]] | None:
        url = f"{self._cfg.alertmanager_url}/api/v2/alerts"
        try:
            resp = requests.get(
                url,
                params={"filter": 'state="firing"'},
                timeout=10,
                headers=self._bearer_headers(),
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.debug("AlertManager fetch failed: %s", exc)
            return None

    def _fetch_prometheus_alerts(self) -> List[Dict[str, Any]] | None:
        """
        Query Prometheus for the ALERTS metric with state='firing'.
        Returns a synthetic list shaped like AlertManager responses.
        """
        url = f"{self._cfg.prometheus_url}/api/v1/query"
        try:
            resp = requests.get(
                url,
                params={"query": "ALERTS{alertstate='firing'}"},
                timeout=10,
                headers=self._bearer_headers(),
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("data", {}).get("result", [])
            # Convert Prometheus result format to AlertManager-like dicts
            return [
                {
                    "labels": r["metric"],
                    "annotations": {},
                    "status": {"state": "firing"},
                }
                for r in results
            ]
        except Exception as exc:
            logger.debug("Prometheus alert fetch failed: %s", exc)
            return None

    @staticmethod
    def _bearer_headers() -> Dict[str, str]:
        """
        When running in-cluster, read the ServiceAccount token for
        authenticating with the OpenShift monitoring stack.
        """
        try:
            with open("/var/run/secrets/kubernetes.io/serviceaccount/token") as f:
                token = f.read().strip()
            return {"Authorization": f"Bearer {token}"}
        except OSError:
            return {}
