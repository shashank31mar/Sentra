"""Execution isolation for the security-efficacy benchmark harness.

LLD 41 §4.7 (D10, mechanisms I1–I5) · §4.8 (configuration) · §11 (the
store-by-store discharge) · FR-14.9 · WS-B milestones B1/B2.

The rig executes adversarial content by design, imports the production engine's
code in-process, and — if unguarded — can write into the production AWS account.
**The serious risk here is not an attacker; it is us.** ``enforce()`` is the
first executable statement of every entry point under ``benchmarks/``, before any
``sys.path`` manipulation and before any ``app.*`` import, and it turns the
boundary of the measurement from something declared into something that *fails*
when crossed.

The chain, in the order it must run
-----------------------------------
==== =========================== ==================================================
 I1   ``AEGION_BENCHMARK=1``      the badge, not the protection — it makes I2–I5
                                  unconditional
 I3   positive credential         **assert first**, on the UNMUTATED provider chain
      assertion
 I2   credential sentinelization  the correctness floor
 I5   prod-target denylist        hosted runs only
 I4   null objects                the cleanliness / performance layer
 --   tenant bind                 ``_benchmark``, so every row is separable
==== =========================== ==================================================

**The I3-before-I2 ordering is the whole mechanism, and an earlier LLD draft had
it backwards.** botocore's provider chain resolves ``EnvProvider`` first, so once
I2 has written the sentinel and popped ``AWS_PROFILE``,
``botocore.session.Session().get_credentials()`` can only ever return the
sentinel. Asserting after sentinelizing therefore passes unconditionally: "a
developer with a live ``sentra`` profile is stopped here, loudly" would never
once fire, and the live-credential refusal test would be *unpassable*.
``benchmarks/tests/test_isolation_unit.py::test_i3_snapshots_before_mutation`` is
the regression test for exactly that inversion.

Import discipline
-----------------
Nothing from ``boto3`` and nothing from ``app.*`` is imported at module scope —
I2 must land before boto3 caches a session, and the I4 substitution must land
before the modules that construct clients are imported. ``botocore.session`` is
imported inside the function, for the I3 snapshot only.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional, Tuple
from urllib.parse import urlsplit

from .null_objects import NullAuditWriter, NullMetricsPublisher

# --------------------------------------------------------------------------- #
# Constants — every one of these is a knob in LLD 41 §4.8
# --------------------------------------------------------------------------- #
BADGE_ENV_VAR = "AEGION_BENCHMARK"
BADGE_VALUE = "1"

#: What I2 writes over the AWS credential environment. Any call that slips past a
#: missing null object fails at the API with ``InvalidClientTokenId`` rather than
#: succeeding against a real account.
SENTINEL_CREDENTIAL = "AEGION-BENCH-NO-AWS"

#: Access-key values I3 will accept as "not a live credential". Only our own
#: sentinel qualifies — a nested run (the harness re-invoking an entry point)
#: must pass I3, and nothing else may.
ACCEPTED_ACCESS_KEYS = frozenset({SENTINEL_CREDENTIAL})

#: The production AWS account. `cdk/config/prod.yaml` and `cdk/stacks/*` pin it.
PROD_ACCOUNT_ID = "531109575379"

#: Production engine endpoints. Verified against the deployed configuration:
#: the prod API Gateway (`web/console/.env.example:2`,
#: `cdk/stacks/bedrock_agent_stack.py:125`), the public ALB
#: (`tests/integration/test_data_model_v2_integration.py:31`), the private ALB and
#: the API NLB (`tasks/workstream-16-apigw-vpc-link-networking.md:297`).
PROD_HOSTS = frozenset({
    "iw3limi4k7.execute-api.us-east-1.amazonaws.com",
    "sentra-public-alb-1320390749.us-east-1.elb.amazonaws.com",
    "internal-sentra-private-alb-760501353.us-east-1.elb.amazonaws.com",
    "sentra-api-nlb-f00bf616b8803daf.elb.us-east-1.amazonaws.com",
})

#: Substrings that mark a host as production infrastructure even when the exact
#: DNS name has moved (an ALB re-creation changes only the numeric suffix). This
#: is defence in depth over :data:`PROD_HOSTS`, not a replacement for it — and,
#: per LLD 41 §11, egress control here is application-level and best-effort. The
#: credential floor (I2) is what actually holds.
PROD_HOST_FRAGMENTS = ("sentra-public-alb", "sentra-private-alb", "sentra-api-nlb")

#: The reserved tenant the run binds. `app.utils.tenancy.RESERVED_TENANT_IDS`
#: must contain it — pinned by `benchmarks/tests/test_tenancy.py`.
BENCHMARK_TENANT = "_benchmark"

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CONTROLLER_ROOT = _REPO_ROOT / "src" / "security-controller"

# Modules/attributes I4 has replaced, newest last, so `restore_substitutions()`
# can put the real symbols back. Test support and run teardown only — a run never
# calls it.
_SUBSTITUTIONS: List[Tuple[Any, str, Any]] = []


class IsolationError(RuntimeError):
    """A rig-configuration fault that stops isolation being establishable at all."""


# --------------------------------------------------------------------------- #
# The record the manifest carries (LLD 41 §4.7 B5 — a data carrier, recorded
# rather than asserted; its correctness is covered by I1–I5's own tests)
# --------------------------------------------------------------------------- #
@dataclass
class IsolationRecord:
    """The ``isolation`` block WS-A serializes verbatim into the run manifest.

    Six fields, and **never a credential value** — ``aws_credentials`` records
    the *state* ("sentinel"), not the key.
    """

    tenant: str
    badge: bool
    aws_credentials: str
    metrics_publisher: str
    audit_writer: str
    prod_target_check: str
    #: contextvars Token for the tenant binding. Held so the run can unwind the
    #: binding rather than leaking it into whatever runs next in this process
    #: (`tenancy.set_current_tenant` returns a Token — LLD 41 §4.7 footgun).
    #: Excluded from the serialized form.
    tenant_token: Any = field(default=None, repr=False, compare=False)

    def to_dict(self) -> dict:
        """The manifest shape — exactly six fields, token excluded."""
        return {
            "tenant": self.tenant,
            "badge": self.badge,
            "aws_credentials": self.aws_credentials,
            "metrics_publisher": self.metrics_publisher,
            "audit_writer": self.audit_writer,
            "prod_target_check": self.prod_target_check,
        }

    def release(self) -> None:
        """Unbind the ``_benchmark`` tenant at run end. Idempotent."""
        if self.tenant_token is None:
            return
        from app.utils import tenancy  # local: never at module scope

        tenancy.reset_current_tenant(self.tenant_token)
        self.tenant_token = None


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _refuse(message: str) -> "NoReturn":  # type: ignore[valid-type]  # noqa: F821
    """Refuse, loudly, with exit code **2**.

    ``raise SystemExit("text")`` would print the text but exit **1**; the refusal
    contract is exit 2 with the reason on stderr, so the two are done separately.
    """
    print(f"[aegion-benchmark] REFUSED: {message}", file=sys.stderr, flush=True)
    raise SystemExit(2)


def _argv_option(name: str, argv: Optional[List[str]] = None) -> Optional[str]:
    """Read ``--name value`` / ``--name=value`` straight out of ``sys.argv``.

    ``enforce()`` has to be able to apply I5 while still being *literally* the
    first executable statement of an entry point — i.e. before argparse has run.
    An explicit keyword argument (what WS-A's ``run.py`` passes once it has
    parsed) always wins over this scan; this is only the pre-argparse fallback.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    flag = f"--{name}"
    for i, arg in enumerate(args):
        if arg == flag and i + 1 < len(args):
            return args[i + 1]
        if arg.startswith(flag + "="):
            return arg.split("=", 1)[1]
    return None


