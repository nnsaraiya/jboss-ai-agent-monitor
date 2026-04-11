"""
jira_client.py — Creates JIRA issues via the JIRA REST API v3.

Builds a well-structured ticket description that includes:
  • Issue summary and detection metadata
  • Claude's root-cause analysis
  • Numbered resolution steps
  • Prevention tips
  • Reference links
  • Raw diagnostic data (collapsed)
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict

import requests
from requests.auth import HTTPBasicAuth

from src.config import Config
from src.models import Issue, JiraTicket, Resolution, SEVERITY_TO_JIRA_PRIORITY

logger = logging.getLogger(__name__)


class JiraClient:
    def __init__(self, config: Config) -> None:
        self._cfg = config
        self._auth = HTTPBasicAuth(config.jira_user, config.jira_token)
        self._base = config.jira_url.rstrip("/")
        self._session = requests.Session()
        self._session.auth = self._auth
        self._session.headers.update(
            {"Accept": "application/json", "Content-Type": "application/json"}
        )

    # ── Public API ─────────────────────────────────────────────────────────

    def create_ticket(self, issue: Issue, resolution: Resolution) -> JiraTicket:
        """Create a JIRA issue and return the resulting JiraTicket."""
        payload = self._build_payload(issue, resolution)
        url = f"{self._base}/rest/api/3/issue"
        try:
            resp = self._session.post(url, json=payload, timeout=30)
            if not resp.ok:
                logger.error(
                    "JiraClient: HTTP %s creating ticket.\nURL: %s\nResponse body: %s\nPayload fields: %s",
                    resp.status_code,
                    url,
                    resp.text,
                    list(payload.get("fields", {}).keys()),
                )
            resp.raise_for_status()
        except requests.HTTPError as exc:
            raise
        data = resp.json()
        issue_key = data["key"]
        issue_id = data["id"]
        ticket_url = f"{self._base}/browse/{issue_key}"
        logger.info("JiraClient: created ticket %s — %s", issue_key, ticket_url)
        return JiraTicket(issue_key=issue_key, issue_id=issue_id, url=ticket_url)

    # ── Internal helpers ───────────────────────────────────────────────────

    def _build_payload(self, issue: Issue, resolution: Resolution) -> Dict[str, Any]:
        priority = SEVERITY_TO_JIRA_PRIORITY.get(issue.severity, "High")
        description_adf = self._build_adf_description(issue, resolution)

        # Sanitize label values: JIRA labels must not contain spaces or special chars
        def _safe_label(v: str) -> str:
            return v.replace(" ", "_").replace(":", "-").replace("/", "-")

        extra_labels = [
            _safe_label(issue.issue_type.value),
            _safe_label(f"severity-{issue.severity.value}"),
        ]
        labels = [_safe_label(lbl) for lbl in self._cfg.jira_labels] + extra_labels

        fields: Dict[str, Any] = {
            "project": {"key": self._cfg.jira_project_key},
            "summary": self._truncate(f"[JBoss/OCP] {issue.title}", 255),
            "issuetype": {"name": self._cfg.jira_issue_type},
            "description": description_adf,
            "labels": labels,
        }
        # Only include priority if it's configured (some project schemes don't allow it)
        if priority:
            fields["priority"] = {"name": priority}
        return {"fields": fields}

    def _build_adf_description(
        self, issue: Issue, resolution: Resolution
    ) -> Dict[str, Any]:
        """
        Build an Atlassian Document Format (ADF) description.
        ADF is required by JIRA Cloud REST API v3.
        """
        nodes = []

        # ── Header ────────────────────────────────────────────────────────
        nodes.append(self._heading(2, "🔴 Issue Detected"))
        nodes.append(self._paragraph(f"**Type:** {issue.issue_type.value}"))
        nodes.append(self._paragraph(f"**Severity:** {issue.severity.value.upper()}"))
        nodes.append(self._paragraph(f"**Namespace:** {issue.namespace}"))
        if issue.pod_name:
            nodes.append(self._paragraph(f"**Pod:** {issue.pod_name}"))
        if issue.container_name:
            nodes.append(self._paragraph(f"**Container:** {issue.container_name}"))
        nodes.append(
            self._paragraph(
                f"**Detected at:** {issue.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}"
            )
        )

        # ── Description ───────────────────────────────────────────────────
        nodes.append(self._heading(2, "📋 Description"))
        nodes.append(self._paragraph(issue.description))

        # ── Log excerpt ───────────────────────────────────────────────────
        if issue.log_excerpt:
            nodes.append(self._heading(2, "📄 Log Excerpt"))
            nodes.append(self._code_block(issue.log_excerpt))

        # ── Root Cause Analysis ───────────────────────────────────────────
        nodes.append(self._heading(2, "🧠 Root Cause Analysis (AI)"))
        nodes.append(
            self._paragraph(
                f"_Confidence: {resolution.confidence.upper()}_ — "
                "Generated by Claude AI. Please verify before acting."
            )
        )
        nodes.append(self._paragraph(resolution.root_cause_analysis))

        # ── Resolution Steps ──────────────────────────────────────────────
        nodes.append(self._heading(2, "🔧 Resolution Steps"))
        for i, step in enumerate(resolution.resolution_steps, 1):
            nodes.append(self._paragraph(f"{i}. {step}"))

        # ── Prevention ────────────────────────────────────────────────────
        if resolution.prevention_tips:
            nodes.append(self._heading(2, "🛡️ Prevention Tips"))
            for tip in resolution.prevention_tips:
                nodes.append(self._paragraph(f"• {tip}"))

        # ── References ────────────────────────────────────────────────────
        if resolution.references:
            nodes.append(self._heading(2, "📚 References"))
            for ref in resolution.references:
                nodes.append(self._paragraph(f"• {ref}"))

        # ── Raw diagnostic data ───────────────────────────────────────────
        if issue.raw_data:
            nodes.append(self._heading(2, "🔍 Diagnostic Data"))
            import json
            raw_str = json.dumps(issue.raw_data, indent=2, default=str)
            nodes.append(self._code_block(raw_str[:2000]))

        nodes.append(
            self._paragraph(
                "---\n_This ticket was automatically created by the JBoss AI Monitor agent._"
            )
        )

        return {"version": 1, "type": "doc", "content": nodes}

    # ── ADF node helpers ───────────────────────────────────────────────────

    @staticmethod
    def _heading(level: int, text: str) -> Dict[str, Any]:
        return {
            "type": "heading",
            "attrs": {"level": level},
            "content": [{"type": "text", "text": text}],
        }

    @staticmethod
    def _paragraph(text: str) -> Dict[str, Any]:
        return {
            "type": "paragraph",
            "content": [{"type": "text", "text": text}],
        }

    @staticmethod
    def _code_block(code: str) -> Dict[str, Any]:
        return {
            "type": "codeBlock",
            "attrs": {"language": "text"},
            "content": [{"type": "text", "text": code}],
        }

    @staticmethod
    def _truncate(text: str, max_len: int) -> str:
        return text if len(text) <= max_len else text[: max_len - 3] + "..."
