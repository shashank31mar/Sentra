"""The frozen local-floor verdict contract (WS-A ship-now seam; lld/36 §4.2.1).

This module is deliberately TINY in SDK 0.2.0: it declares ONLY the
``LocalFloorVerdict`` enum. There is **no interpreter, no bundle evaluator, no
caching, no crypto** here — that is lld/37's scope (``ws-a-local-floor-bundle``).
This release ships the *name* so that lld/37, the WS-J differential runner and
WS-H metering can code against a stable, frozen contract before the producer
exists.

``LocalFloorVerdict`` is the verdict a future in-process floor (lld/37) will
return for a locally-evaluable action. In 0.2.0 nothing ever mints one — the
seam (:mod:`aegion_guard.guard`) always routes to the hosted PDP (fail-secure).
It is a ``str``-Enum so a member serializes as its plain string value on the
wire / in a log line without a bespoke encoder.

Fail-secure note: the four members map to the four terminal states a floor may
reach. ``DENY_BY_DEFAULT`` is the deny-by-default floor (deny-overrides,
NFR-4) — an unknown/unhandled local case DENYs, it never allows. The seam that
consumes these (lld/37) must translate a floor verdict into a real
``Decision`` or ``None`` (route to hosted); it must NEVER let a bare enum escape
as a verdict (a ``str``-Enum reads truthy → fail-OPEN).
"""
from __future__ import annotations

from enum import Enum


class LocalFloorVerdict(str, Enum):
    """The four terminal verdicts an in-process local floor may reach (lld/36 §4.2.1).

    FROZEN CONTRACT (owned by WS-A / ws-a-sdk-release): the member set and their
    string values are a shared join key consumed by lld/37 (the interpreter that
    fills the seam), the WS-J differential runner and WS-H metering. A member
    added, removed or renamed here is a contract change that ripples into those
    consumers — ``tests/test_local_floor_seam.py::test_verdict_enum_frozen``
    fails on any drift, forcing the change through review rather than silently.
    """

    LOCAL_ALLOW = "LOCAL_ALLOW"
    LOCAL_DENY = "LOCAL_DENY"
    ESCALATE = "ESCALATE"
    DENY_BY_DEFAULT = "DENY_BY_DEFAULT"