def _host_of(base_url: str) -> str:
    """Hostname of a base url, lower-cased and port-stripped. Falls back to the
    raw value so a bare ``host:port`` (no scheme) is still checked."""
    parsed = urlsplit(base_url if "//" in base_url else f"//{base_url}")
    return (parsed.hostname or base_url).strip().lower()


def _is_prod_host(host: str) -> bool:
    return host in PROD_HOSTS or any(f in host for f in PROD_HOST_FRAGMENTS)


def _resolve_account_id() -> Optional[str]:
    """The AWS account the ambient credentials resolve to, or ``None``.

    Called for hosted runs only, and only *after* I2 — which means it will
    normally fail (that is the point of I2) and return ``None``. The account
    check is therefore best-effort by construction; :data:`PROD_HOSTS` is the
    control that actually bites on the hosted path. Monkeypatched by
    ``test_i5_rejects_prod_account``.
    """
    try:
        import boto3
        from botocore.config import Config

        sts = boto3.client(
            "sts",
            config=Config(connect_timeout=2, read_timeout=2, retries={"max_attempts": 0}),
        )
        return sts.get_caller_identity().get("Account")
    except Exception:  # noqa: BLE001 — an unresolvable account is not a refusal
        return None


def _ensure_controller_importable() -> None:
    """Put the PDP package root on ``sys.path`` so ``app.*`` resolves.

    This is the *only* sys.path manipulation the rig performs, and it happens
    inside ``enforce()`` — after I2 — so nothing imported by it can reach AWS
    with live credentials.
    """
    if not _CONTROLLER_ROOT.is_dir():
        raise IsolationError(
            f"security-controller package root not found at {_CONTROLLER_ROOT}; "
            "the benchmark rig must run from inside the Sentra checkout"
        )
    path = str(_CONTROLLER_ROOT)
    if path not in sys.path:
        sys.path.insert(0, path)


