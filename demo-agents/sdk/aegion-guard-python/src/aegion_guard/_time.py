"""Timestamp formatting (LLD 23 §4.1).

The system convention for timestamps is ISO-8601 with **millisecond** precision
ending in ``Z`` (``YYYY-MM-DDTHH:MM:SS.sssZ``). The controller's signal-store
writer enforces this for its own sort keys; we reproduce the format here so the
request ``timestamp`` echoes the same shape across every writer in the system.

This is a **convention, not a correctness gate**: the controller computes signal
sort keys from its own clock, not from ``request.timestamp``. We reimplement the
3-line formatter rather than import the controller-internal helper, because the
SDK must not depend on any controller code (it ships to customers standalone).
"""
from __future__ import annotations

from datetime import datetime, timezone


def isoformat_ms_z(ts: datetime) -> str:
    """Render a datetime as ``YYYY-MM-DDTHH:MM:SS.sssZ`` (UTC, millisecond).

    Naive datetimes are assumed to be UTC; aware datetimes are converted to UTC.
    Python's default ``isoformat`` emits microseconds, so we truncate to ms.
    """
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    else:
        ts = ts.astimezone(timezone.utc)
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def now_ms_z() -> str:
    """Current UTC time in the canonical millisecond-Z format."""
    return isoformat_ms_z(datetime.now(timezone.utc))
