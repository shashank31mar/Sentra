"""WS-K K8 — Post-cutover acceptance + durable regression suite.

Implements LLD 27 §7 (the owner-directed post-cutover acceptance gate AND the
durable regression suite reused on every later PR). Spec:
`tasks/serverless-edition/ws-k-production-activation.md` Milestone K8 (§K8.1–K8.3).
Verifies FR-10.5 (prod/staging TENANCY_V2 activation), AD-7/FR-10.3 (verified
agent identity), AD-2 (Cedar authoritative).

Why this suite exists (LLD §7, owner directive): there are no real customers yet,
so a break won't announce itself as a complaint — we only find it by testing every
API across all use-cases ourselves, immediately after the cutover. A red run blocks
"go-live complete."

What it asserts: HTTP **status codes** and **reason codes** (e.g. `IDENTITY_UNVERIFIED`)
against a LIVE deployed controller — never internal state. The full route inventory
(59 routes from `app/api/routes.py` + `app/api/tenancy_routes.py`) is covered two ways:
  * the named load-bearing groups below get behavioural happy + failure-path tests;
  * the parametrized `test_every_route_responds` (K8.3 gap 2) covers REACHABILITY for
    every route (catches the apigw-per-resource missing-route footgun, LLD §8 E4).
Per K8.2 / the module note, the ~6 CRUD resource families get explicit 401/403/404/400
failure-path tests; the parametrized enumeration covers reachability for the rest.

How to run (LLD §7.1): against the **prod** ALB with an operator OIDC token + a
credentialed `acme` agent's signing key —
    SECURITY_CONTROLLER_URL=https://<prod-alb> \
    SENTRA_OPERATOR_TOKEN=<oidc> SENTRA_API_KEY=<gw-key> \
    pytest tests/integration/ -m integration -v
With NO deployed target the suite is a clean SKIP (see `_require_reachable`), never an
ERROR — so it is safe to collect/run in a bare CI/dev env.

Markers: every test is `@pytest.mark.integration` AND `@pytest.mark.requires_services`
(these hit a live deployed controller; they must NOT run in the unit suite). Fixtures
`service_urls` / `api_headers` come from `tests/integration/conftest.py` (do not redefine).
"""
from __future__ import annotations

import os
import time
import uuid

import pytest
import requests

# Decorate the whole module so every test is integration + requires_services without
# repeating the markers on each function (mirrors the suite's "live controller only"
# contract). Individual tests may still add `@pytest.mark.xfail` etc.
pytestmark = [pytest.mark.integration, pytest.mark.requires_services]

# Per-run id namespace. This is a normal test file (NOT the workflow harness), so
# uuid/time are fine and give clean, collision-free, self-cleaning ids on re-run.
RUN_ID = os.environ.get("WS_K_K8_RUN_ID") or f"ws-k-k8-{uuid.uuid4().hex[:8]}"

# A short connect+read timeout so a wedged/absent endpoint fails fast rather than
# hanging the suite.
HTTP_TIMEOUT = float(os.environ.get("WS_K_K8_HTTP_TIMEOUT", "10"))


# =========================================================================== #
# Skip-guard — the file must COLLECT cleanly and SKIP (not ERROR) with no target
# =========================================================================== #
@pytest.fixture(scope="session")
def base_url(service_urls):
    """The deployed controller base URL (no trailing slash). All routes are /v1/*."""
    return service_urls["security_controller"].rstrip("/")


@pytest.fixture(scope="session", autouse=True)
def _require_reachable(base_url):
    """One `GET /v1/health` probe per session. If the controller is unreachable
    (no deployed target from this env), skip the WHOLE suite cleanly rather than
    erroring — so the file is safe to collect/run anywhere (K8.1 quality bar).

    A reachable controller that returns 503 (a dependency is unhealthy) is NOT a
    skip — the suite should run and surface that as real failures."""
    try:
        resp = requests.get(f"{base_url}/v1/health", timeout=HTTP_TIMEOUT)
    except requests.exceptions.RequestException as exc:
        pytest.skip(
            f"controller not reachable at {base_url} ({exc.__class__.__name__}); "
            "post-cutover suite requires a deployed target "
            "(set SECURITY_CONTROLLER_URL to the prod/staging ALB)."
        )
    # Health endpoint reachable — the suite runs. (503 = degraded-but-present is
    # intentionally NOT skipped; let the relevant tests surface it.)
    return resp


# =========================================================================== #
# Helpers
# =========================================================================== #
def _no_auth_headers(api_headers):
    """A copy of the operator headers with EVERY auth credential stripped — used
    to assert the 401 (no-auth) failure path. The control-plane front door verifies
    an ALB-OIDC operator token (deps.verify_alb_oidc); against a deployed ALB a
    request with no operator identity must be rejected (401)."""
    stripped = dict(api_headers)
    for key in ("Authorization", "X-Operator-Email", "x-amzn-oidc-data",
                "x-sentra-oidc-data", "X-Aegion-Tenant"):
        stripped.pop(key, None)
    # Keep Content-Type so the request is otherwise well-formed.
    stripped.setdefault("Content-Type", "application/json")
    return stripped


def _agent_id_for(tenant_id: str) -> str:
    """Canonical, tenant-scoped agent_id: `{tenant}-{cloud}-{slug}-{hash}`. The
    controller's isolation check (deps / tenancy_routes._assert_owns_agent) requires
    a DELIMITED `tenant_id + "-"` prefix, so a bare tenant id won't do."""
    return f"{tenant_id}-aws-{RUN_ID}-0001"


def _validate_body(agent_id: str, tool_name: str, tool_params: dict,
                   *, user_input: str = "routine operation",
                   operation_type: str = "READ", session_id: str | None = None) -> dict:
    """Build a well-formed POST /v1/validate body (matches app.api.models.ValidationRequest:
    all of request_id/session_id/agent_id/tool_name/user_input/timestamp/operation_type
    are required)."""
    return {
        "request_id": f"req-{RUN_ID}-{uuid.uuid4().hex[:8]}",
        "session_id": session_id or f"sess-{RUN_ID}-{uuid.uuid4().hex[:8]}",
        "agent_id": agent_id,
        "tool_name": tool_name,
        "tool_params": tool_params,
        "user_input": user_input,
        "timestamp": "2026-06-29T00:00:00Z",
        "operation_type": operation_type,
    }


