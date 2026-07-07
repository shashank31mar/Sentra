"""WS-F F6.5 (§3.3 item 4) — self-contained CI assertion for the sigma-mutating
route authz gate.

Founder 2026-07-05 (Option B): this is a NON-BLOCKING WARNING, not a build failure.
WS-F shipped/merged AHEAD of WS-M; WS-M (M-M3) landed the actual PLATFORM-operator
gate — `Depends(require_platform)` on `PATCH /sigma-rules/{rule_id}` + the
`__sigma_version__` version-epoch write (routes.py `update_sigma_rule`). With M-M3
landed this check returns an empty list (the WARNING has cleared). WS-F owns only
this check of its OWN build, so the invariant survives even if the WS-M gate later
regresses.

The check inspects the app's route table for a platform-operator gate dependency on
the sigma-mutating routes. Per lld/35 §3.3(4), the grep MUST accept `require_platform`
(the symbol WS-M M-M3 actually lands, lld/39 §3.5) as well as a platform-scoped
`require_role` — matching only `require_role` would false-fail once WS-M lands
`require_platform`. It returns the list of ungated sigma-mutating route paths (empty
once WS-M gates them). Flipping the WARNING to build-failing is a one-line change
(`raise` instead of `warn`) if the founder ever chooses to.
"""
from __future__ import annotations

import logging
from typing import List

logger = logging.getLogger(__name__)

# The sigma-mutating routes that MUST carry a platform-operator gate
# (§3.3 + the version-epoch write). Method + path pattern.
SIGMA_MUTATING_ROUTES = [
    ("PATCH", "/v1/sigma-rules/{rule_id}"),
]

# The platform-operator gate dependencies the grep accepts (lld/35 §3.3(4)):
# `require_platform` is the symbol WS-M M-M3 lands (lld/39 §3.5); a platform-scoped
# `require_role` is the alternate form. Matching only one would false-fail the build.
_PLATFORM_GATE_QUALNAMES = ("require_platform", "require_role")


def _route_has_platform_gate(route) -> bool:
    """True if a Starlette/FastAPI route carries a platform-operator gate dependency.

    We look for a dependency whose callable's __qualname__ mentions `require_platform`
    (WS-M M-M3, lld/39 §3.5) OR a platform-scoped `require_role` (the project's RBAC
    dep factory, imported at routes.py:19). This inspects the resolved dependant so it
    survives whether the gate is on the path operation or a router-level dependency."""
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return False
    stack = list(getattr(dependant, "dependencies", []))
    while stack:
        dep = stack.pop()
        call = getattr(dep, "call", None)
        qual = getattr(call, "__qualname__", "") or getattr(call, "__name__", "")
        if any(name in qual for name in _PLATFORM_GATE_QUALNAMES):
            return True
        stack.extend(getattr(dep, "dependencies", []))
    return False


# Back-compat alias — the pre-M-M3 name; kept so any external caller still resolves.
_route_has_require_role = _route_has_platform_gate


def find_ungated_sigma_routes(app) -> List[str]:
    """Return the sigma-mutating route paths in `app` that lack a platform-operator gate.

    Empty list == the invariant holds (WS-M M-M3 has landed the gate)."""
    wanted = {(m, p) for m, p in SIGMA_MUTATING_ROUTES}
    ungated: List[str] = []
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", set()) or set()
        for method, wpath in wanted:
            if path == wpath and method in methods:
                if not _route_has_platform_gate(route):
                    ungated.append(f"{method} {path}")
    return ungated


def assert_sigma_routes_gated(app, *, fail_build: bool = False) -> List[str]:
    """CI hook. Emits a NON-BLOCKING WARNING (founder 2026-07-05 Option B) for each
    ungated sigma-mutating route; returns the list. If `fail_build=True` it raises
    instead (a one-line flip; safe to arm now that WS-M M-M3 has landed the gate)."""
    ungated = find_ungated_sigma_routes(app)
    for r in ungated:
        logger.warning(
            "WS-F F6.5 CI WARNING: sigma-mutating route %s lacks a platform-operator "
            "gate (`require_platform` or a platform-scoped `require_role`) (§3.3 — "
            "owned by WS-M M-M3; non-blocking per founder 2026-07-05 Option B). This "
            "warning clears when WS-M lands the gate.", r,
        )
    if fail_build and ungated:
        raise AssertionError(
            f"sigma-mutating routes lack a platform-operator gate: {ungated}"
        )
    return ungated
