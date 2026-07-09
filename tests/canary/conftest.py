"""WS-J J1 — transport-parameterized fixtures + pytest markers.

The ONE place ``CANARY_TARGET`` is read (lld/38 §3.1). Scenario functions are
transport-agnostic (enforced by Jc.2's transport-purity lint). Extends — never
re-declares — the ``tests/integration/conftest.py`` ``service_urls``/``aws_config``
fixtures (imported below).

Hermetic-by-default: the in-process client backs the FastAPI app with a real
``DenyOverrides``-combiner validation service (so an ALLOW/DENY is a GENUINE
combiner verdict carrying ``metadata.winning_source``, not a mock) and moto for
any AWS the query/mutation routes touch. No real AWS, no real PII, no network.
"""
from __future__ import annotations

import importlib.util
import os
import pathlib
import uuid
from typing import Any, Dict, Optional

import pytest

# Extend (do NOT re-declare) the shared integration fixtures — the J1.1 hard rule.
# `tests/` is not an importable package (no tests/__init__.py + PYTHONPATH points at
# the controller pkg), so load the integration conftest by file path and re-export
# its `service_urls`/`aws_config` fixtures rather than re-declaring them.
_integration_conftest = pathlib.Path(__file__).resolve().parents[1] / "integration" / "conftest.py"
_spec = importlib.util.spec_from_file_location("_canary_integration_conftest", _integration_conftest)
_int_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_int_mod)  # type: ignore[union-attr]
service_urls = _int_mod.service_urls  # noqa: F811  (re-exported fixture)
aws_config = _int_mod.aws_config      # noqa: F811  (re-exported fixture)

CANARY_TARGET_ENV = "CANARY_TARGET"
CANARY_SENTINEL = "CANARY-PII-7F3A"  # Invariant 6 — the only sensitive marker.


# ------------------------------------------------------------ live-collection guard
# The lean LIVE container (docker/canary/Dockerfile) installs ONLY httpx/boto3/pytest/
# pytest-cov — NO fastapi, NO pydantic, NO aegion_guard SDK, and does NOT COPY the whole
# controller package as an importable tree the heavy modules need. The hourly monitor
# runs ONLY the black-box scenarios that hit the deployed API Gateway over httpx
# (test_all_routes.py's all-route sweep + test_metrics_live.py's requires_live metric
# checks). Every other module (app-standing-up / meta / harness-unit) does a heavy
# module-LEVEL import (app.* / aegion_guard / fastapi / pydantic / moto) that the lean
# container CANNOT satisfy — collecting them would raise ModuleNotFoundError AT
# COLLECTION, erroring the WHOLE run before any scenario executes → emit_run_metrics
# never fires → ChecksPassed/Failed=0 → the ChecksFailed alarm (TreatMissingData.
# BREACHING) fires PERMANENTLY (the false-alarm gap integration-sentinel found).
#
# So in live mode we collect EXACTLY the two live-safe scenario modules; the rest are
# INPROCESS/BUILD-TIME only. In inprocess mode (the 193-pass PR gate) we collect
# everything — collect_ignore stays empty. test_live_collection_lean.py asserts the
# live-collected set imports only the lean allowlist, so a future app-importing test
# added to the live set is caught in the PR gate, not in prod.
_LIVE_SAFE_MODULES = frozenset({
    "test_all_routes.py",         # P0-1 all-route positive/negative sweep (pure httpx)
    "test_metrics_live.py",       # requires_live metric checks (pure httpx)
    "test_oidc_routes_live.py",   # J8.4 no-identity 401 sweep of the oidc lane (pure httpx)
    "test_console_authed_oidc.py",  # J8.1-J8.4 Playwright login + authed legs (browser;
                                     # import-guarded so a browserless run skips, not errors)
})


def _live_collect_ignore(canary_dir: "pathlib.Path") -> list:
    """The set of ``test_*.py`` module names pytest must IGNORE in live mode: every
    module on disk EXCEPT the live-safe scenario modules. A pure function so the
    regression guard (test_live_collection_lean.py) can assert the SAME wiring the
    runtime branch below uses — reverting the branch is caught by that test."""
    return sorted(
        p.name
        for p in canary_dir.glob("test_*.py")
        if p.name not in _LIVE_SAFE_MODULES
    )


# Only the two live-safe scenario modules are collected against a live target; every
# other test_*.py is inprocess/build-time and must NOT be collected in the lean
# container. Populated at import time (module-level, when pytest reads this conftest).
collect_ignore: list = []
if os.environ.get(CANARY_TARGET_ENV, "inprocess") == "live":
    collect_ignore = _live_collect_ignore(pathlib.Path(__file__).resolve().parent)


