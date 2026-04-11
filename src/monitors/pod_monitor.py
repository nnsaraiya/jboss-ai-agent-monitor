"""
pod_monitor.py — Watches OpenShift/Kubernetes pod state for JBoss pods.

Detects:
  • CrashLoopBackOff
  • OOMKilled (container exit code 137)
  • Error / ImagePullBackOff / CreateContainerError
  • Pod restart count spikes
"""

import logging
from typing import List, Optional

from kubernetes import client as k8s_client

from src.config import Config
from src.models import Issue, IssueSeverity, IssueType

logger = logging.getLogger(__name__)

# Number of restarts before we consider it a "crash loop" even without the
# CrashLoopBackOff status (some operators restart pods silently).
RESTART_THRESHOLD = 5


class PodMonitor:
    def __init__(self, config: Config, v1: k8s_client.CoreV1Api) -> None:
        self._cfg = config
        self._v1 = v1
        # Track last-seen restart counts to detect spikes between cycles
        self._last_restart_counts: dict = {}

    def check(self) -> List[Issue]:
        """Return a list of Issues detected in this monitoring cycle."""
        issues: List[Issue] = []
        try:
            pods = self._v1.list_namespaced_pod(
                namespace=self._cfg.namespace,
                label_selector=self._cfg.jboss_label_selector,
            )
        except Exception as exc:
            logger.error("PodMonitor: failed to list pods: %s", exc)
            return issues

        for pod in pods.items:
            pod_name: str = pod.metadata.name
            node_name: Optional[str] = pod.spec.node_name

            # ── Check container statuses ───────────────────────────────────
            if not pod.status or not pod.status.container_statuses:
                continue

            for cs in pod.status.container_statuses:
                container_name = cs.name
                restart_count = cs.restart_count or 0

                # ── OOMKilled ──────────────────────────────────────────────
                if cs.last_state and cs.last_state.terminated:
                    term = cs.last_state.terminated
                    if term.exit_code == 137 or (term.reason and "OOMKilled" in term.reason):
                        issues.append(
                            Issue(
                                issue_type=IssueType.OOM_KILLED,
                                severity=IssueSeverity.CRITICAL,
                                title=f"OOMKilled: {pod_name}/{container_name}",
                                description=(
                                    f"Container '{container_name}' in pod '{pod_name}' "
                                    f"(namespace: {self._cfg.namespace}) was OOMKilled "
                                    f"(exit code 137). Restart count: {restart_count}. "
                                    f"This indicates the JVM heap or native memory exceeded "
                                    f"the container memory limit."
                                ),
                                raw_data={
                                    "exit_code": term.exit_code,
                                    "reason": term.reason,
                                    "finished_at": str(term.finished_at),
                                    "restart_count": restart_count,
                                    "pod_phase": pod.status.phase,
                                },
                                namespace=self._cfg.namespace,
                                pod_name=pod_name,
                                container_name=container_name,
                                node_name=node_name,
                            )
                        )

                # ── CrashLoopBackOff ───────────────────────────────────────
                if cs.state and cs.state.waiting:
                    reason = cs.state.waiting.reason or ""
                    if reason == "CrashLoopBackOff":
                        issues.append(
                            Issue(
                                issue_type=IssueType.CRASH_LOOP,
                                severity=IssueSeverity.CRITICAL,
                                title=f"CrashLoopBackOff: {pod_name}/{container_name}",
                                description=(
                                    f"Container '{container_name}' in pod '{pod_name}' "
                                    f"is in CrashLoopBackOff. "
                                    f"Restart count: {restart_count}. "
                                    f"Message: {cs.state.waiting.message or 'N/A'}."
                                ),
                                raw_data={
                                    "reason": reason,
                                    "message": cs.state.waiting.message,
                                    "restart_count": restart_count,
                                    "pod_phase": pod.status.phase,
                                },
                                namespace=self._cfg.namespace,
                                pod_name=pod_name,
                                container_name=container_name,
                                node_name=node_name,
                            )
                        )
                    elif reason in (
                        "Error",
                        "CreateContainerError",
                        "CreateContainerConfigError",
                        "ImagePullBackOff",
                        "ErrImagePull",
                    ):
                        issues.append(
                            Issue(
                                issue_type=IssueType.POD_CRASH,
                                severity=IssueSeverity.HIGH,
                                title=f"Container error ({reason}): {pod_name}/{container_name}",
                                description=(
                                    f"Container '{container_name}' in pod '{pod_name}' "
                                    f"is in waiting state with reason '{reason}'. "
                                    f"Message: {cs.state.waiting.message or 'N/A'}."
                                ),
                                raw_data={
                                    "reason": reason,
                                    "message": cs.state.waiting.message,
                                    "restart_count": restart_count,
                                },
                                namespace=self._cfg.namespace,
                                pod_name=pod_name,
                                container_name=container_name,
                                node_name=node_name,
                            )
                        )

                # ── Restart count spike ────────────────────────────────────
                key = f"{pod_name}/{container_name}"
                last = self._last_restart_counts.get(key, 0)
                if restart_count >= RESTART_THRESHOLD and restart_count > last:
                    # Only flag once per spike (new restarts since last cycle)
                    new_restarts = restart_count - last
                    if new_restarts >= 2:
                        issues.append(
                            Issue(
                                issue_type=IssueType.POD_CRASH,
                                severity=IssueSeverity.HIGH,
                                title=f"High restart count ({restart_count}): {pod_name}/{container_name}",
                                description=(
                                    f"Container '{container_name}' in pod '{pod_name}' "
                                    f"has restarted {restart_count} times total "
                                    f"({new_restarts} new since last check). "
                                    f"This suggests a recurring startup or runtime failure."
                                ),
                                raw_data={
                                    "restart_count": restart_count,
                                    "new_restarts_this_cycle": new_restarts,
                                    "pod_phase": pod.status.phase,
                                },
                                namespace=self._cfg.namespace,
                                pod_name=pod_name,
                                container_name=container_name,
                                node_name=node_name,
                            )
                        )
                self._last_restart_counts[key] = restart_count

        logger.info("PodMonitor: found %d issue(s)", len(issues))
        return issues
