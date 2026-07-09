"""WS-J J-report — the pytest reporting plugin (lld/38 §9) + the three-state model.

Maps each check's outcome → ``status`` (PASS/FAIL/INFRA/SKIPPED_OVERLAP) and, in
``live`` mode ONLY, writes one durable ``sentra-canary-results`` row per check
(``(run_id, check_id)`` + failure_reason + expected/actual + http_status +
latency_ms + correlation_id + scenario + route + ttl) so RCA is a query, not a hunt.
A local/on-demand ``inprocess`` run emits to stdout only — NEVER writes prod.

Three-state model (§9.1):
  * INFRA  — a live transport error with NO HTTP response (DNS / conn-reset /
             conn-refused / TLS / client-timeout) → bounded retry, then INFRA.
  * FAIL   — a deterministic assertion failure OR any service-returned 5xx
             (ALB 502/503, controller 500) → NEVER retried, pages.
  * PASS   — assertion passed.

Defense-in-depth (§9.3): before an SNS publish to the shared critical topic the
plugin asserts ``sts:GetCallerIdentity`` is the canary task-role ARN — belt-and-
suspenders on top of the IAM scoping (the load-bearing boundary is IAM).
"""
from __future__ import annotations

import datetime as _dt
import os
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

CANARY_TARGET_ENV = "CANARY_TARGET"
RESULTS_TABLE_ENV = "CANARY_RESULTS_TABLE"
CANARY_ROLE_SUBSTR = "sentra-canary"  # the canary task-role ARN carries this.
_TTL_DAYS = 90


def _is_service_5xx(exc: Optional[BaseException]) -> bool:
    """A raw assertion failure whose message carries a service-returned 5xx status is
    a product 5xx (FAIL that also increments ``ProductFivexxFail`` for the critical
    escalation, §9.1). The scenario library asserts ``status_code < 500`` and includes
    the observed status in the assertion message, so a 5xx surfaces here. Belt-and-
    suspenders: the live ``CanaryClient`` also records a 5xx directly (``record_service_5xx``)
    so the escalation does not depend on message-string matching alone."""
    if exc is None:
        return False
    # A live transport error (InfraError) is NOT a service 5xx.
    if isinstance(exc, InfraError):
        return False
    msg = str(exc)
    return any(f"{code}" in msg for code in (500, 502, 503, 504))


class InfraError(Exception):
    """Raised by the retry wrapper when a live transport error has NO HTTP response
    after N bounded retries → recorded as INFRA (never FAIL, never swallowed)."""


class TransportRetryable(Exception):
    """Signals a GATEWAY 5xx (502/503/504 — the edge could not reach the backend, same
    transient class as a no-response transport error) that ``retry_transport`` should
    RE-ATTEMPT. It carries the last HTTP response so that, if all retries return a
    gateway 5xx (a genuine PERSISTENT edge outage), the wrapper returns that response
    and the scenario's status assertion fails normally — a persistent 502 IS a failure,
    while a single transient one is retried away and never pages."""

    def __init__(self, response):
        self.response = response
        super().__init__(f"gateway {getattr(response, 'status_code', '5xx')} (retryable)")


@dataclass
class CanaryResult:
    run_id: str
    check_id: str
    status: str
    scenario: str = ""
    route: str = ""
    failure_reason: str = ""
    expected: str = ""
    actual: str = ""
    http_status: Optional[int] = None
    latency_ms: Optional[float] = None
    correlation_id: Optional[str] = None

    def to_item(self) -> Dict[str, Any]:
        ttl = int(time.time()) + _TTL_DAYS * 86400
        item = {
            "run_id": self.run_id,
            "check_id": self.check_id,
            "status": self.status,
            "scenario": self.scenario,
            "route": self.route,
            "failure_reason": self.failure_reason,
            "expected": self.expected,
            "actual": self.actual,
            "correlation_id": self.correlation_id or "",
            "ttl": ttl,
        }
        if self.http_status is not None:
            item["http_status"] = self.http_status
        if self.latency_ms is not None:
            item["latency_ms"] = str(round(self.latency_ms, 3))
        return item


def new_run_id() -> str:
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"canary-{stamp}-{uuid.uuid4().hex}"


def classify_outcome(*, passed: bool, infra: bool, service_5xx: bool) -> str:
    """The three-state decision (§9.1). A service 5xx is a FAIL that pages, NOT an
    INFRA blip; only a no-HTTP-response transport error is INFRA."""
    if infra:
        return "INFRA"
    if not passed or service_5xx:
        return "FAIL"
    return "PASS"


