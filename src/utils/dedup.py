"""
dedup.py — In-memory issue deduplication with a sliding time window.

Prevents the agent from opening multiple JIRA tickets for the same
recurring issue within the configured dedup window.
"""

import logging
from datetime import datetime, timedelta
from typing import Dict

logger = logging.getLogger(__name__)


class IssueDeduplicator:
    """
    Tracks issue fingerprints with the UTC timestamp they were last seen.
    An issue is considered a duplicate if the same fingerprint was seen
    within `window_minutes` of now.
    """

    def __init__(self, window_minutes: int = 120) -> None:
        self._window = timedelta(minutes=window_minutes)
        # fingerprint -> datetime of last JIRA creation
        self._seen: Dict[str, datetime] = {}

    def is_duplicate(self, fingerprint: str) -> bool:
        """Return True if the issue was already processed within the window."""
        last_seen = self._seen.get(fingerprint)
        if last_seen is None:
            return False
        age = datetime.utcnow() - last_seen
        if age < self._window:
            logger.debug(
                "Duplicate suppressed: fingerprint=%s age=%s window=%s",
                fingerprint,
                age,
                self._window,
            )
            return True
        # Window expired — allow re-processing
        return False

    def mark_processed(self, fingerprint: str) -> None:
        """Record that a JIRA ticket was just created for this fingerprint."""
        self._seen[fingerprint] = datetime.utcnow()

    def evict_expired(self) -> None:
        """Housekeeping: remove entries older than the window to free memory."""
        cutoff = datetime.utcnow() - self._window
        expired = [fp for fp, ts in self._seen.items() if ts < cutoff]
        for fp in expired:
            del self._seen[fp]
        if expired:
            logger.debug("Evicted %d expired dedup entries", len(expired))
