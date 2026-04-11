"""
health_monitor.py — Probes JBoss MicroProfile Health endpoints.

Two strategies:
  1. Explicit URLs from HEALTH_CHECK_URLS env var.
  2. Auto-discovery: list Services in the namespace, find ones with the
     JBoss label selector, build URLs from their ClusterIP + target port,
     and probe the configured health path (default: /health/ready).

Any non-2xx response or connection timeout is reported as a HealthFailure Issue.
"""

import logging
from typing import List, Optional, Tuple

import requests

from kubernetes import client as k8s_client

from src.config import Config
from src.models import Issue, IssueSeverity, IssueType

logger = logging.getLogger(__name__)


class HealthMonitor:
    def __init__(self, config: Config, v1: k8s_client.CoreV1Api) -> None:
        self._cfg = config
        self._v1 = v1

    def check(self) -> List[Issue]:
        """Probe all health endpoints and return Issues for failures."""
        issues: List[Issue] = []
        urls = self._resolve_urls()

        if not urls:
            logger.debug("HealthMonitor: no health URLs configured or discovered — skipping")
            return issues

        for url, pod_name, container_name in urls:
            issue = self._probe(url, pod_name, container_name)
            if issue:
                issues.append(issue)

        logger.info("HealthMonitor: probed %d endpoint(s), found %d issue(s)", len(urls), len(issues))
        return issues

    # ── Internal helpers ───────────────────────────────────────────────────

    def _resolve_urls(self) -> List[Tuple[str, Optional[str], Optional[str]]]:
        """
        Returns list of (url, pod_name, container_name) tuples to probe.
        Falls back to auto-discovery if no explicit URLs configured.
        """
        if self._cfg.health_check_urls:
            return [(url, None, None) for url in self._cfg.health_check_urls]

        # Auto-discover from Services
        return self._discover_from_services()

    def _discover_from_services(self) -> List[Tuple[str, Optional[str], Optional[str]]]:
        """
        Finds Services in the namespace matching the JBoss label selector,
        then constructs health endpoint URLs.
        """
        results: List[Tuple[str, Optional[str], Optional[str]]] = []
        try:
            svcs = self._v1.list_namespaced_service(
                namespace=self._cfg.namespace,
                label_selector=self._cfg.jboss_label_selector,
            )
        except Exception as exc:
            logger.warning("HealthMonitor: could not list services: %s", exc)
            return results

        for svc in svcs.items:
            cluster_ip = svc.spec.cluster_ip
            if not cluster_ip or cluster_ip == "None":
                continue
            for port_obj in svc.spec.ports or []:
                port = port_obj.port
                # Prefer HTTP/management ports (8080, 9990, 8443)
                if port in (8080, 9990, 8443, 80, 443):
                    scheme = "https" if port in (8443, 443) else "http"
                    url = f"{scheme}://{cluster_ip}:{port}{self._cfg.health_check_path}"
                    results.append((url, svc.metadata.name, None))
                    break  # one URL per service is enough

        return results

    def _probe(
        self,
        url: str,
        pod_name: Optional[str],
        container_name: Optional[str],
    ) -> Optional[Issue]:
        """
        Probe a single URL. Returns an Issue on failure, None on success.
        """
        try:
            resp = requests.get(
                url,
                timeout=self._cfg.health_check_timeout,
                verify=False,  # In-cluster certs may be self-signed
                allow_redirects=True,
            )
            if resp.status_code < 400:
                logger.debug("HealthMonitor: %s -> HTTP %s OK", url, resp.status_code)
                return None

            # Non-2xx / non-3xx → health check failed
            body_snippet = resp.text[:500] if resp.text else "(empty body)"
            return Issue(
                issue_type=IssueType.HEALTH_FAILURE,
                severity=IssueSeverity.HIGH,
                title=f"Health check failed (HTTP {resp.status_code}): {url}",
                description=(
                    f"JBoss health endpoint returned HTTP {resp.status_code}.\n"
                    f"URL: {url}\n"
                    f"Response body (first 500 chars): {body_snippet}"
                ),
                raw_data={
                    "url": url,
                    "http_status": resp.status_code,
                    "response_body_snippet": body_snippet,
                },
                namespace=self._cfg.namespace,
                pod_name=pod_name,
                container_name=container_name,
            )

        except requests.exceptions.ConnectTimeout:
            return Issue(
                issue_type=IssueType.HEALTH_FAILURE,
                severity=IssueSeverity.HIGH,
                title=f"Health check timeout: {url}",
                description=(
                    f"JBoss health endpoint did not respond within "
                    f"{self._cfg.health_check_timeout}s.\n"
                    f"URL: {url}\n"
                    f"This may indicate the JBoss process is hung or the pod is overloaded."
                ),
                raw_data={
                    "url": url,
                    "error": "ConnectTimeout",
                    "timeout_seconds": self._cfg.health_check_timeout,
                },
                namespace=self._cfg.namespace,
                pod_name=pod_name,
                container_name=container_name,
            )

        except requests.exceptions.ConnectionError as exc:
            return Issue(
                issue_type=IssueType.HEALTH_FAILURE,
                severity=IssueSeverity.HIGH,
                title=f"Health check connection error: {url}",
                description=(
                    f"Cannot connect to JBoss health endpoint.\n"
                    f"URL: {url}\n"
                    f"Error: {exc}"
                ),
                raw_data={
                    "url": url,
                    "error": str(exc),
                },
                namespace=self._cfg.namespace,
                pod_name=pod_name,
                container_name=container_name,
            )

        except Exception as exc:
            logger.warning("HealthMonitor: unexpected error probing %s: %s", url, exc)
            return None