def retry_transport(fn, *, retries: int = 2, backoff: float = 0.2):
    """Bounded retry for a LIVE transient condition (§9.1). Two retryable classes:
      * a transport error with NO HTTP response (DNS/conn-reset/timeout) — after
        ``retries`` failures raises ``InfraError`` → recorded INFRA (never FAIL).
      * a ``TransportRetryable`` (gateway 502/503/504) — after ``retries`` failures
        RETURNS the last response so the caller's status assertion fails normally
        (a PERSISTENT edge outage is a real FAIL; a single transient 502 is retried away).
    A deterministic assertion failure is NEVER retried — only pass a transport call here."""
    last_exc: Optional[Exception] = None
    for attempt in range(retries + 1):
        try:
            return fn()
        except TransportRetryable as exc:  # gateway 5xx — retry, else return last resp
            last_exc = exc
            if attempt < retries:
                time.sleep(backoff * (attempt + 1))
                continue
            return exc.response  # exhausted → hand back the persistent gateway 5xx
        except _NO_RESPONSE_ERRORS as exc:  # transport-only, no HTTP response
            last_exc = exc
            if attempt < retries:
                time.sleep(backoff * (attempt + 1))
                continue
    raise InfraError(f"transport error after {retries} retries: {last_exc!r}")


def _no_response_error_types():
    try:
        import httpx  # noqa: WPS433

        return (
            httpx.ConnectError,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
            httpx.RemoteProtocolError,
            ConnectionError,
        )
    except Exception:  # noqa: BLE001
        return (ConnectionError, TimeoutError)


_NO_RESPONSE_ERRORS = _no_response_error_types()


class ResultSink:
    """Writes results in ``live`` mode; stdout-only otherwise. The load-bearing
    boundary is IAM (only the canary task role has PutItem/Publish) — the
    ``mode=='live'`` branch is ONE guard on top of that."""

    def __init__(self, mode: str, table_name: Optional[str] = None):
        self.mode = mode
        self.table_name = table_name or os.environ.get(RESULTS_TABLE_ENV)
        self.written: List[CanaryResult] = []

    def write(self, result: CanaryResult) -> bool:
        """Return True iff a durable row was written (live only)."""
        if self.mode != "live":
            # Local / PR-gate inprocess run — stdout only, NEVER touch prod.
            print(f"[canary] {result.status} {result.check_id} {result.failure_reason}")
            return False
        import boto3

        boto3.resource("dynamodb").Table(self.table_name).put_item(Item=result.to_item())
        self.written.append(result)
        return True

    def publish_critical(self, topic_arn: str, message: str, *, sts_client=None) -> bool:
        """Publish to the shared critical topic ONLY after asserting we are the
        canary task role (§9.3 defense-in-depth). Returns True iff published."""
        import boto3

        sts = sts_client or boto3.client("sts")
        arn = sts.get_caller_identity().get("Arn", "")
        if CANARY_ROLE_SUBSTR not in arn:
            # A non-canary caller (e.g. a developer's sentra creds) must NOT page the
            # shared critical audience — fail closed on the publish.
            return False
        boto3.client("sns").publish(TopicArn=topic_arn, Message=message)
        return True


# --------------------------------------------------------------------------- pytest hook
# The plugin is OPT-IN via -p canary.reporting_plugin (the ECS entrypoint enables it);
# a normal PR-gate run does not load it, so importing this module is side-effect free.
# ``counts`` carries the FOUR numbers the alarms watch: PASS/FAIL/INFRA drive
# ChecksPassed/ChecksFailed/InfraErrors (+ ChecksExpected, §9.4), and ``SERVICE_5XX``
# drives the ProductFivexxFail critical escalation (§9.1). The end-of-run emitter
# (entrypoint.emit_run_metrics / the pytest_sessionfinish belt-and-suspenders below)
# is what turns these counts into the CloudWatch metrics every canary_stack alarm
# reads — WITHOUT it the counts are computed and thrown away (the dead-seam bug).
_RUN_STATE: Dict[str, Any] = {}


def _fresh_counts() -> Dict[str, int]:
    return {"PASS": 0, "FAIL": 0, "INFRA": 0, "SERVICE_5XX": 0}


def run_counts() -> Dict[str, int]:
    """The current run's outcome tally (public accessor for the entrypoint emitter).
    Empty dict before ``pytest_configure`` ran (e.g. a bare import)."""
    return dict(_RUN_STATE.get("counts", {}))


def record_service_5xx() -> None:
    """The live ``CanaryClient`` calls this the moment it sees a service-returned 5xx
    response, BEFORE the scenario assertion raises. This is the authoritative signal
    that the current check hit a product 5xx (drives ProductFivexxFail, §9.1); the
    assertion-message fallback in ``pytest_runtest_makereport`` only fires if this
    per-check flag was NOT set (e.g. a 5xx observed off the client path). No-op if the
    plugin isn't active (e.g. a pure unit-test import)."""
    if "counts" in _RUN_STATE:
        _RUN_STATE["pending_5xx"] = True