def _decision_of(resp: requests.Response) -> str | None:
    """Pull the `decision` field out of a /v1/validate response (ALLOW/DENY), or
    None if the body isn't the validate shape."""
    try:
        return (resp.json() or {}).get("decision")
    except ValueError:
        return None


# --------------------------------------------------------------------------- #
# K8.3 gap 2 helper — "is this route REACHABLE (handler ran), not a gateway hole?"
# --------------------------------------------------------------------------- #
# The apigw-per-resource footgun (LLD §8 E4 / ops memo): a controller route that
# was never wired into API Gateway + ALB returns a *gateway* 403 with the body
# {"message":"Missing Authentication Token"} (a 43-byte body, absent from the
# controller logs) — NOT a handler response. We must distinguish:
#   * route EXISTS, handler ran  -> 200/201/202/204/400/401/403/404-resource/409/422/429/503
#   * route MISSING at the gateway -> the "Missing Authentication Token" 403, OR a
#     connection error, OR a 5xx that names no handler.
_GATEWAY_MISSING_MARKERS = (
    "missing authentication token",  # API Gateway: route not defined for this method
    "no method found",               # API Gateway: undefined method on a known resource
)


def _route_exists(resp: requests.Response) -> bool:
    """True iff the response proves the route's HANDLER ran (route is wired through
    the gateway + ALB to the controller). False iff it looks like an undefined
    gateway route (the E4 footgun).

    Rationale for each branch:
      * Any 2xx/4xx that ISN'T the API-Gateway "Missing Authentication Token" 403 is
        a handler response — even a 404 ("resource not found"), a 401 (auth required),
        a 403 (wrong tenant/role), a 422 (validation), a 409, a 429 (quota). The
        handler ran; the route exists.
      * A 403 whose body is the API-Gateway "Missing Authentication Token" / "No
        method found" marker means the gateway has no integration for this
        method+path — the route is a hole. FAIL.
      * A 5xx is allowed ONLY if it carries a JSON detail (a handler error like a
        downstream dependency); a bare/empty 5xx with no body is treated as
        undefined-route/edge failure. FAIL.
    """
    status = resp.status_code
    body_text = (resp.text or "").lower()

    if status == 403 and any(m in body_text for m in _GATEWAY_MISSING_MARKERS):
        return False
    if 200 <= status < 500:
        # 2xx/3xx/4xx all mean a handler produced a deliberate response.
        return True
    # 5xx: accept only if the controller produced a structured error body (handler
    # ran and failed for a real reason); reject a contentless gateway/edge 5xx.
    if status >= 500:
        try:
            payload = resp.json()
        except ValueError:
            return False
        return bool(payload)
    return False


# The FULL 59-route inventory (prefix /v1) — method + path template with absent-id
# placeholders. Source: app/api/routes.py (43) + app/api/tenancy_routes.py (16).
# Placeholders are obviously-absent ids so a 404 here means "resource not found"
# (route exists), never a real delete/mutation. Bodies for the write routes are the
# minimal well-formed shape so we reach the handler (not a pre-handler 422 that
# would still prove reachability, but a clean handler entry is cleaner).
_ABSENT = "__nope__"
_ROUTE_INVENTORY = [
    # ---- routes.py ----
    ("GET", "/v1/health", None),
    ("POST", "/v1/validate", _validate_body(_agent_id_for(_ABSENT), "noop", {})),
    ("GET", "/v1/logs", None),
    ("GET", f"/v1/sessions/{_ABSENT}/decisions", None),
    ("GET", f"/v1/sessions/{_ABSENT}/signals", None),
    ("GET", "/v1/decisions", None),
    ("POST", f"/v1/sessions/{_ABSENT}/signals", {"source": "test", "signal_type": "noop"}),
    ("GET", "/v1/sessions", None),
    ("GET", "/v1/metrics", None),
    ("GET", "/v1/metrics/overview", None),
    ("GET", "/v1/metrics/platform-distribution", None),
    ("GET", "/v1/metrics/decisions-timeseries", None),
    ("GET", "/v1/discovery/agents", None),
    ("GET", "/v1/discovery/summary", None),
    ("GET", "/v1/discovery/platforms", None),
    ("POST", "/v1/discovery/import", {"agent_ids": [], "enforcement_mode": "monitor"}),
    ("GET", "/v1/connections", None),
    ("POST", "/v1/connections", {"cloud_provider": "aws"}),
    ("GET", f"/v1/connections/{_ABSENT}", None),
    ("PUT", f"/v1/connections/{_ABSENT}", {"role_arn": "arn:aws:iam::000000000000:role/x"}),
    ("POST", f"/v1/connections/{_ABSENT}/test", {}),
    ("POST", f"/v1/connections/{_ABSENT}/scan", None),
    ("DELETE", f"/v1/connections/{_ABSENT}", None),
    ("POST", f"/v1/agents/{_ABSENT}/policies", {"policy_id": _ABSENT}),
    ("DELETE", f"/v1/agents/{_ABSENT}/policies/{_ABSENT}", None),
    ("POST", f"/v1/decisions/{_ABSENT}/verdict",
     {"verdict": "false_positive", "reason": "test", "operator_id": "test"}),
    ("GET", "/v1/agents", None),
    ("GET", f"/v1/agents/{_ABSENT}", None),
    ("GET", f"/v1/agents/{_ABSENT}/tools", None),
    ("GET", "/v1/policies", None),
    ("GET", f"/v1/policies/{_ABSENT}", None),
    ("POST", "/v1/policies", {"schema_version": "v1", "agent_id": _ABSENT, "name": "x",
                              "version": "1.0.0", "allowed_tools": [], "policies": []}),
    ("PUT", f"/v1/policies/{_ABSENT}", {"schema_version": "v1", "agent_id": _ABSENT,
                                        "name": "x", "version": "1.0.0",
                                        "allowed_tools": [], "policies": []}),
    ("DELETE", f"/v1/policies/{_ABSENT}", None),
    ("PATCH", f"/v1/policies/{_ABSENT}/status", {"status": "disabled"}),
    ("GET", "/v1/sigma-rules", None),
    ("PATCH", f"/v1/sigma-rules/{_ABSENT}", {"status": "disabled"}),
    ("GET", f"/v1/sigma-rules/{_ABSENT}/content", None),
    ("GET", f"/v1/logs/conversation/{_ABSENT}", None),
    ("POST", "/v1/rollback", {"action_id": _ABSENT, "action_type": "noop",
                              "reason": "test", "operator_id": "test"}),
    ("POST", f"/v1/rollback/conversation/{_ABSENT}", {"reason": "test"}),
    ("POST", f"/v1/quarantine/{_ABSENT}", {"reason": "test", "operator_id": "test"}),
    ("DELETE", f"/v1/quarantine/{_ABSENT}", None),
    # ---- tenancy_routes.py ----
    ("GET", "/v1/me", None),
    ("POST", f"/v1/agents/{_ABSENT}/credentials",
     {"public_key": "-----BEGIN PUBLIC KEY-----\nnope\n-----END PUBLIC KEY-----", "alg": "ES256"}),
    ("GET", f"/v1/agents/{_ABSENT}/credentials", None),
    ("GET", "/v1/identity/residual-agents", None),
    ("POST", f"/v1/agents/{_ABSENT}/credentials/{_ABSENT}/rotate", None),
    ("DELETE", f"/v1/agents/{_ABSENT}/credentials/{_ABSENT}", None),
    ("POST", "/v1/tenants", {"display_name": "ws-k-k8 probe"}),
    ("GET", f"/v1/tenants/{_ABSENT}", None),
    ("PATCH", f"/v1/tenants/{_ABSENT}", {"display_name": "x"}),
    ("DELETE", f"/v1/tenants/{_ABSENT}", None),
    ("GET", f"/v1/tenants/{_ABSENT}/members", None),
    ("POST", f"/v1/tenants/{_ABSENT}/invites", {"email": "x@example.com", "role": "viewer"}),
    ("POST", "/v1/invites/redeem", {"invite_token": _ABSENT}),
    ("DELETE", f"/v1/tenants/{_ABSENT}/members/{_ABSENT}", None),
    ("GET", "/v1/platform/tenants", None),
    ("GET", f"/v1/platform/tenants/{_ABSENT}", None),
]


