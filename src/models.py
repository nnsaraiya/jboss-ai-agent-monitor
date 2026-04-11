"""
models.py — Shared data models for issues, resolutions, and JIRA tickets.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import hashlib
import json


class IssueSeverity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class IssueType(str, Enum):
    POD_CRASH = "pod_crash"
    OOM_KILLED = "oom_killed"
    CRASH_LOOP = "crash_loop_backoff"
    ALERT_FIRING = "alert_firing"
    LOG_ERROR = "log_error"
    HEALTH_FAILURE = "health_failure"


# Map issue severity to JIRA priority names
SEVERITY_TO_JIRA_PRIORITY: Dict[IssueSeverity, str] = {
    IssueSeverity.CRITICAL: "Highest",
    IssueSeverity.HIGH: "High",
    IssueSeverity.MEDIUM: "Medium",
    IssueSeverity.LOW: "Low",
}


@dataclass
class Issue:
    """Represents a single detected issue on a JBoss instance."""

    issue_type: IssueType
    severity: IssueSeverity
    title: str
    description: str
    # Raw data from kubernetes / prometheus / logs — for Claude context
    raw_data: Dict[str, Any]
    namespace: str
    pod_name: Optional[str] = None
    container_name: Optional[str] = None
    node_name: Optional[str] = None
    # Excerpt of relevant log lines or stack trace
    log_excerpt: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.utcnow)
    # Stable fingerprint used for deduplication
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if not self.fingerprint:
            raw = f"{self.issue_type.value}|{self.namespace}|{self.pod_name or ''}|{self.title[:80]}"
            self.fingerprint = hashlib.md5(raw.encode()).hexdigest()

    def to_context_dict(self) -> Dict[str, Any]:
        """Produce a clean dict to send to the Claude API for analysis."""
        return {
            "issue_type": self.issue_type.value,
            "severity": self.severity.value,
            "title": self.title,
            "description": self.description,
            "namespace": self.namespace,
            "pod_name": self.pod_name,
            "container_name": self.container_name,
            "node_name": self.node_name,
            "log_excerpt": self.log_excerpt,
            "timestamp": self.timestamp.isoformat(),
            "raw_data_summary": {
                k: str(v)[:500]  # truncate individual fields for safety
                for k, v in self.raw_data.items()
                if k not in ("logs",)  # logs go via log_excerpt
            },
        }


@dataclass
class Resolution:
    """Resolution recommendation produced by the Claude agent."""

    root_cause_analysis: str
    resolution_steps: List[str]
    prevention_tips: List[str]
    references: List[str]
    # Confidence expressed by Claude: high / medium / low
    confidence: str = "medium"


@dataclass
class JiraTicket:
    """Minimal info about a created JIRA ticket."""

    issue_key: str
    issue_id: str
    url: str