# --------------------------------------------------------------------------- #
# I1 — the badge
# --------------------------------------------------------------------------- #
def _assert_badge() -> bool:
    """Refuse to run unbadged. A soft badge is a convention with better prose —
    this is the mechanism that makes I2–I5 unconditional, so it is never a
    warning."""
    value = os.environ.get(BADGE_ENV_VAR)
    if value != BADGE_VALUE:
        _refuse(
            "benchmark entry points refuse to run unbadged — "
            f"set {BADGE_ENV_VAR}={BADGE_VALUE} (got {value!r})"
        )
    return True


# --------------------------------------------------------------------------- #
# I3 — the positive credential assertion, on the UNMUTATED environment
# --------------------------------------------------------------------------- #
def _assert_no_live_credentials() -> None:
    """Snapshot the real provider chain **before** anything mutates it.

    Sentinelization silently does nothing if an SDK reads credentials from
    ``~/.aws/credentials`` or IMDS — I2 only overwrites the *environment*
    provider — so the negative has to be asserted, not assumed. This runs first
    for the reason spelled out in the module docstring.
    """
    import botocore.session
    from botocore.exceptions import ProfileNotFound

    try:
        creds = botocore.session.Session().get_credentials()
    except ProfileNotFound:
        # A stale AWS_PROFILE pointing at a profile that does not exist resolves
        # no credentials — benign, and I2 pops the variable a moment later.
        return
    except Exception as exc:  # noqa: BLE001 — fail secure: unknown == unassertable
        _refuse(
            "could not assert the absence of live AWS credentials "
            f"({type(exc).__name__}: {exc}); refusing rather than guessing"
        )

    if creds is None:
        return
    access_key = getattr(creds, "access_key", None)
    if access_key in ACCEPTED_ACCESS_KEYS:
        return  # a nested run already carrying our sentinel

    provider = getattr(creds, "method", None) or "unknown"
    _refuse(
        f"live AWS credentials present (resolved by provider {provider!r}) — "
        "the benchmark rig must never run with credentials that can reach a real "
        "account. Unset them (or run in a clean shell) and retry."
    )


# --------------------------------------------------------------------------- #
# I2 — credential sentinelization (the correctness floor)
# --------------------------------------------------------------------------- #
def _sentinelize_credentials() -> str:
    """Overwrite the credential environment and pop the profile chain.

    Holds even if a future code path adds an AWS client nobody anticipated:
    four of the seven stores on the in-process path construct their boto3 client
    directly in ``__init__``, bypassing the ``get_clients()`` registry, so a
    seam-only approach would leave most of them un-neutralized (LLD 41 §11).
    """
    os.environ["AWS_ACCESS_KEY_ID"] = SENTINEL_CREDENTIAL
    os.environ["AWS_SECRET_ACCESS_KEY"] = SENTINEL_CREDENTIAL
    os.environ.pop("AWS_PROFILE", None)
    os.environ.pop("AWS_SESSION_TOKEN", None)
    return "sentinel"


# --------------------------------------------------------------------------- #
# I5 — the prod-target denylist (hosted runs only)
# --------------------------------------------------------------------------- #
def _assert_not_production(transport: str, base_url: Optional[str]) -> str:
    """Refuse a hosted run aimed at production.

    "Point it at prod just this once to see" is the failure mode FR-14.9 exists
    to prevent; it must not be one CLI flag away. In-process runs reach no
    endpoint at all, so no STS call is attempted for them.
    """
    if transport != "hosted":
        return "skipped"

    if base_url:
        host = _host_of(base_url)
        if _is_prod_host(host):
            _refuse(f"refusing to target production — {host!r} is a production host")

    account = _resolve_account_id()
    if account == PROD_ACCOUNT_ID:
        _refuse(
            f"refusing to target production — credentials resolve to the "
            f"production account {PROD_ACCOUNT_ID}"
        )
    return "passed"