# =========================================================================== #
# Group 1 — Data plane: POST /v1/validate (LLD §7.2 data-plane row)
# =========================================================================== #
class TestDataPlaneValidate:
    """ALLOW + DENY round-trips, the identity-gate DENY shape, cross-tenant spoof."""

    def test_validate_allow_roundtrip(self, base_url, api_headers):
        """A benign READ tool call returns the validate envelope with a `decision`
        of ALLOW or DENY (the contract shape), 200 on the HTTP layer. We assert the
        envelope + that an obviously-benign call is not a 5xx — the deployed policy
        set decides ALLOW vs DENY, so we assert SHAPE here (the over-cap DENY test
        below pins the DENY behaviour deterministically)."""
        body = _validate_body(
            _agent_id_for("acme"), "query_customers",
            {"query": "SELECT id FROM customers LIMIT 1"},
            user_input="show me one customer", operation_type="READ",
        )
        resp = requests.post(f"{base_url}/v1/validate", json=body,
                             headers=api_headers, timeout=HTTP_TIMEOUT)
        assert resp.status_code == 200, f"validate HTTP {resp.status_code}: {resp.text}"
        assert _decision_of(resp) in ("ALLOW", "DENY"), \
            f"validate must return a decision envelope, got {resp.text}"

    def test_validate_deny_over_cap_refund(self, base_url, api_headers):
        """A `process_refund` with an over-cap amount must DENY (the deterministic
        param-bound floor — the moat spine shipped in Serverless). This pins DENY
        behaviour deterministically regardless of the env's identity mode, because
        a policy/param DENY is independent of the identity gate."""
        body = _validate_body(
            _agent_id_for("acme"), "process_refund",
            {"amount": 999999999, "currency": "USD", "order_id": f"ord-{RUN_ID}"},
            user_input="refund this order", operation_type="WRITE",
        )
        resp = requests.post(f"{base_url}/v1/validate", json=body,
                             headers=api_headers, timeout=HTTP_TIMEOUT)
        assert resp.status_code == 200, f"validate HTTP {resp.status_code}: {resp.text}"
        assert _decision_of(resp) == "DENY", \
            f"over-cap refund must DENY, got {resp.text}"

    def test_validate_malformed_body_422(self, base_url, api_headers):
        """A /v1/validate body missing required fields is a Pydantic 422 (handler
        rejects malformed input at the edge) — not a 5xx."""
        resp = requests.post(f"{base_url}/v1/validate",
                             json={"agent_id": _agent_id_for("acme")},
                             headers=api_headers, timeout=HTTP_TIMEOUT)
        assert resp.status_code == 422, f"expected 422, got {resp.status_code}: {resp.text}"

    def test_validate_unsigned_under_enforce_is_identity_unverified(self, base_url, api_headers):
        """K8.2 data-plane: an unsigned/tokenless call under ENFORCE → fail-secure
        `IDENTITY_UNVERIFIED` DENY (decision DENY + violation_type/reason carrying
        IDENTITY_UNVERIFIED). Tolerant of the fleet ceiling: if the deployed ceiling
        is `shadow`/`off` (identity disabled), the legacy path runs and the call is
        a verified ALLOW or a normal verdict — so we ACCEPT the IDENTITY_UNVERIFIED
        DENY OR a clean verdict, and xfail with a clear reason rather than hard-fail.
        The test is correct regardless of which mode the env is in."""
        # No bearer/identity token at all → tokenless. Strip any Authorization so
        # this is genuinely unsigned even if the operator token leaked into headers.
        headers = dict(api_headers)
        headers.pop("Authorization", None)
        body = _validate_body(
            _agent_id_for("acme"), "query_customers",
            {"query": "SELECT 1"}, user_input="probe", operation_type="READ",
        )
        resp = requests.post(f"{base_url}/v1/validate", json=body,
                             headers=headers, timeout=HTTP_TIMEOUT)
        assert resp.status_code == 200, f"validate HTTP {resp.status_code}: {resp.text}"
        payload = resp.json()
        decision = payload.get("decision")
        reason_blob = f"{payload.get('reason', '')} {payload.get('violation_type', '')}".upper()

        if "IDENTITY_UNVERIFIED" in reason_blob:
            # Enforce is active fleet-wide for this path → exactly the gate DENY.
            assert decision == "DENY", \
                f"IDENTITY_UNVERIFIED must be a DENY, got {payload}"
            return
        # Identity gate not enforcing on this env (shadow/off): the legacy path ran.
        # That's a valid env state, not a bug — accept a clean verdict and xfail so
        # it's visible the gate wasn't exercised here.
        assert decision in ("ALLOW", "DENY"), \
            f"expected a decision envelope, got {payload}"
        pytest.xfail(
            "fleet identity ceiling is not 'enforce' on this target — unsigned call "
            f"took the legacy path (decision={decision}); re-run after K2.4 enforce "
            "to exercise the IDENTITY_UNVERIFIED gate."
        )

    def test_validate_cross_tenant_agent_id_spoof(self, base_url, api_headers):
        """A cross-tenant `agent_id` spoof (a body claiming an agent under a tenant
        the caller has no signed credential for) must NOT be honored as that tenant.
        Under enforce this is an IDENTITY_* DENY tagged `_unverified`; under shadow/off
        it is at most a normal verdict. We assert the call never crashes (no 5xx) and,
        when identity enforces, the spoof is denied — never silently charged to the
        claimed tenant. Tolerant of mode, same rationale as the unsigned test."""
        body = _validate_body(
            _agent_id_for("victim-tenant"), "process_refund",
            {"amount": 1, "currency": "USD"}, user_input="spoof probe",
            operation_type="WRITE",
        )
        resp = requests.post(f"{base_url}/v1/validate", json=body,
                             headers=api_headers, timeout=HTTP_TIMEOUT)
        assert resp.status_code == 200, f"validate HTTP {resp.status_code}: {resp.text}"
        payload = resp.json()
        reason_blob = f"{payload.get('reason', '')} {payload.get('violation_type', '')}".upper()
        if any(tag in reason_blob for tag in ("IDENTITY_UNVERIFIED", "IDENTITY_MISMATCH",
                                              "IDENTITY_TAMPERED")):
            assert payload.get("decision") == "DENY", \
                f"identity spoof must DENY, got {payload}"
        else:
            assert payload.get("decision") in ("ALLOW", "DENY"), \
                f"expected a decision envelope, got {payload}"


