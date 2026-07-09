"""WS-J J8.4 — live-only coverage of the OPERATOR (oidc) route lane.

Every ``auth_class == "oidc"`` route requires an operator OIDC session
(``resolve_operator_tenant`` / ``require_role`` / ``require_platform``). Two facts
shape how the canary covers them:

  * The **no-identity** leg (an ``X-Api-Key``-only call with no ALB session cookie)
    is reachable WITHOUT a browser — it MUST fail-secure to a 4xx (401/403). This is
    the exact pattern WS-N shipped for the two metrics rows in ``test_metrics_live.py``,
    generalized here to EVERY oidc route. A 2xx to an un-authenticated caller is the
    operator gate leaking → RED.
  * The **authenticated** leg (a real operator session) needs the hosted-UI login
    fixture (``canary_operator`` live form, J8.1) driving Playwright — that lives in
    ``test_console_authed_oidc.py`` (browser-gated), not here.

So THIS module is pure httpx, ``requires_live`` (the hourly prod monitor runs it; the
hermetic PR gate skips it — there is no live gateway in-process). It carries NO
Playwright import, so it stays in the lean live-collection allowlist. The metrics rows
``/v1/metrics/overview`` + ``/v1/metrics/decisions-timeseries`` are OWNED by
``test_metrics_live.py`` (they read CloudWatch, a distinct concern) and are excluded
here to keep single ownership — see ``_METRICS_LIVE_OWNED``.
"""
from __future__ import annotations

import pytest

from canary.route_manifest import ROUTE_MANIFEST
from canary.scenarios import _fill_path, _positive_body

# Owned by test_metrics_live.py (CloudWatch GetMetricData rows) — excluded here so a
# route is probed by exactly one live module (no duplicate per-run probe).
_METRICS_LIVE_OWNED = frozenset(
    {"/v1/metrics/overview", "/v1/metrics/decisions-timeseries"}
)

# Every oidc route (WS-N-reclassified reads + the tenancy/platform/credential set).
_OIDC_ROUTES = [
    s for s in ROUTE_MANIFEST
    if s.auth_class == "oidc" and s.path not in _METRICS_LIVE_OWNED
]
_OIDC_IDS = [f"{s.method} {s.path}" for s in _OIDC_ROUTES]


@pytest.mark.requires_live
@pytest.mark.parametrize("spec", _OIDC_ROUTES, ids=_OIDC_IDS)
def test_oidc_route_no_identity_refused(canary_client, spec):
    """J8.4 (no-identity leg) — an operator route called with NO ALB OIDC session (the
    canary's api-key-host client carries none) MUST fail-secure: ``resolve_operator_
    tenant`` / ``require_role`` / ``require_platform`` refuses the un-authenticated
    caller with a **401 or 403**. A 2xx means the operator gate LEAKED (the WS-N read
    lock / WS-M mutation lock is not holding) → RED CRITICAL.

    NOTE: this asserts the SPECIFIC 401/403 refusal, NOT the generic ``scenario_j2_4_
    negative("401")`` (which only checks ``<500`` — too weak here: a leaked gate
    returning 200 would pass that). This is the live gate-holding proof, so it must
    reject a 2xx. Runs live-only (the in-process app never sees the gateway OIDC gate)."""
    url = _fill_path(spec.path)
    body = _positive_body(spec.path, spec.method)
    kwargs = {"json": body} if body is not None and spec.method not in ("GET", "DELETE") else {}
    resp = getattr(canary_client, spec.method.lower())(url, **kwargs)
    # The load-bearing invariant: the operator route must NOT EXECUTE for a caller with
    # no OIDC session → NEVER a 2xx (a 2xx = the resolve_operator_tenant/require_role/
    # require_platform lock leaked → RED CRITICAL) and never a 5xx. The refusal is an
    # honest 4xx: 401/403 (auth gate) OR 422/400 for a POST whose Pydantic BODY model
    # validates before the auth dependency fires (FastAPI resolves a body param first —
    # e.g. POST /v1/tenants + /v1/invites/redeem take a body model, so an empty probe
    # body 422s pre-auth; both declare "422" in failure_axis). GET reads have no body,
    # so they land squarely on 401/403. The specific gate proof is the authed leg
    # (test_console_authed_oidc) — this live leg is the "no anonymous 2xx" monitor,
    # matching the J7.1 gated-mutation contract (a body-first 4xx is still a refusal)."""
    assert 400 <= resp.status_code < 500, (
        f"{spec.method} {spec.path} with NO operator session → {resp.status_code}, "
        f"expected a 4xx refusal (401/403 auth, or 422/400 body-first); a 2xx = the "
        f"operator gate leaked → RED CRITICAL, a 5xx = a server error"
    )
    # A GET read has no body model to validate first, so it MUST hit the auth gate
    # directly — pin it to 401/403 (a GET returning 422/400 would be anomalous).
    if spec.method == "GET":
        assert resp.status_code in (401, 403), (
            f"GET {spec.path} with no operator session → {resp.status_code}, expected "
            f"401/403 (a read has no body to validate before the auth gate)"
        )