# --------------------------------------------------------------------------- markers
def pytest_configure(config: "pytest.Config") -> None:
    """Register the WS-J markers so ``-m "not requires_live and not pr_gate_only"``
    resolves cleanly (no unknown-marker warnings → error under -W)."""
    config.addinivalue_line(
        "markers",
        "requires_live: scenario needs a live deployed target (SENTRA_API_GW_URL); "
        "skipped in the hermetic PR-gate run.",
    )
    config.addinivalue_line(
        "markers",
        "pr_gate_only: scenario runs only in the in-process PR-gate, never the "
        "hourly prod monitor (e.g. billing-hygiene J5).",
    )


# --------------------------------------------------------------------------- client
class CanaryClient:
    """Thin transport adapter over an in-process ``TestClient`` OR a live
    ``httpx.Client`` (lld/38 §3.1 / J1.1). Exposes ``.get/.post/.put/.delete/
    .patch``, a fresh per-call ``X-Correlation-Id`` (the RCA join key, §9), a
    ``.correlation_id`` of the last call, ``.latency_ms``, and a ``mode`` attr.
    """

    def __init__(self, inner: Any, mode: str) -> None:
        assert mode in ("inprocess", "live")
        self._inner = inner
        self.mode = mode
        self._last_correlation_id: Optional[str] = None
        self.latency_ms: Optional[float] = None

    @property
    def correlation_id(self) -> Optional[str]:
        return self._last_correlation_id

    def _call(self, verb: str, path: str, **kwargs: Any):
        import time as _time

        cid = uuid.uuid4().hex
        self._last_correlation_id = cid
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("X-Correlation-Id", cid)
        # drop_api_key (J2.4 "401" axis / J8): actually remove the X-Api-Key for THIS
        # request so the missing-key→401/403 edge gate is really exercised. In live mode
        # the key is an httpx.Client DEFAULT header, so a per-request override must send
        # an empty value (API Gateway treats an empty/absent key as unauthenticated →
        # 403). Without this the default key would still be sent and the probe would be
        # a no-op (the dead-param bug the review found).
        if kwargs.pop("drop_api_key", False):
            headers["X-Api-Key"] = ""
        t0 = _time.perf_counter()
        if self.mode == "live":
            # A LIVE transport error with NO HTTP response (DNS/conn-reset/timeout) is
            # a transient blip, NOT a product failure: bounded-retry then raise
            # InfraError → the reporting plugin classifies INFRA, never FAIL (§9.1).
            # A deterministic assertion failure is NEVER retried (it is not raised here).
            from canary.reporting_plugin import record_service_5xx, retry_transport

            # Two kinds of "5xx" must NOT be conflated (prod incident 2026-07-05: a
            # single transient 502 hard-failed the run + paged):
            #   * GATEWAY 5xx (502 Bad Gateway / 503 Unavailable / 504 Timeout) — the
            #     EDGE could not reach the backend. Same class as a no-response transport
            #     error: transient/infra. RETRY it (bounded); only a PERSISTENT gateway
            #     5xx (all retries fail) falls through to the assertion.
            #   * A true APP 500 (transport succeeded, the controller itself erred) — a
            #     real product FAIL that pages the critical topic (ProductFivexxFail).
            _GATEWAY_5XX = (502, 503, 504)

            def _once():
                r = getattr(self._inner, verb)(path, headers=headers, **kwargs)
                if getattr(r, "status_code", 0) in _GATEWAY_5XX:
                    # raise so retry_transport re-attempts (same path as a conn error);
                    # on the FINAL attempt retry_transport returns the last response.
                    from canary.reporting_plugin import TransportRetryable
                    raise TransportRetryable(r)
                return r

            resp = retry_transport(_once)
            # A genuine app-returned 500 (NOT a gateway 502/503/504) is a product FAIL
            # that ALSO pages the critical topic (ProductFivexxFail, §9.1) — record it
            # before the scenario's status assertion raises. A persistent gateway 5xx
            # that exhausted retries also lands here (a real edge outage IS a failure).
            if getattr(resp, "status_code", 0) >= 500:
                record_service_5xx()
        else:
            resp = getattr(self._inner, verb)(path, headers=headers, **kwargs)
        self.latency_ms = (_time.perf_counter() - t0) * 1000.0
        return resp

    def get(self, path: str, **kw: Any):
        return self._call("get", path, **kw)

    def post(self, path: str, **kw: Any):
        return self._call("post", path, **kw)

    def put(self, path: str, **kw: Any):
        return self._call("put", path, **kw)

    def delete(self, path: str, **kw: Any):
        return self._call("delete", path, **kw)

    def patch(self, path: str, **kw: Any):
        return self._call("patch", path, **kw)