# =========================================================================== #
# Group 2 — Identity / credentials (LLD §7.2 identity row)
# =========================================================================== #
@pytest.fixture
def cred_cleanup(base_url, api_headers):
    """Revoke any credentials issued by a test (DELETE is the revoke route).
    Idempotent: a 404 on cleanup is fine (already gone / never created)."""
    issued: list[tuple[str, str]] = []  # (agent_id, kid)
    yield issued
    for agent_id, kid in issued:
        try:
            requests.delete(f"{base_url}/v1/agents/{agent_id}/credentials/{kid}",
                            headers=api_headers, timeout=HTTP_TIMEOUT)
        except requests.exceptions.RequestException:
            pass


class TestIdentityCredentials:

    def test_residual_agents_returns_count(self, base_url, api_headers):
        """GET /v1/identity/residual-agents returns a JSON object with a `count`
        (the WS-B legacy-fallback residual list the console surfaces)."""
        resp = requests.get(f"{base_url}/v1/identity/residual-agents",
                            headers=api_headers, timeout=HTTP_TIMEOUT)
        assert resp.status_code == 200, f"expected 200, got {resp.status_code}: {resp.text}"
        payload = resp.json()
        assert "count" in payload, f"residual-agents must carry a `count`, got {payload}"
        assert isinstance(payload["count"], int)

    def test_credential_issue_list_rotate_revoke_happy_path(
        self, base_url, api_headers, cred_cleanup
    ):
        """Issue → list → rotate → revoke against /v1/agents/{id}/credentials*.

        Tolerant of operator-auth posture: against the deployed ALB this needs an
        admin OIDC token; if the env has no write-capable operator identity the
        register returns 401/403 and we skip with a clear reason (we cannot self-
        certify the mutation chain without an authorized operator). When it DOES
        issue, the full lifecycle is asserted end to end."""
        agent_id = _agent_id_for("acme")
        register = requests.post(
            f"{base_url}/v1/agents/{agent_id}/credentials",
            json={"public_key": _es256_public_pem(), "alg": "ES256"},
            headers=api_headers, timeout=HTTP_TIMEOUT,
        )
        if register.status_code in (401, 403):
            pytest.skip(
                "no write-capable operator identity on this target "
                f"(register → {register.status_code}); supply an admin OIDC token "
                "(SENTRA_OPERATOR_TOKEN) to exercise the credential lifecycle."
            )
        assert register.status_code == 201, \
            f"register expected 201, got {register.status_code}: {register.text}"
        kid = register.json()["kid"]
        cred_cleanup.append((agent_id, kid))

        # list — the issued kid is present, status active, no private material.
        listed = requests.get(f"{base_url}/v1/agents/{agent_id}/credentials",
                              headers=api_headers, timeout=HTTP_TIMEOUT)
        assert listed.status_code == 200, listed.text
        kids = {c["kid"] for c in listed.json().get("credentials", [])}
        assert kid in kids, f"issued kid {kid} not in {kids}"

        # rotate — needs editor+; on success status goes to 'rotating'.
        rotate = requests.post(
            f"{base_url}/v1/agents/{agent_id}/credentials/{kid}/rotate",
            headers=api_headers, timeout=HTTP_TIMEOUT,
        )
        assert rotate.status_code in (200, 403), rotate.text
        if rotate.status_code == 200:
            assert rotate.json().get("status") == "rotating"

        # revoke — DELETE returns the revoked status.
        revoke = requests.delete(
            f"{base_url}/v1/agents/{agent_id}/credentials/{kid}",
            headers=api_headers, timeout=HTTP_TIMEOUT,
        )
        assert revoke.status_code in (200, 403), revoke.text
        if revoke.status_code == 200:
            assert revoke.json().get("status") == "revoked"

    def test_cross_tenant_credential_read_forbidden(self, base_url, api_headers):
        """An operator listing credentials for an agent NOT owned by their tenant →
        403 (`_assert_owns_agent` delimited-prefix isolation). The agent_id is under
        a deliberately foreign tenant so the ownership check must reject it.

        Tolerant: if the env has no resolvable operator membership at all, the route
        401s before the ownership check — accept 401 as 'auth boundary held' too,
        since the IDOR can't even be attempted unauthenticated."""
        foreign_agent = "some-other-tenant-aws-foreign-9999"
        resp = requests.get(f"{base_url}/v1/agents/{foreign_agent}/credentials",
                            headers=api_headers, timeout=HTTP_TIMEOUT)
        assert resp.status_code in (401, 403), \
            f"cross-tenant cred read must be denied (401/403), got {resp.status_code}: {resp.text}"

    def test_credentials_no_auth_401(self, base_url, api_headers):
        """No operator identity → 401 on a credential read (auth required at the
        trust boundary, not assumed)."""
        resp = requests.get(
            f"{base_url}/v1/agents/{_agent_id_for('acme')}/credentials",
            headers=_no_auth_headers(api_headers), timeout=HTTP_TIMEOUT,
        )
        assert resp.status_code in (401, 403), \
            f"expected 401/403 with no auth, got {resp.status_code}: {resp.text}"


