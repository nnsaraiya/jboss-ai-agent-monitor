"""
log_monitor.py — Streams recent logs from JBoss pods and matches
configurable error patterns to detect issues.

Uses the Kubernetes Python client to fetch the last N lines of each
JBoss pod's main container, then applies regex matching for patterns
like SEVERE, OutOfMemoryError, stack traces, etc.

Groups consecutive matched lines into a single Issue to avoid flooding.
"""

import logging
import re
from typing import List, Optional

from kubernetes import client as k8s_client

from src.config import Config
from src.models import Issue, IssueSeverity, IssueType

logger = logging.getLogger(__name__)

# How many lines of context to include around a match (before + after)
CONTEXT_LINES = 5


class LogMonitor:
    def __init__(self, config: Config, v1: k8s_client.CoreV1Api) -> None:
        self._cfg = config
        self._v1 = v1
        # Compile all patterns once
        self._patterns = [
            re.compile(p, re.IGNORECASE) for p in config.log_error_patterns if p
        ]
        # Track the last log hash per pod to avoid re-alerting on the same lines
        self._last_log_hash: dict = {}

    def check(self) -> List[Issue]:
        """Scan logs of all JBoss pods; return Issues for matched patterns."""
        issues: List[Issue] = []

        try:
            pods = self._v1.list_namespaced_pod(
                namespace=self._cfg.namespace,
                label_selector=self._cfg.jboss_label_selector,
            )
        except Exception as exc:
            logger.error("LogMonitor: failed to list pods: %s", exc)
            return issues

        for pod in pods.items:
            pod_name = pod.metadata.name
            # Only scan Running pods
            if pod.status.phase not in ("Running", "Unknown"):
                continue

            containers = [c.name for c in (pod.spec.containers or [])]
            for container_name in containers:
                pod_issues = self._scan_pod_logs(pod_name, container_name, pod)
                issues.extend(pod_issues)

        logger.info("LogMonitor: found %d issue(s)", len(issues))
        return issues

    # ── Internal helpers ───────────────────────────────────────────────────

    def _scan_pod_logs(
        self,
        pod_name: str,
        container_name: str,
        pod,
    ) -> List[Issue]:
        issues: List[Issue] = []
        log_text = self._fetch_logs(pod_name, container_name)
        if not log_text:
            return issues

        lines = log_text.splitlines()

        # Quick change detection — only process if logs have new content
        import hashlib
        log_hash = hashlib.md5(log_text[-4096:].encode()).hexdigest()
        cache_key = f"{pod_name}/{container_name}"
        if self._last_log_hash.get(cache_key) == log_hash:
            return issues
        self._last_log_hash[cache_key] = log_hash

        # Find all matching lines and group nearby matches into one issue
        match_groups = self._find_match_groups(lines)

        for group_start, group_end in match_groups:
            # Extract context window
            ctx_start = max(0, group_start - CONTEXT_LINES)
            ctx_end = min(len(lines), group_end + CONTEXT_LINES + 1)
            excerpt_lines = lines[ctx_start:ctx_end]
            excerpt = "\n".join(excerpt_lines)

            # Pick the first matching line as the title
            first_match_line = lines[group_start].strip()
            title = first_match_line[:120] if first_match_line else "Log error detected"

            severity = self._infer_severity(excerpt)

            issues.append(
                Issue(
                    issue_type=IssueType.LOG_ERROR,
                    severity=severity,
                    title=f"Log error in {pod_name}/{container_name}: {title}",
                    description=(
                        f"Error pattern matched in container '{container_name}' "
                        f"of pod '{pod_name}' (namespace: {self._cfg.namespace}).\n\n"
                        f"Matched lines {group_start}–{group_end} of last "
                        f"{self._cfg.log_tail_lines} log lines."
                    ),
                    raw_data={
                        "pod_name": pod_name,
                        "container_name": container_name,
                        "matched_line_range": f"{group_start}-{group_end}",
                        "total_lines_scanned": len(lines),
                    },
                    namespace=self._cfg.namespace,
                    pod_name=pod_name,
                    container_name=container_name,
                    node_name=pod.spec.node_name,
                    log_excerpt=excerpt[:3000],  # cap excerpt size
                )
            )

        return issues

    def _fetch_logs(self, pod_name: str, container_name: str) -> Optional[str]:
        try:
            return self._v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=self._cfg.namespace,
                container=container_name,
                tail_lines=self._cfg.log_tail_lines,
                timestamps=True,
            )
        except Exception as exc:
            logger.debug("LogMonitor: could not fetch logs for %s/%s: %s", pod_name, container_name, exc)
            return None

    def _find_match_groups(self, lines: List[str]) -> List[tuple]:
        """
        Returns list of (start, end) line index tuples for groups of
        consecutive (within 10 lines) matching lines.
        """
        matching_indices = [
            i
            for i, line in enumerate(lines)
            if any(p.search(line) for p in self._patterns)
        ]
        if not matching_indices:
            return []

        groups: List[tuple] = []
        group_start = matching_indices[0]
        group_end = matching_indices[0]

        for idx in matching_indices[1:]:
            if idx - group_end <= 10:  # close enough — same group
                group_end = idx
            else:
                groups.append((group_start, group_end))
                group_start = idx
                group_end = idx
        groups.append((group_start, group_end))
        return groups

    @staticmethod
    def _infer_severity(excerpt: str) -> IssueSeverity:
        """Heuristic severity based on keywords in the excerpt."""
        upper = excerpt.upper()
        if any(k in upper for k in ("OUTOFMEMORYERROR", "OOMKILLED", "FATAL", "SEVERE")):
            return IssueSeverity.CRITICAL
        if any(k in upper for k in ("ERROR", "EXCEPTION", "STACKOVERFLOWERROR", "DEADLOCK")):
            return IssueSeverity.HIGH
        if any(k in upper for k in ("WARN", "WARNING", "TIMEOUT")):
            return IssueSeverity.MEDIUM
        return IssueSeverity.LOW
