"""WS-F F6.5 (§3.3 item 4) — self-contained CI assertion for the sigma-mutating
route authz gate.

Founder 2026-07-05 (Option B): this is a NON-BLOCKING WARNING, not a build failure.
WS-F ships/merges AHEAD of WS-M; WS-M (M-M3) lands the actual platform-operator
`require_role` gate on `PATCH /sigma-rules/{rule_id}` + the `__sigma_version__`
version-epoch write. When M-M3 lands, this warning clears. WS-F owns only this check
of its OWN build, so the invariant survives even if the WS-M fix later regresses.

The check inspects the app's route table for a `require_role`-style dependency on the
sigma-mutating routes. It returns the list of ungated sigma-mutating route paths
(empty once WS-M gates them). Flipping the WARNING to build-failing is a one-line
change (`raise` instead of `warn`) if the founder ever chooses to.
"""
from __future__ import annotations

import logging
from typing import List

logger = logging.getLogger(__name__)

# The sigma-mutating routes that MUST carry a platform-operator require_role
# (§3.3 + the version-epoch write). Method + path pattern.
SIGMA_MUTATING_ROUTES = [
    ("PATCH", "/v1/sigma-rules/{rule_id}"),
]


def _route_has_require_role(route) -> bool:
    """True if a Starlette/FastAPI route carries a `require_role`-style dependency.

    We look for a dependency whose callable's __qualname__ mentions `require_role`
    (the project's RBAC dep factory, imported at routes.py:19). This inspects the
    resolved dependant so it survives whether the gate is on the path operation or a
    router-level dependency."""
    dependant = getattr(route, "dependant", None)
    if dependant is None:
        return False
    stack = list(getattr(dependant, "dependencies", []))
    while stack:
        dep = stack.pop()
        call = getattr(dep, "call", None)
        qual = getattr(call, "__qualname__", "") or getattr(call, "__name__", "")
        if "require_role" in qual:
            return True
        stack.extend(getattr(dep, "dependencies", []))
    return False


def find_ungated_sigma_routes(app) -> List[str]:
    """Return the sigma-mutating route paths in `app` that lack a require_role gate.

    Empty list == the invariant holds (WS-M M-M3 has landed the gate)."""
    wanted = {(m, p) for m, p in SIGMA_MUTATING_ROUTES}
    ungated: List[str] = []
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", set()) or set()
        for method, wpath in wanted:
            if path == wpath and method in methods:
                if not _route_has_require_role(route):
                    ungated.append(f"{method} {path}")
    return ungated


def assert_sigma_routes_gated(app, *, fail_build: bool = False) -> List[str]:
    """CI hook. Emits a NON-BLOCKING WARNING (founder 2026-07-05 Option B) for each
    ungated sigma-mutating route; returns the list. If `fail_build=True` (a future
    one-line flip once WS-M lands the gate) it raises instead."""
    ungated = find_ungated_sigma_routes(app)
    for r in ungated:
        logger.warning(
            "WS-F F6.5 CI WARNING: sigma-mutating route %s lacks a platform-operator "
            "require_role gate (§3.3 — owned by WS-M M-M3; non-blocking per founder "
            "2026-07-05 Option B). This warning clears when WS-M lands the gate.", r,
        )
    if fail_build and ungated:
        raise AssertionError(
            f"sigma-mutating routes lack a require_role gate: {ungated}"
        )
    return ungated