def _load_secret(secret_id: str) -> str:
    """Fetch a secret string from Secrets Manager (live-mode only, J1.1)."""
    import boto3

    sm = boto3.client("secretsmanager")
    return sm.get_secret_value(SecretId=secret_id)["SecretString"]


@pytest.fixture
def canary_client(request):
    """The transport switch. Reads ``CANARY_TARGET`` HERE and nowhere else.

    * ``inprocess`` (default): a ``TestClient(app)`` whose ``validation_service``
      runs the REAL ``DenyOverrides`` combiner (real ``metadata.winning_source``),
      under a moto AWS mock so query/mutation routes don't touch real AWS.
    * ``live``: an ``httpx.Client`` against ``SENTRA_API_GW_URL`` carrying the
      ``X-Api-Key`` from ``sentra/canary/api-key`` (8 s per-call timeout, §12).
    """
    target = os.environ.get(CANARY_TARGET_ENV, "inprocess")
    if target == "inprocess":
        from canary._inprocess import build_inprocess_client

        yield from build_inprocess_client()
        return

    import httpx

    base = os.environ["SENTRA_API_GW_URL"]
    key = _load_secret("sentra/canary/api-key")
    client = httpx.Client(base_url=base, headers={"X-Api-Key": key}, timeout=8.0)
    try:
        yield CanaryClient(client, mode="live")
    finally:
        client.close()


# --------------------------------------------------------------------------- tenant
@pytest.fixture
def canary_tenant():
    """J1.2 — an ephemeral ``canary-<uuid4hex>`` tenant (prod-write hygiene, §11).

    Yields the id; seeds one ``sentra-tenant-members`` row for it (in live mode
    over moto/real; in the hermetic inprocess run the seed is best-effort against
    the moto tables the inprocess client stands up). Teardown is best-effort +
    idempotent — a teardown failure logs, NEVER reds the run (§11). NEVER targets
    the real ``acme-*`` fleet / prod ``sentra-meter-events`` / real-operator rows.
    """
    tid = f"canary-{uuid.uuid4().hex}"
    seeded = _seed_tenant_member(tid)
    try:
        yield tid
    finally:
        if seeded:
            _teardown_tenant_member(tid)


def _seed_tenant_member(tenant_id: str) -> bool:
    """Best-effort seed of one members row. Returns True if a row was written."""
    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    try:
        from app.config import settings

        ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
        # PK = operator_sub (HASH) + tenant_id (RANGE), mirroring the CDK schema
        # (mt_helpers.create_mt_tables). SEC-7: viewer only, never _platform.
        ddb.Table(settings.dynamodb_tenant_members_table).put_item(
            Item={
                "operator_sub": f"canary-op-{uuid.uuid4().hex[:8]}",
                "tenant_id": tenant_id,
                "role": "viewer",
                "is_primary": True,
            }
        )
        return True
    except (ClientError, BotoCoreError, KeyError, Exception):  # noqa: BLE001
        return False


def _teardown_tenant_member(tenant_id: str) -> None:
    """Idempotent best-effort delete. A failure logs but never reds the run."""
    import logging

    import boto3
    from botocore.exceptions import BotoCoreError, ClientError

    try:
        from app.config import settings

        ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
        table = ddb.Table(settings.dynamodb_tenant_members_table)
        # Query the tenant-members-index GSI (keyed on tenant_id) then delete by the
        # base composite key (operator_sub HASH + tenant_id RANGE).
        resp = table.query(
            IndexName="tenant-members-index",
            KeyConditionExpression="tenant_id = :t",
            ExpressionAttributeValues={":t": tenant_id},
        )
        for item in resp.get("Items", []):
            table.delete_item(
                Key={"operator_sub": item["operator_sub"], "tenant_id": tenant_id}
            )
    except (ClientError, BotoCoreError, Exception):  # noqa: BLE001
        logging.getLogger("canary").info(
            "canary tenant teardown best-effort skip for %s", tenant_id
        )