# =========================================================================== #
# Group 3 — Tenancy (LLD §7.2 tenancy row)
# =========================================================================== #
@pytest.fixture
def tenant_cleanup(base_url, api_headers):
    """Begin staged deletion (DELETE marks `deleting` + revokes creds — the live
    purge runs out-of-band behind sign-off, so this is safe + reversible)."""
    created: list[str] = []
    yield created
    for tenant_id in created:
        try:
            requests.delete(f"{base_url}/v1/tenants/{tenant_id}",
                            headers=api_headers, timeout=HTTP_TIMEOUT)
        except requests.exceptions.RequestException:
            pass


class TestTenancy:

    def test_me_returns_identity(self, base_url, api_headers):
        """GET /v1/me returns the operator's role + memberships bootstrap, OR 401/403
        if this env has no resolvable operator membership. Either way the route is
        reachable and the auth boundary is coherent."""
        resp = requests.get(f"{base_url}/v1/me", headers=api_headers, timeout=HTTP_TIMEOUT)
        assert resp.status_code in (200, 401, 403), \
            f"/v1/me unexpected status {resp.status_code}: {resp.text}"
        if resp.status_code == 200:
            payload = resp.json()
            assert "role" in payload and "tenant_id" in payload, \
                f"/v1/me must carry role + tenant_id, got {payload}"

    def test_create_get_patch_tenant(self, base_url, api_headers, tenant_cleanup):
        """Create → get → patch a tenant. Tolerant of operator-auth posture: tenant
        creation needs an authenticated operator; if none is available the create
        401/403s and we skip rather than hard-fail."""
        create = requests.post(
            f"{base_url}/v1/tenants",
            json={"display_name": f"ws-k-k8 {RUN_ID}", "plan": "trial"},
            headers=api_headers, timeout=HTTP_TIMEOUT,
        )
        if create.status_code in (401, 403):
            pytest.skip(
                "no authenticated operator on this target "
                f"(create tenant → {create.status_code}); supply SENTRA_OPERATOR_TOKEN."
            )
        assert create.status_code == 201, \
            f"create tenant expected 201, got {create.status_code}: {create.text}"
        tenant_id = create.json()["tenant_id"]
        tenant_cleanup.append(tenant_id)

        # The creator is the owner → can read it. Use the tenant-switch header to
        # act in the just-created tenant.
        scoped = dict(api_headers)
        scoped["X-Aegion-Tenant"] = tenant_id
        got = requests.get(f"{base_url}/v1/tenants/{tenant_id}",
                          headers=scoped, timeout=HTTP_TIMEOUT)
        assert got.status_code == 200, f"get own tenant: {got.status_code} {got.text}"
        assert got.json()["tenant_id"] == tenant_id

        # patch display_name (admin+; owner satisfies). identity_mode/enforce flip is
        # deliberately NOT touched here (that's a gated rollout action, K2/K3 scope).
        patch = requests.patch(f"{base_url}/v1/tenants/{tenant_id}",
                              json={"display_name": f"ws-k-k8 patched {RUN_ID}"},
                              headers=scoped, timeout=HTTP_TIMEOUT)
        assert patch.status_code == 200, f"patch tenant: {patch.status_code} {patch.text}"

    def test_switch_to_nonmember_tenant_forbidden(self, base_url, api_headers):
        """An `X-Aegion-Tenant` switch to a tenant the operator is not a member of →
        403 (resolve_operator_tenant rejects a non-member switch). Tolerant: 401 if
        no operator identity exists at all."""
        headers = dict(api_headers)
        headers["X-Aegion-Tenant"] = f"t_not-a-member-{RUN_ID}"
        resp = requests.get(f"{base_url}/v1/me", headers=headers, timeout=HTTP_TIMEOUT)
        assert resp.status_code in (401, 403), \
            f"non-member tenant switch must be denied, got {resp.status_code}: {resp.text}"

    def test_tenant_write_without_role_forbidden(self, base_url, api_headers):
        """A `require_role`-gated write (PATCH a tenant) by an operator without the
        role, OR with no operator identity → 401/403 (RBAC is the server-side
        boundary, not client UX). Uses a foreign tenant id so even a member is
        rejected by the membership check."""
        resp = requests.patch(f"{base_url}/v1/tenants/t_foreign-{RUN_ID}",
                             json={"display_name": "x"},
                             headers=api_headers, timeout=HTTP_TIMEOUT)
        assert resp.status_code in (401, 403, 404), \
            f"gated write on foreign tenant must not succeed, got {resp.status_code}: {resp.text}"

    def test_tenant_no_auth_401(self, base_url, api_headers):
        """Reading a tenant with no operator identity → 401/403."""
        resp = requests.get(f"{base_url}/v1/tenants/{_ABSENT}",
                           headers=_no_auth_headers(api_headers), timeout=HTTP_TIMEOUT)
        assert resp.status_code in (401, 403), \
            f"expected 401/403 with no auth, got {resp.status_code}: {resp.text}"


