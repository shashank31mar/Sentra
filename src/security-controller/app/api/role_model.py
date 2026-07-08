"""WS-G B2.1 (lld/40 §5 / G2.9) — the D3 role-model generator.

Single source of truth for the client↔server RBAC parity check. Walks the live
FastAPI app for every route carrying a ``require_role(...)`` / ``require_platform``
dependency and emits a stable JSON fixture the console's ``rbac.parity.test.ts``
(frontend G2.9) asserts its ``rbac.ts`` map against.

Why the backend owns this: the server ``require_role`` (``deps.py:496``) IS the
authorization boundary; the client render-gate only MIRRORS it. Deriving the
fixture from the running app (not a hand-maintained list) means the parity test
catches ANY drift between a route's server floor and the client capability map.

Emitted schema (the frontend consumer contract — do NOT drift without updating
``tasks/serverless-edition/ws-g-build/ws-g-backend.md`` §B2.1):

    {
      "rank":  ["viewer", "editor", "admin", "owner"],   # deps.py:39 _ROLE_ORDER
      "minRole": { "viewer": 0, "editor": 1, ... },        # rank → index
      "routes": [
        {"path": "/v1/policies/{policy_id}", "method": "DELETE", "min_role": "admin"},
        {"path": "/v1/sigma-rules/{rule_id}", "method": "PATCH", "platform": true},
        ...
      ]
    }

A ``require_platform`` route carries ``platform: true`` and NO ``min_role`` (it
gates on the reserved ``_platform`` grant, not a tenant role).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional


def _min_role_from_dep(call: Any) -> Optional[str]:
    """Recover the ``min_role`` a ``require_role(min_role)`` closure was built with.

    ``require_role`` (``deps.py:496``) returns a nested ``_dep`` closure that closes
    over ``min_role``; we read it back out of the closure cell keyed by free-var
    name (robust to free-var ordering)."""
    freevars = getattr(getattr(call, "__code__", None), "co_freevars", ()) or ()
    closure = getattr(call, "__closure__", None) or ()
    cells = {name: cell.cell_contents for name, cell in zip(freevars, closure)}
    val = cells.get("min_role")
    return val if isinstance(val, str) else None


def _classify_route(dependant: Any) -> Optional[Dict[str, Any]]:
    """Return the RBAC descriptor for a route's dependency tree, or None if the
    route carries neither ``require_role`` nor ``require_platform`` (a plain
    ``resolve_operator_tenant`` read is NOT emitted — the parity walk is over the
    gated MUTATIONS + the platform surface, per G2.9)."""
    found_min_role: Optional[str] = None
    found_platform = False

    def walk(dep: Any) -> None:
        nonlocal found_min_role, found_platform
        call = getattr(dep, "call", None)
        if call is not None:
            name = getattr(call, "__name__", "")
            qual = getattr(call, "__qualname__", "")
            if name == "require_platform":
                found_platform = True
            elif qual == "require_role.<locals>._dep" or name == "_dep":
                mr = _min_role_from_dep(call)
                if mr is not None:
                    found_min_role = mr
        for sub in getattr(dep, "dependencies", []) or []:
            walk(sub)

    walk(dependant)

    if found_platform:
        return {"platform": True}
    if found_min_role is not None:
        return {"min_role": found_min_role}
    return None


def build_role_model(app: Any) -> Dict[str, Any]:
    """Build the role-model dict from a FastAPI ``app`` route-walk.

    Deterministic ordering (path, then method) so the emitted JSON is stable across
    runs — a committed fixture must not churn on re-generation."""
    from app.api.deps import _ROLE_ORDER

    routes: List[Dict[str, Any]] = []
    for route in getattr(app, "routes", []):
        dependant = getattr(route, "dependant", None)
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if dependant is None or not path or not methods:
            continue
        if not str(path).startswith("/v1"):
            continue
        descriptor = _classify_route(dependant)
        if descriptor is None:
            continue
        # HEAD/OPTIONS are framework-added — never a gated mutation surface.
        for method in sorted(m for m in methods if m not in ("HEAD", "OPTIONS")):
            row = {"path": path, "method": method}
            row.update(descriptor)
            routes.append(row)

    routes.sort(key=lambda r: (r["path"], r["method"]))
    rank = list(_ROLE_ORDER)
    return {
        "rank": rank,
        "minRole": {role: idx for idx, role in enumerate(rank)},
        "routes": routes,
    }


def _load_app() -> Any:
    from app.main import app
    return app


# The fixture path the frontend G2.9 parity test reads (relative to the repo root).
# From this file: src/security-controller/app/api/role_model.py → repo root is 4 up.
_REPO_ROOT = Path(__file__).resolve().parents[4]
FIXTURE_PATH = _REPO_ROOT / "web" / "console" / "src" / "lib" / "__fixtures__" / "role-model.json"
BAD_FIXTURE_PATH = _REPO_ROOT / "web" / "console" / "src" / "lib" / "__fixtures__" / "role-model.bad.json"


def _make_bad_model(model: Dict[str, Any]) -> Dict[str, Any]:
    """A DELIBERATELY-broken copy for the frontend's NEGATIVE parity test: flip the
    first ``min_role`` route's floor to a wrong role so the parity assertion MUST
    fail against it. If there is no min_role route (shouldn't happen), corrupt the
    rank order instead so the negative test still has something to catch."""
    import copy

    bad = copy.deepcopy(model)
    for row in bad["routes"]:
        if row.get("min_role") == "admin":
            row["min_role"] = "viewer"  # under-privilege an admin route → parity fail
            return bad
        if "min_role" in row:
            row["min_role"] = "owner"
            return bad
    bad["rank"] = list(reversed(bad["rank"]))
    return bad


def emit(app: Optional[Any] = None) -> Dict[str, Any]:
    """Generate the model and WRITE both fixtures. Returns the (good) model."""
    app = app or _load_app()
    model = build_role_model(app)
    FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    FIXTURE_PATH.write_text(json.dumps(model, indent=2, sort_keys=False) + "\n")
    BAD_FIXTURE_PATH.write_text(json.dumps(_make_bad_model(model), indent=2, sort_keys=False) + "\n")
    return model


if __name__ == "__main__":  # pragma: no cover — script entrypoint
    m = emit()
    print(f"wrote {len(m['routes'])} gated routes -> {FIXTURE_PATH}")
    print(f"wrote negative fixture -> {BAD_FIXTURE_PATH}")
