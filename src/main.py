"""
main.py — JBoss AI Monitor — Main orchestrator loop.

Architecture:
  ┌─────────────────────────────────────────────────────────────────────┐
  │                    MonitoringAgent (this file)                      │
  │                                                                     │
  │  ┌──────────────┐  ┌──────────────┐  ┌───────────┐  ┌──────────┐  │
  │  │  PodMonitor  │  │ AlertMonitor │  │LogMonitor │  │HealthMon │  │
  │  └──────┬───────┘  └──────┬───────┘  └─────┬─────┘  └────┬─────┘  │
  │         └─────────────────┴────────────────┴──────────────┘        │
  │                                    │ Issues                         │
  │                             ┌──────▼──────┐                         │
  │                             │  Dedup      │                         │
  │                             └──────┬──────┘                         │
  │                                    │ new issues only                │
  │                             ┌──────▼──────┐                         │
  │                             │  Claude AI  │  (ResolutionAgent)      │
  │                             └──────┬──────┘                         │
  │                                    │ Resolution                     │
  │                             ┌──────▼──────┐                         │
  │                             │  JIRA Client│                         │
  │                             └─────────────┘                         │
  └─────────────────────────────────────────────────────────────────────┘

Runs continuously with a configurable sleep interval between cycles.
"""

import logging
import os
import sys
import time
from typing import List

from kubernetes import client as k8s_client, config as k8s_config

from src.config import Config, load_config
from src.models import Issue
from src.monitors.pod_monitor import PodMonitor
from src.monitors.alert_monitor import AlertMonitor
from src.monitors.log_monitor import LogMonitor
from src.monitors.health_monitor import HealthMonitor
from src.agent.resolution_agent import ResolutionAgent
from src.jira.jira_client import JiraClient
from src.utils.dedup import IssueDeduplicator


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
    )


def load_kubernetes_client() -> k8s_client.CoreV1Api:
    """Load Kubernetes config — in-cluster first, then kubeconfig fallback."""
    try:
        k8s_config.load_incluster_config()
        logging.getLogger(__name__).info("Kubernetes: loaded in-cluster config")
    except k8s_config.ConfigException:
        k8s_config.load_kube_config()
        logging.getLogger(__name__).info("Kubernetes: loaded kubeconfig")
    return k8s_client.CoreV1Api()


def validate_config(cfg: Config) -> None:
    """Fail fast if required environment variables are missing."""
    errors = []
    if not cfg.jira_url:
        errors.append("JIRA_URL is required")
    if not cfg.jira_user:
        errors.append("JIRA_USER is required")
    if not cfg.jira_token:
        errors.append("JIRA_TOKEN is required")
    if not cfg.jira_project_key:
        errors.append("JIRA_PROJECT_KEY is required")
    if not cfg.rhoai_api_url:
        errors.append("RHOAI_API_URL is required")
    if not cfg.rhoai_model_name:
        errors.append("RHOAI_MODEL_NAME is required")
    if errors:
        for err in errors:
            logging.getLogger(__name__).error("Config error: %s", err)
        sys.exit(1)