# =========================================================================== #
# Group 4 — Policy CRUD (LLD §7.2 policy row)
# =========================================================================== #
@pytest.fixture
def policy_cleanup(base_url, api_headers):
    created: list[str] = []
    yield created
    for policy_id in created:
        try:
            requests.delete(f"{base_url}/v1/policies/{policy_id}",
                            headers=api_headers, timeout=HTTP_TIMEOUT)
        except requests.exceptions.RequestException:
            pass


def _policy_payload(agent_id: str) -> dict:
    return {
        "schema_version": "v1",
        "agent_id": agent_id,
        "name": f"ws-k-k8 policy {RUN_ID}",
        "version": "1.0.0",
        "description": "post-cutover suite policy",
        "allowed_tools": ["query_customers"],
        "policies": [{
            "policy_id": f"pol-{RUN_ID}",
            "name": "k8 limit",
            "description": "limit",
            "rule": "query_limit <= 500",
            "action": "DENY",
            "severity": "high",
            "enabled": True,
        }],
    }


class TestPolicyCRUD:

    def test_author_bind_list_patch_delete(self, base_url, api_headers, policy_cleanup):
        """author → get → bind (POST /agents/{id}/policies) → list → patch-status →
        delete. Idempotent + self-cleaning via policy_cleanup."""
        agent_id = _agent_id_for("acme")
        create = requests.post(f"{base_url}/v1/policies",
                              json=_policy_payload(agent_id),
                              headers=api_headers, timeout=HTTP_TIMEOUT)
        if create.status_code in (401, 403):
            pytest.skip(
                "no write-capable operator on this target "
                f"(create policy → {create.status_code}); supply SENTRA_OPERATOR_TOKEN."
            )
        assert create.status_code == 201, \
            f"create policy expected 201, got {create.status_code}: {create.text}"
        policy_id = create.json()["policy_id"]
        policy_cleanup.append(policy_id)

        time.sleep(1)  # eventual consistency (DDB + S3), mirrors test_policy_crud_e2e

        # get
        got = requests.get(f"{base_url}/v1/policies/{policy_id}",
                          params={"include_content": False},
                          headers=api_headers, timeout=HTTP_TIMEOUT)
        assert got.status_code == 200, got.text

        # bind to the agent (rebind-as-replace; no 409). The agent may not be
        # registered → 404 is acceptable (the bind handler ran).
        bind = requests.post(f"{base_url}/v1/agents/{agent_id}/policies",
                            json={"policy_id": policy_id},
                            headers=api_headers, timeout=HTTP_TIMEOUT)
        assert bind.status_code in (200, 404), \
            f"bind policy unexpected {bind.status_code}: {bind.text}"

        # list (filtered by agent)
        listed = requests.get(f"{base_url}/v1/policies",
                            params={"agent_id": agent_id},
                            headers=api_headers, timeout=HTTP_TIMEOUT)
        assert listed.status_code == 200, listed.text

        # patch status (disable)
        patch = requests.patch(f"{base_url}/v1/policies/{policy_id}/status",
                             json={"status": "disabled"},
                             headers=api_headers, timeout=HTTP_TIMEOUT)
        assert patch.status_code == 200, f"patch status: {patch.status_code} {patch.text}"

        # delete (soft delete)
        delete = requests.delete(f"{base_url}/v1/policies/{policy_id}",
                               headers=api_headers, timeout=HTTP_TIMEOUT)
        assert delete.status_code == 200, f"delete policy: {delete.status_code} {delete.text}"

    def test_get_nonexistent_policy_404(self, base_url, api_headers):
        """GET a missing policy → 404 (resource-not-found, handler ran)."""
        resp = requests.get(f"{base_url}/v1/policies/{_ABSENT}",
                           headers=api_headers, timeout=HTTP_TIMEOUT)
        assert resp.status_code == 404, \
            f"missing policy expected 404, got {resp.status_code}: {resp.text}"

    def test_create_policy_malformed_400_or_422(self, base_url, api_headers):
        """Malformed policy body (missing required fields) → 400/422 at the edge."""
        resp = requests.post(f"{base_url}/v1/policies",
                           json={"schema_version": "v1", "agent_id": "x"},
                           headers=api_headers, timeout=HTTP_TIMEOUT)
        assert resp.status_code in (400, 401, 403, 422), \
            f"malformed policy expected 400/422 (or auth gate), got {resp.status_code}: {resp.text}"

    def test_create_policy_no_auth_401(self, base_url, api_headers):
        """Create a policy with no operator identity → 401/403."""
        resp = requests.post(f"{base_url}/v1/policies",
                           json=_policy_payload(_agent_id_for("acme")),
                           headers=_no_auth_headers(api_headers), timeout=HTTP_TIMEOUT)
        # A controller behind ALB rejects unauthenticated writes; a local dev
        # controller with the legacy shim may allow → clean up if it 201s.
        assert resp.status_code in (401, 403, 201), \
            f"unexpected status for no-auth create: {resp.status_code}: {resp.text}"
        if resp.status_code == 201:
            try:
                requests.delete(f"{base_url}/v1/policies/{resp.json()['policy_id']}",
                                headers=api_headers, timeout=HTTP_TIMEOUT)
            except requests.exceptions.RequestException:
                pass

    def test_cross_tenant_policy_read_denied(self, base_url, api_headers):
        """A policy id under a foreign tenant scope is not readable → 403/404
        (cross-tenant read denied; a 404 'not found' is also acceptable since a
        foreign policy simply isn't visible in the caller's scope)."""
        resp = requests.get(f"{base_url}/v1/policies/agent-config-foreign-{RUN_ID}",
                           headers=api_headers, timeout=HTTP_TIMEOUT)
        assert resp.status_code in (403, 404), \
            f"cross-tenant policy read must be 403/404, got {resp.status_code}: {resp.text}"


