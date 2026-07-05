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
    "test_all_routes.py",     # P0-1 all-route positive/negative sweep (pure httpx)
    "test_metrics_live.py",   # requires_live metric checks (pure httpx)
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
@pytest.fixture
def canary_operator(request):
    """J1.3 — synthetic verified operator claims for OIDC-gated handlers, INPROCESS
    ONLY (Increment 1). Installs ``deps._alb_claims_override`` (the test seam,
    deps.py:279/289) returning ``{"sub","email"}`` + seeds a matching
    ``sentra-tenant-members`` row; resets the override to ``None`` on teardown.

    The ``live`` (real-Cognito) form is Increment-2 deferred (task §3.2) — invoking
    this fixture in ``live`` mode raises ``NotImplementedError``.
    """
    target = os.environ.get(CANARY_TARGET_ENV, "inprocess")
    if target == "live":
        raise NotImplementedError(
            "canary_operator live form is Increment-2 (console/auth)"
        )

    from app.api import deps

    sub = f"canary-op-{uuid.uuid4().hex[:12]}"
    email = f"{sub}@canary.invalid"

    def _claims(_request) -> Dict[str, str]:
        return {"sub": sub, "email": email}

    prev = deps._alb_claims_override
    deps._alb_claims_override = _claims
    try:
        yield {"sub": sub, "email": email}
    finally:
        deps._alb_claims_override = prev