# --------------------------------------------------------------------------- operator
def _seed_member_row(operator_sub: str, tenant_id: str, role: str) -> bool:
    """Seed ONE ``sentra-tenant-members`` row (``operator_sub`` PK / ``tenant_id`` SK)
    with the given role. Customer roles (owner|admin|editor|viewer) go through the
    service ``MemberStore.add`` (VALID_ROLES-checked, create-only). The reserved
    ``_platform`` role is NOT in VALID_ROLES, so it is written directly via put_item
    into the ``_platform`` tenant partition. Returns True on success; best-effort —
    a moto/table absence returns False rather than reddening a scenario at collection."""
    try:
        from app.services.tenant_service import get_member_store

        store = get_member_store()
        if role == "_platform":
            store._table().put_item(
                Item={
                    "operator_sub": operator_sub,
                    "tenant_id": tenant_id,
                    "role": "_platform",
                    "is_primary": False,
                }
            )
        else:
            store.add(
                operator_sub=operator_sub, tenant_id=tenant_id, role=role,
                is_primary=True,
            )
        return True
    except Exception:  # noqa: BLE001 — best-effort seed; caller asserts on the result.
        return False


class _OperatorMinter:
    """J7 (WS-M authz) — a factory that mints a VERIFIED operator identity at a chosen
    role in a chosen tenant, INPROCESS ONLY. Installs ``deps._alb_claims_override``
    (the ALB-OIDC test seam, [deps.py:301](../../src/security-controller/app/api/deps.py#L301))
    so ``verify_alb_oidc`` returns the synthetic claims, AND seeds the matching
    ``sentra-tenant-members`` row so ``resolve_operator_tenant`` finds a real primary
    membership (WITHOUT a seeded row a minted operator 403s at membership resolution —
    the bug the old fixture's docstring claimed to fix but did not). Every mint is
    torn down (override reset + best-effort member-row delete) at fixture teardown.

    ``_platform`` mints a reserved cross-tenant membership (for the ``require_platform``
    sigma route). This is a TEST seam confined to the fixture — never a scenario body
    (transport-purity, Jc.2), and it does NOT exist on the deployed service, so J7's
    authorized/role/IDOR legs are ``inprocess``-only (``live`` = J8, the Cognito
    hosted-UI login fixture). Mirrors the documented J3.3/J4.2 live-weaker exceptions."""

    def __init__(self, deps_mod) -> None:
        self._deps = deps_mod
        self._prev = deps_mod._alb_claims_override
        self._minted = []  # (operator_sub, tenant_id) for teardown

    def mint(self, tenant_id: str, role: str = "editor") -> Dict[str, str]:
        from app.utils import tenancy as _tncy

        sub = f"canary-op-{uuid.uuid4().hex[:12]}"
        email = f"{sub}@canary.invalid"
        if role == "_platform":
            # A _platform operator needs TWO membership rows:
            # 1) the reserved _platform partition (grants is_platform=True)
            # 2) a customer-primary row in the working tenant (so
            #    resolve_operator_tenant can bind to a real tenant; a pure-
            #    platform with no customer membership can't resolve → 403).
            plat = _tncy.PLATFORM_TENANT
            s1 = _seed_member_row(sub, plat, "_platform")
            s2 = _seed_member_row(sub, tenant_id, "admin")
            self._minted.append((sub, plat))
            self._minted.append((sub, tenant_id))
            if not (s1 and s2):
                raise RuntimeError(
                    f"canary_operator could not seed _platform dual-membership for "
                    f"{sub} in {plat}+{tenant_id} — RED/INFRA, never a skip."
                )
        else:
            seeded = _seed_member_row(sub, tenant_id, role)
            self._minted.append((sub, tenant_id))
            if not seeded:
                raise RuntimeError(
                    f"canary_operator could not seed a {role} membership for {sub} in "
                    f"{tenant_id} — RED/INFRA, never a skip."
                )
        self._deps._alb_claims_override = lambda _req, _s=sub, _e=email: {"sub": _s, "email": _e}
        return {"sub": sub, "email": email, "tenant_id": tenant_id, "role": role}

    def teardown(self) -> None:
        self._deps._alb_claims_override = self._prev
        for sub, tid in self._minted:
            try:
                from app.services.tenant_service import get_member_store

                get_member_store()._table().delete_item(
                    Key={"operator_sub": sub, "tenant_id": tid}
                )
            except Exception:  # noqa: BLE001 — idempotent best-effort; never reds a run.
                pass