class MonitoringAgent:
    def __init__(self, cfg: Config, v1: k8s_client.CoreV1Api) -> None:
        self._cfg = cfg
        self._logger = logging.getLogger(self.__class__.__name__)
        self._dedup = IssueDeduplicator(window_minutes=cfg.dedup_window_minutes)
        self._resolution_agent = ResolutionAgent(cfg)
        self._jira = JiraClient(cfg)

        # Instantiate enabled monitors
        self._monitors = []
        if cfg.enable_pod_monitor:
            self._monitors.append(PodMonitor(cfg, v1))
            self._logger.info("Monitor enabled: PodMonitor")
        if cfg.enable_alert_monitor:
            self._monitors.append(AlertMonitor(cfg))
            self._logger.info("Monitor enabled: AlertMonitor")
        if cfg.enable_log_monitor:
            self._monitors.append(LogMonitor(cfg, v1))
            self._logger.info("Monitor enabled: LogMonitor")
        if cfg.enable_health_monitor:
            self._monitors.append(HealthMonitor(cfg, v1))
            self._logger.info("Monitor enabled: HealthMonitor")

    def run_once(self) -> None:
        """Execute a single monitoring cycle."""
        self._logger.info("── Starting monitoring cycle ──────────────────────────")

        # ── Collect issues from all monitors ──────────────────────────────
        all_issues: List[Issue] = []
        for monitor in self._monitors:
            monitor_name = monitor.__class__.__name__
            try:
                issues = monitor.check()
                self._logger.info("%s: %d issue(s)", monitor_name, len(issues))
                all_issues.extend(issues)
            except Exception as exc:
                self._logger.error("%s: unexpected error: %s", monitor_name, exc, exc_info=True)

        if not all_issues:
            self._logger.info("No issues detected this cycle.")
            return

        self._logger.info("Total issues detected: %d", len(all_issues))

        # ── Deduplicate ────────────────────────────────────────────────────
        new_issues = [i for i in all_issues if not self._dedup.is_duplicate(i.fingerprint)]
        self._logger.info(
            "%d new issue(s) after deduplication (%d suppressed)",
            len(new_issues),
            len(all_issues) - len(new_issues),
        )

        # ── Process each new issue ─────────────────────────────────────────
        for issue in new_issues:
            self._process_issue(issue)

        # ── Housekeeping ───────────────────────────────────────────────────
        self._dedup.evict_expired()

    def _process_issue(self, issue: Issue) -> None:
        """Analyse an issue with Claude and file a JIRA ticket."""
        self._logger.info(
            "Processing issue: [%s/%s] %s",
            issue.severity.value.upper(),
            issue.issue_type.value,
            issue.title,
        )

        # ── Get AI resolution ──────────────────────────────────────────────
        self._logger.info("Requesting resolution from RHOAI model …")
        resolution = self._resolution_agent.analyse(issue)
        self._logger.info(
            "Resolution received (confidence: %s, %d steps)",
            resolution.confidence,
            len(resolution.resolution_steps),
        )

        # ── Create JIRA ticket ─────────────────────────────────────────────
        try:
            ticket = self._jira.create_ticket(issue, resolution)
            self._dedup.mark_processed(issue.fingerprint)
            self._logger.info(
                "JIRA ticket created: %s — %s", ticket.issue_key, ticket.url
            )
        except Exception as exc:
            self._logger.error("Failed to create JIRA ticket: %s", exc, exc_info=True)
            # Don't mark as processed — retry next cycle

    def run_forever(self) -> None:
        """Main loop: run monitoring cycles indefinitely."""
        interval = self._cfg.check_interval_seconds
        self._logger.info(
            "JBoss AI Monitor started. Namespace=%s  Interval=%ss",
            self._cfg.namespace,
            interval,
        )
        while True:
            try:
                self.run_once()
            except KeyboardInterrupt:
                self._logger.info("Received shutdown signal — exiting.")
                sys.exit(0)
            except Exception as exc:
                self._logger.error("Unhandled error in monitoring cycle: %s", exc, exc_info=True)
            self._logger.info("Sleeping %ss until next cycle …", interval)
            time.sleep(interval)


def main() -> None:
    cfg = load_config()
    setup_logging(cfg.log_level)
    logger = logging.getLogger("main")

    # Load optional .env file for local development
    try:
        from dotenv import load_dotenv
        load_dotenv()
        logger.debug(".env file loaded")
    except ImportError:
        pass

    logger.info("JBoss AI Monitor — version 1.0.0")
    validate_config(cfg)

    v1 = load_kubernetes_client()
    agent = MonitoringAgent(cfg, v1)
    agent.run_forever()


if __name__ == "__main__":
    main()