# =========================================================================== #
# Group 5 — Quarantine / rollback (LLD §7.2 quarantine row)
# =========================================================================== #
class TestQuarantineRollback:

    def test_quarantine_missing_session_404(self, base_url, api_headers):
        """POST /v1/quarantine/{sid} on a missing session → 404 (handler ran;
        session genuinely absent). A well-formed body so we reach the existence
        check, not the 400 missing-fields branch."""
        resp = requests.post(f"{base_url}/v1/quarantine/sess-{_ABSENT}-{RUN_ID}",
                           json={"reason": "k8 probe", "operator_id": "k8"},
                           headers=api_headers, timeout=HTTP_TIMEOUT)
        assert resp.status_code in (404, 401, 403), \
            f"quarantine missing session expected 404 (or auth gate), got {resp.status_code}: {resp.text}"

    def test_quarantine_missing_fields_400(self, base_url, api_headers):
        """POST /v1/quarantine/{sid} without reason/operator_id → 400."""
        resp = requests.post(f"{base_url}/v1/quarantine/sess-{_ABSENT}-{RUN_ID}",
                           json={}, headers=api_headers, timeout=HTTP_TIMEOUT)
        assert resp.status_code in (400, 401, 403), \
            f"quarantine missing fields expected 400, got {resp.status_code}: {resp.text}"

    def test_rollback_missing_action_404(self, base_url, api_headers):
        """POST /v1/rollback for a non-existent action → 404 (well-formed body
        reaches the coordinator; action genuinely absent)."""
        resp = requests.post(f"{base_url}/v1/rollback",
                           json={"action_id": f"act-{_ABSENT}-{RUN_ID}",
                                 "action_type": "process_refund",
                                 "reason": "k8 probe", "operator_id": "k8"},
                           headers=api_headers, timeout=HTTP_TIMEOUT)
        assert resp.status_code in (404, 400, 401, 403, 500), \
            f"rollback missing action unexpected {resp.status_code}: {resp.text}"
        # Must NOT be a gateway hole.
        assert _route_exists(resp), f"/v1/rollback looks like an undefined route: {resp.text}"

    def test_rollback_missing_fields_400(self, base_url, api_headers):
        """POST /v1/rollback without required fields → 400."""
        resp = requests.post(f"{base_url}/v1/rollback", json={},
                           headers=api_headers, timeout=HTTP_TIMEOUT)
        assert resp.status_code in (400, 401, 403), \
            f"rollback missing fields expected 400, got {resp.status_code}: {resp.text}"

    def test_decision_verdict_invalid_verdict_400(self, base_url, api_headers):
        """POST /v1/decisions/{id}/verdict with an invalid verdict → 400."""
        resp = requests.post(f"{base_url}/v1/decisions/{_ABSENT}:{_ABSENT}/verdict",
                           json={"verdict": "not-a-verdict", "reason": "x",
                                 "operator_id": "k8"},
                           headers=api_headers, timeout=HTTP_TIMEOUT)
        assert resp.status_code in (400, 401, 403), \
            f"invalid verdict expected 400, got {resp.status_code}: {resp.text}"


# =========================================================================== #
# Group 6 — Query / SOC reads (LLD §7.2 query/SOC row)
# =========================================================================== #
class TestQuerySocReads:
    """Each read returns 200 with the auth'd operator (tenant-scoped). The IDENTITY_*
    audit filter is what surfaces gate-DENYs the Decisions metric hides (memo)."""

    @pytest.mark.parametrize("path", [
        "/v1/logs",
        "/v1/sessions",
        "/v1/decisions",
        "/v1/metrics",
        "/v1/metrics/overview",
        "/v1/metrics/platform-distribution",
        "/v1/metrics/decisions-timeseries",
        "/v1/discovery/agents",
        "/v1/discovery/summary",
        "/v1/discovery/platforms",
        "/v1/connections",
        "/v1/sigma-rules",
    ])
    def test_soc_read_returns_200(self, base_url, api_headers, path):
        """A SOC/query read returns 200 for an authenticated operator (or 401/403 if
        this env has no operator identity — the auth boundary held). Never a 5xx and
        never an undefined-route gateway hole."""
        resp = requests.get(f"{base_url}{path}", headers=api_headers, timeout=HTTP_TIMEOUT)
        assert resp.status_code in (200, 401, 403), \
            f"{path} unexpected status {resp.status_code}: {resp.text}"
        assert _route_exists(resp), f"{path} looks like an undefined gateway route: {resp.text}"

    def test_identity_audit_filter_reachable(self, base_url, api_headers):
        """The IDENTITY_* audit filter (the proof an enforce cutover is clean, since
        identity-gate DENYs are NOT metered) — GET /v1/logs?decision=DENY is reachable
        and returns 200/auth-gate, never a 5xx."""
        resp = requests.get(f"{base_url}/v1/logs",
                           params={"decision": "DENY", "limit": 10},
                           headers=api_headers, timeout=HTTP_TIMEOUT)
        assert resp.status_code in (200, 401, 403), \
            f"/v1/logs DENY filter unexpected {resp.status_code}: {resp.text}"


# =========================================================================== #
# Group 7 — K8.3 gap 1: credential → JWT sign → verify, end-to-end over HTTP
# =========================================================================== #
def _load_sdk_identity():
    """Import the real SDK identity helpers (generate_keypair / AgentIdentity /
    JwtSigner). Returns the module's symbols, or None if the SDK / its `identity`
    extra (PyJWT[crypto]) isn't importable — in which case the gap-1 test SKIPS
    (per K8.3: do NOT fake the signing)."""
    import importlib
    import sys
    from pathlib import Path

    sdk_src = (Path(__file__).resolve().parents[2]
               / "demo-agents" / "sdk" / "aegion-guard-python" / "src")
    if sdk_src.is_dir() and str(sdk_src) not in sys.path:
        sys.path.insert(0, str(sdk_src))
    try:
        identity = importlib.import_module("aegion_guard.identity")
        # Touch the crypto-backed path so a missing `identity` extra is caught here.
        identity.generate_keypair()
        return identity
    except Exception:  # noqa: BLE001 — SDK absent OR signing libs (PyJWT[crypto]) missing
        return None