@pytest.fixture
def canary_operator(request):
    """J1.3 / J7 — a role-parameterized VERIFIED-operator minter, INPROCESS ONLY.

    Yields an ``_OperatorMinter``; call ``.mint(tenant_id, role)`` to install one
    operator identity (``viewer|editor|admin|owner|_platform``). **Last-minted wins** —
    calling ``mint()`` again overrides the previous identity (both membership rows are
    cleaned up, but only the last override is active). Each J7 test mints once.
    Backwards-compatible for the J1 smoke use: ``op = canary_operator.mint(tid)``
    returns ``{sub,email,...}``.

    The ``live`` (real-Cognito) form is Increment-2 deferred (task §3.2) — using this
    fixture in ``live`` mode raises ``NotImplementedError`` (the deployed service has no
    ``_alb_claims_override`` seam; J8 supplies the hosted-UI login)."""
    target = os.environ.get(CANARY_TARGET_ENV, "inprocess")
    if target == "live":
        raise NotImplementedError(
            "canary_operator live form is Increment-2 (console/auth, J8)"
        )
    from app.api import deps

    minter = _OperatorMinter(deps)
    try:
        yield minter
    finally:
        minter.teardown()


# ------------------------------------------------------------------ J8 console login
# The live hosted-UI login fixture (D-4). ALL Playwright imports are LAZY (inside the
# fixture body) so importing this conftest in the hermetic PR gate / lean image never
# needs the browser lib. The console scenarios themselves import-guard playwright at
# module level (test_console_authed_oidc.py) so a browserless collection skips, not errors.
_CONSOLE_USER_SECRET = "sentra/canary/console-user"  # founder-provisioned (email/password/tenant_id)


class _ConsoleVisitResult:
    """What a single authed console-page visit observed (J8.2)."""

    def __init__(self, rendered: bool, saw_5xx: bool, five_xx_urls, uncaught_error: bool) -> None:
        self.rendered = rendered
        self.saw_5xx = saw_5xx
        self.five_xx_urls = five_xx_urls
        self.uncaught_error = uncaught_error


class _ConsoleSession:
    """An authenticated Playwright browser context (J8.1) + helpers for J8.2/J8.4.

    Holds ONE logged-in context for the whole run. ``visit(path)`` drives the authed
    ``page`` and captures its network trace (render + no-5xx + no uncaught error).
    ``oidc_client()`` returns an httpx client seeded with the ALB session cookie for
    OIDC ``/v1`` calls THROUGH the console host (where nginx re-emits x-sentra-oidc-data
    + injects the api-key). SEC-10: NO trace/screenshot is ever captured (real prod
    cookies + authed DOM must never hit an artifact)."""

    def __init__(self, page, context, base_url: str) -> None:
        self._page = page
        self._context = context
        self._base = base_url.rstrip("/")

    def visit(self, path: str) -> "_ConsoleVisitResult":
        five_xx = []
        uncaught = {"hit": False}

        def _on_response(r):
            if r.status >= 500:
                five_xx.append(r.url)

        def _on_pageerror(_e):
            uncaught["hit"] = True

        # The page is session-scoped (reused across all 25 sweep routes), so listeners
        # MUST be removed after each visit — else they accumulate (leak + Playwright
        # listener-limit warnings) AND a late event from an earlier route could attribute
        # a 5xx / pageerror to the WRONG visit (false RED). Scope them per-visit.
        self._page.on("response", _on_response)
        self._page.on("pageerror", _on_pageerror)
        rendered = False
        try:
            self._page.goto(f"{self._base}{path}", wait_until="networkidle", timeout=20000)
            # A landmark element (the console app shell) — explicit wait, never sleep.
            self._page.wait_for_selector("#root, main, [data-app-shell]", timeout=15000)
            rendered = True
        except Exception:  # noqa: BLE001 — a render/timeout failure is a FAIL, captured below.
            rendered = False
        finally:
            self._page.remove_listener("response", _on_response)
            self._page.remove_listener("pageerror", _on_pageerror)
        return _ConsoleVisitResult(rendered, bool(five_xx), five_xx, uncaught["hit"])

    def oidc_client(self):
        """An httpx client carrying the ALB session cookies, based at the console host."""
        import httpx

        cookies = {c["name"]: c["value"] for c in self._context.cookies()}
        return httpx.Client(base_url=self._base, cookies=cookies, timeout=15.0,
                            follow_redirects=False)