# --------------------------------------------------------------------------- #
# I4 — null objects by module substitution
# --------------------------------------------------------------------------- #
def _install_null_objects() -> Tuple[str, str]:
    """Replace the ``MetricsPublisher`` / ``AuditLogger`` symbols on their
    defining modules, before anything that consumes them is imported.

    Substituting the *class symbol* is sufficient for the lazy consumers
    (``sigma_engine.py:361`` imports inside the method, so it resolves through
    ``sys.modules`` at call time), but **not** for the module-scope consumers —
    ``app/services/conversation_service.py:14`` and
    ``app/utils/rollback_coordinator.py:26`` bind ``AuditLogger`` at import. That
    is why this has to land before ``app.*`` is imported, and why
    ``test_substitution_lands_before_app_import`` runs in a subprocess: nothing
    else can prove an ordering.

    Deliberately NOT a ``benchmark_mode`` flag in ``app/config.py`` (SEC-6
    rejects it): that would put the harness's isolation guarantee inside the
    artifact under measurement, where a refactor can un-read it, the harness
    cannot see it, and it ships to customers as dead configuration.
    """
    _ensure_controller_importable()

    import app.utils.audit_logger as _audit_logger_mod
    import app.utils.metrics_publisher as _metrics_publisher_mod

    for module, attr, replacement in (
        (_metrics_publisher_mod, "MetricsPublisher", NullMetricsPublisher),
        (_audit_logger_mod, "AuditLogger", NullAuditWriter),
    ):
        _SUBSTITUTIONS.append((module, attr, getattr(module, attr)))
        setattr(module, attr, replacement)

    return NullMetricsPublisher.__name__, NullAuditWriter.__name__


def restore_substitutions() -> None:
    """Put the real symbols back. **Test support and run teardown only** — a run
    never calls this, and calling it mid-run re-arms the contamination path."""
    while _SUBSTITUTIONS:
        module, attr, original = _SUBSTITUTIONS.pop()
        setattr(module, attr, original)


# --------------------------------------------------------------------------- #
# The chain
# --------------------------------------------------------------------------- #
def enforce(
    *,
    transport: Optional[str] = None,
    base_url: Optional[str] = None,
) -> IsolationRecord:
    """Establish execution isolation. The first executable statement of every
    ``benchmarks/`` entry point.

    Args:
        transport: ``in-process`` (the effective default) or ``hosted``. Only
            ``hosted`` runs reach an endpoint, so only they are subject to I5.
            Defaults to ``None`` rather than to the string so the ``--transport``
            argv fallback can engage — a literal default would be truthy and
            would silently swallow ``--transport hosted``, downgrading I5 to a
            no-op on exactly the runs it exists for.
        base_url: the hosted engine endpoint. Falls back to ``--base-url`` on the
            command line when not passed, so I5 applies even pre-argparse.

    Returns:
        The :class:`IsolationRecord` WS-A serializes into ``manifest.isolation``.
        Hold it: ``release()`` unbinds the tenant at run end.

    Raises:
        SystemExit: with code **2** on every refusal path (I1, I3, I5).
    """
    transport = transport or _argv_option("transport") or "in-process"
    if base_url is None:
        base_url = _argv_option("base-url")

    # I1 — the badge.
    badge = _assert_badge()

    # I3 — BEFORE any mutation. Snapshot the real provider chain.
    _assert_no_live_credentials()

    # I2 — only now.
    credentials_state = _sentinelize_credentials()

    # I5 — hosted runs only.
    prod_target_check = _assert_not_production(transport, base_url)

    # I4 — before any app.* import that constructs a client.
    metrics_publisher, audit_writer = _install_null_objects()

    # Tenant bind — reuse the existing contextvar, hold the token.
    from app.utils import tenancy  # local: after I2 and after I4

    token = tenancy.set_current_tenant(BENCHMARK_TENANT)

    return IsolationRecord(
        tenant=BENCHMARK_TENANT,
        badge=badge,
        aws_credentials=credentials_state,
        metrics_publisher=metrics_publisher,
        audit_writer=audit_writer,
        prod_target_check=prod_target_check,
        tenant_token=token,
    )


# --------------------------------------------------------------------------- #
# Entry point — the isolation self-check
# --------------------------------------------------------------------------- #
def main() -> int:
    """``python -m benchmarks.core.isolation [--transport …] [--base-url …]``

    A minimal entry point that does nothing except establish isolation and print
    the resulting manifest block. It exists so the three refusal paths can be
    proven from a **subprocess** (``benchmarks/tests/test_isolation.py``, the M1
    exit gate) without depending on WS-A's ``run.py``, and it doubles as an
    operator check that a shell is safe to benchmark from.

    ``enforce()`` is the first executable statement — the argv fallback inside it
    is what makes that possible while still honouring ``--base-url``.
    """
    record = enforce()
    print(json.dumps(record.to_dict(), indent=2))
    record.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