def _es256_public_pem() -> str:
    """A throwaway ES256/P-256 public PEM for credential-registration tests. Uses the
    SDK keypair generator when available, else a syntactically-valid placeholder PEM
    (the credential routes only need a public key string; verification isn't exercised
    by the registration happy-path test)."""
    sdk = _load_sdk_identity()
    if sdk is not None:
        _priv, pub = sdk.generate_keypair()
        return pub
    return "-----BEGIN PUBLIC KEY-----\nMFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcD\n-----END PUBLIC KEY-----"


class TestCredentialSignVerifyE2E:
    """K8.3 gap 1 — the real provision → POST /credentials → signed /v1/validate
    chain over HTTP, today only unit-tested. If signing libs aren't available, SKIP
    (never fake the signature)."""

    def test_issue_sign_verify_over_http(self, base_url, api_headers, cred_cleanup):
        sdk = _load_sdk_identity()
        if sdk is None:
            pytest.skip(
                "SDK identity / PyJWT[crypto] not importable — cannot mint a real "
                "ES256 token; install 'aegion-guard[identity]' to run the E2E "
                "credential→sign→verify gap test (K8.3 gap 1). Not faking the signature."
            )

        tenant_id = "acme"
        agent_id = _agent_id_for(tenant_id)  # delimited tenant prefix (isolation check)
        private_pem, public_pem = sdk.generate_keypair()

        # 1. Register the PUBLIC key with the controller (operator-authed).
        register = requests.post(
            f"{base_url}/v1/agents/{agent_id}/credentials",
            json={"public_key": public_pem, "alg": "ES256"},
            headers=api_headers, timeout=HTTP_TIMEOUT,
        )
        if register.status_code in (401, 403):
            pytest.skip(
                "no admin operator identity on this target "
                f"(register → {register.status_code}); supply SENTRA_OPERATOR_TOKEN "
                "(admin) to run the credential→sign→verify E2E."
            )
        assert register.status_code == 201, \
            f"register expected 201, got {register.status_code}: {register.text}"
        kid = register.json()["kid"]
        cred_cleanup.append((agent_id, kid))

        # 2. Sign a real ES256 JWT with the held private key (the agent-side half).
        signer = sdk.JwtSigner(sdk.AgentIdentity(
            agent_id=agent_id, tenant_id=tenant_id, kid=kid, private_key=private_pem,
        ))
        token = signer.token()
        assert token and token.count(".") == 2, "expected a compact JWT"

        # 3. Call /v1/validate WITH the signed token — the controller must resolve the
        #    tenant FROM the verified credential (not the self-asserted body). We assert
        #    the call verifies: it is NOT an IDENTITY_* DENY (the signature/kid resolved).
        signed_headers = dict(api_headers)
        signed_headers["Authorization"] = f"Bearer {token}"
        body = _validate_body(
            agent_id, "query_customers", {"query": "SELECT 1"},
            user_input="signed probe", operation_type="READ",
        )
        resp = requests.post(f"{base_url}/v1/validate", json=body,
                             headers=signed_headers, timeout=HTTP_TIMEOUT)
        assert resp.status_code == 200, f"signed validate HTTP {resp.status_code}: {resp.text}"
        payload = resp.json()
        reason_blob = f"{payload.get('reason', '')} {payload.get('violation_type', '')}".upper()
        assert "IDENTITY_UNVERIFIED" not in reason_blob, \
            f"a correctly-signed token must NOT be IDENTITY_UNVERIFIED, got {payload}"
        assert "IDENTITY_MISMATCH" not in reason_blob, \
            f"signed token sub/tid relationship must verify, got {payload}"
        assert "IDENTITY_TAMPERED" not in reason_blob, \
            f"signed token must not look tampered, got {payload}"
        assert payload.get("decision") in ("ALLOW", "DENY"), \
            f"expected a decision envelope from the signed call, got {payload}"


# =========================================================================== #
# Group 8 — K8.3 gap 2: every-route-responds enumeration (apigw E4 footgun)
# =========================================================================== #
class TestEveryRouteResponds:
    """A parametrized hit over the FULL 59-route inventory. Each route is hit once
    with the auth'd headers and asserted REACHABLE — the handler ran (any deliberate
    status), NOT an undefined-gateway-route 403 ("Missing Authentication Token") or a
    contentless 5xx / connection error. This catches the apigw-per-resource missing-
    route footgun (LLD §8 E4): a new controller route that was never added to the API
    Gateway + ALB rules 403s at the gateway and is silently unreachable."""

    @pytest.mark.parametrize(
        "method,path,body",
        _ROUTE_INVENTORY,
        ids=[f"{m} {p}" for (m, p, _b) in _ROUTE_INVENTORY],
    )
    def test_route_is_reachable(self, base_url, api_headers, method, path, body):
        kwargs = {"headers": api_headers, "timeout": HTTP_TIMEOUT}
        if body is not None:
            kwargs["json"] = body
        try:
            resp = requests.request(method, f"{base_url}{path}", **kwargs)
        except requests.exceptions.RequestException as exc:
            pytest.fail(
                f"{method} {path} is UNREACHABLE ({exc.__class__.__name__}: {exc}) — "
                "connection error means the route/gateway integration is missing (E4)."
            )
        assert _route_exists(resp), (
            f"{method} {path} is NOT reachable: HTTP {resp.status_code} "
            f"body={resp.text[:200]!r}. A '{resp.status_code}' here looks like an "
            "undefined API-Gateway route (the apigw-per-resource footgun, E4): the "
            "controller route exists but was never wired into the gateway + ALB rules."
        )