def _load_console_user() -> Dict[str, str]:
    """Read the founder-provisioned canary console user (email/password/tenant_id).

    A precondition failure (secret absent / malformed) is RAISED — the reporting plugin
    records INFRA, never a silent skip (a skipped security canary is an ungated claim)."""
    import json

    raw = _load_secret(_CONSOLE_USER_SECRET)
    try:
        data = json.loads(raw)
        # Validate + narrow external data before use (never trust the secret blob shape).
        email, password = data["email"], data["password"]
    except (ValueError, KeyError, TypeError) as exc:
        raise RuntimeError(
            f"canary console-user secret {_CONSOLE_USER_SECRET!r} is missing/malformed "
            f"(need JSON with email+password) — J8 login precondition FAIL (INFRA, not skip)"
        ) from exc
    return {"email": email, "password": password, "tenant_id": data.get("tenant_id", "")}


def _hosted_ui_login(page, base_url: str, creds: Dict[str, str]) -> None:
    """Drive the real ALB authenticate-cognito hosted-UI form-fill (D-4). Org-first:
    land on org.html, submit the org, follow to the Cognito hosted UI, fill the
    canary user's email+password by STABLE field semantics (never css/nth-child), and
    let the ALB set AWSELBAuthSessionCookie-*."""
    page.goto(base_url, wait_until="domcontentloaded", timeout=20000)
    # Org-first entry (WS-G): if the org page is shown, submit the canary tenant/org.
    org = creds.get("tenant_id") or ""
    org_field = page.query_selector("input[name='org'], input[name='organization'], #org")
    if org_field is not None and org:
        org_field.fill(org)
        page.click("button[type='submit'], [type='submit']")
    # Cognito hosted UI — stable field semantics (SEC / lld/38 §6.1). Each field is
    # WAIT-guarded before fill: the hosted UI may render the username first and the
    # password on a SECOND page (two-step flow), so querying password without a wait
    # would NoneType-deref. wait_for_selector raises a clear TimeoutError (→ INFRA /
    # LoginFixtureFailed) rather than a confusing `None.fill()` AttributeError.
    def _fill_field(selector: str, value: str, what: str) -> None:
        try:
            page.wait_for_selector(selector, timeout=20000)
        except Exception as exc:  # noqa: BLE001 — a missing login field is a precondition fail.
            raise RuntimeError(
                f"hosted-UI {what} field not found ({selector!r}) — the Cognito login page "
                f"changed or a two-step flow stalled (J8 LoginFixtureFailed, INFRA)"
            ) from exc
        page.fill(selector, value)

    _fill_field("input[name='username'], input[type='email']", creds["email"], "username")
    # Some hosted-UI themes require submitting the username before the password renders;
    # if a lone password field isn't present yet, advance then wait for it.
    if page.query_selector("input[name='password'], input[type='password']") is None:
        page.click("input[type='submit'], button[type='submit']")
    _fill_field("input[name='password'], input[type='password']", creds["password"], "password")
    page.click("input[type='submit'], button[type='submit']")
    # Land back on the console (ALB has set the session cookie by now).
    page.wait_for_load_state("networkidle", timeout=20000)


@pytest.fixture(scope="session")
def console_session():
    """J8.1 — one authenticated console browser context for the whole run (live only).

    A login failure is its OWN concern (``LoginFixtureFailed`` alarm class, lld/38 §6.1) —
    a precondition/login error is RAISED here so the reporting plugin records it distinctly
    (page on a 2-run streak), never folded into a route ChecksFailed count or a silent skip."""
    if os.environ.get(CANARY_TARGET_ENV, "inprocess") != "live":
        pytest.skip("console session is live-only (real hosted-UI login)")
    from playwright.sync_api import sync_playwright

    base_url = os.environ.get("SENTRA_CONSOLE_URL", "https://console.aegionai.ai")
    creds = _load_console_user()  # raises → INFRA if the secret isn't provisioned yet
    with sync_playwright() as pw:
        # Chromium under Fargate: no user namespaces → --no-sandbox; headless=new.
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--headless=new"])
        context = browser.new_context()  # SEC-10: no record_video / no tracing
        page = context.new_page()
        try:
            _hosted_ui_login(page, base_url, creds)
            yield _ConsoleSession(page, context, base_url)
        finally:
            context.close()
            browser.close()


@pytest.fixture
def console_page(console_session):
    """J8.2 — the authed console session (exposes ``.visit(path)``)."""
    return console_session


@pytest.fixture
def console_oidc_client(console_session):
    """J8.4 — an httpx client carrying the ALB session cookie, based at the console host
    (nginx re-emits x-sentra-oidc-data + injects the api-key there)."""
    client = console_session.oidc_client()
    try:
        yield client
    finally:
        client.close()