def pytest_configure(config):  # pragma: no cover - exercised via the ECS entrypoint
    mode = os.environ.get(CANARY_TARGET_ENV, "inprocess")
    _RUN_STATE["run_id"] = new_run_id()
    _RUN_STATE["mode"] = mode
    _RUN_STATE["sink"] = ResultSink(mode)
    _RUN_STATE["counts"] = _fresh_counts()
    _RUN_STATE["pending_5xx"] = False


def pytest_runtest_setup(item):  # pragma: no cover - ECS entrypoint path
    # Clear the per-check 5xx flag so a 5xx recorded during THIS check is not
    # attributed to the next one.
    if "counts" in _RUN_STATE:
        _RUN_STATE["pending_5xx"] = False


def pytest_runtest_makereport(item, call):  # pragma: no cover - ECS entrypoint path
    sink: ResultSink = _RUN_STATE.get("sink")
    if sink is None:
        return
    # A SETUP-phase failure (a fixture raising — e.g. the J8 console_session login
    # fixture when sentra/canary/console-user is unprovisioned or the hosted-UI login
    # fails) must NOT be silently dropped: without this, every console/authed-oidc test
    # errors at setup, reaches 'call' for none of them, and contributes ZERO checks — the
    # run looks green (ChecksFailed=0) while a whole security lane tested nothing. A
    # setup error is recorded as INFRA (a precondition/environment failure, not a product
    # FAIL) so ChecksExpected>counted trips the anti-false-PASS composite alarm and the
    # per-check row carries the reason. A skip (importorskip: no browser) is NOT an error,
    # so it is not counted here.
    if call.when == "setup":
        # Clean setup, or a legitimate skip (importorskip: no browser installed) → not an
        # error; let the run proceed (a skip is not a dropped check). Detect Skipped by
        # class name to avoid a module-level pytest import (lean discipline, §J-report).
        if call.excinfo is None or call.excinfo.typename in ("Skipped", "XFailed"):
            return
        exc = call.excinfo.value
        _RUN_STATE["counts"]["INFRA"] = _RUN_STATE["counts"].get("INFRA", 0) + 1
        sink.write(CanaryResult(
            run_id=_RUN_STATE["run_id"],
            check_id=item.nodeid,
            status="INFRA",
            route=item.nodeid,
            failure_reason=f"setup-phase failure (fixture): {exc!r}",
        ))
        return
    if call.when != "call":
        return
    # A call-phase SKIP/XFAIL (pytest.skip(...) inside a scenario — e.g. J8's known-WS-21
    # overview render-timeout or a gateway-5xx authed read, and the requires_live skips in
    # a non-live run) raises Skipped/XFailed, which sets call.excinfo. It is NOT a failure:
    # counting it would make ChecksFailed++ and page on a documented, deliberate skip
    # (observed: the overview skip lit the alarm). Record it as SKIPPED (visible, never a
    # silent pass) and return — do NOT fall through to the FAIL classification.
    if call.excinfo is not None and call.excinfo.typename in ("Skipped", "XFailed"):
        _RUN_STATE["counts"]["SKIPPED"] = _RUN_STATE["counts"].get("SKIPPED", 0) + 1
        sink.write(CanaryResult(
            run_id=_RUN_STATE["run_id"],
            check_id=item.nodeid,
            status="SKIPPED",
            route=item.nodeid,
            failure_reason=f"skipped: {call.excinfo.value!r}",
        ))
        return
    exc = call.excinfo.value if call.excinfo else None
    infra = isinstance(exc, InfraError)
    passed = call.excinfo is None
    # A service-returned 5xx is a FAIL (never INFRA) that ALSO pages the critical
    # topic. Authoritative signal: the live client's record_service_5xx (per-check
    # flag); fallback: the observed status embedded in the assertion message.
    service_5xx = bool(_RUN_STATE.get("pending_5xx")) or _is_service_5xx(exc)
    status = classify_outcome(passed=passed, infra=infra, service_5xx=service_5xx)
    _RUN_STATE["counts"][status] = _RUN_STATE["counts"].get(status, 0) + 1
    if service_5xx:
        _RUN_STATE["counts"]["SERVICE_5XX"] = _RUN_STATE["counts"].get("SERVICE_5XX", 0) + 1
    result = CanaryResult(
        run_id=_RUN_STATE["run_id"],
        check_id=item.nodeid,
        status=status,
        route=item.nodeid,
        failure_reason=repr(exc) if exc else "",
    )
    sink.write(result)


__all__ = [
    "CanaryResult",
    "ResultSink",
    "InfraError",
    "TransportRetryable",
    "classify_outcome",
    "retry_transport",
    "new_run_id",
    "run_counts",
    "record_service_5xx",
]
