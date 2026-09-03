# src/utils/retry_backoff.py
"""
Shared exponential-backoff gate for the local pending-sync queues (sessions,
session logs, patients). Without this, a background sweep running every
~20s would hammer an unreachable/rejecting server at full frequency forever;
with it, retries space themselves out (10s, 20s, 40s, ... capped at 5 min)
based on each item's own attempt count, so a persistently-failing item backs
off while everything else still gets retried promptly.
"""

from datetime import timedelta
from typing import Any

from src.utils.clock import parse_utc, utc_now


def is_ready_for_retry(
    item: dict[str, Any], base_delay: float = 10.0, max_delay: float = 300.0
) -> bool:
    attempts = item.get("attempts") or 0
    last_attempt_at = item.get("last_attempt_at")

    if attempts <= 0 or not last_attempt_at:
        return True

    # Unparsable or absent timestamp shouldn't permanently wedge an item —
    # fail open. `last_attempt_at` is SQLite CURRENT_TIMESTAMP, which is UTC
    # with no zone on it; parse_utc is where that convention is stated.
    last_dt = parse_utc(last_attempt_at)
    if last_dt is None:
        return True

    delay = min(base_delay * (2 ** min(int(attempts), 10)), max_delay)
    return utc_now() >= last_dt + timedelta(seconds=delay)
