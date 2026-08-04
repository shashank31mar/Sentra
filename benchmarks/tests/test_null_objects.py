"""Unit tests for I4 — the null objects and the timing of their substitution.

LLD 41 §4.7 (I4) / §11 stores #4 and #5 · WS-B B2.

Method parity is provided structurally by ``_CountingNullObject.__getattr__``
rather than by a hand-written list, so these tests pin the *assumption the
catch-all rests on* — that every public method of both real classes is
``async`` — rather than merely re-asserting that ``hasattr`` is true. If a public
sync method is ever added to either class, the catch-all would hand back an
un-awaited coroutine and silently do nothing; these tests fail first.
"""
from __future__ import annotations

import asyncio
import inspect
import subprocess
import sys
import textwrap

import pytest

from benchmarks.core.null_objects import NullAuditWriter, NullMetricsPublisher

from .conftest import REPO_ROOT, hermetic_subprocess_env


def _public_methods(cls) -> list:
    """Public methods defined on (or inherited by) ``cls`` — the surface a
    consumer can call and therefore the surface the null object must cover."""
    return sorted(
        name
        for name, _member in inspect.getmembers(cls, inspect.isfunction)
        if not name.startswith("_")
    )


def _assert_full_parity(real_cls, null_obj) -> list:
    names = _public_methods(real_cls)
    assert names, (
        f"introspection found no public methods on {real_cls.__name__} — the "
        "parity assertion below would be vacuous"
    )
    for name in names:
        real_method = getattr(real_cls, name)
        assert inspect.iscoroutinefunction(real_method), (
            f"{real_cls.__name__}.{name} is not async, but the null object's "
            "catch-all returns a coroutine function for every public name. A "
            "sync caller would get an un-awaited coroutine and a silent no-op — "
            "add an explicit sync no-op for this method."
        )
        null_method = getattr(null_obj, name)
        assert callable(null_method)
        assert inspect.iscoroutinefunction(null_method), (
            f"{type(null_obj).__name__}.{name} must be awaitable to stand in for "
            f"{real_cls.__name__}.{name}"
        )
        assert asyncio.run(null_method()) is None
        assert null_obj.calls[name] == 1
    return names


def test_null_metrics_publisher_swallows_publish():
    """Every public method of the real ``MetricsPublisher`` has an awaitable
    no-op counterpart that performs no I/O. A missing one is an ``AttributeError``
    four hours into a run."""
    from app.utils.metrics_publisher import MetricsPublisher

    assert MetricsPublisher is not NullMetricsPublisher, (
        "a prior test leaked the I4 substitution — this test would then be "
        "introspecting the null object against itself"
    )

    null = NullMetricsPublisher()
    names = _assert_full_parity(MetricsPublisher, null)

    # The known contamination path specifically (sigma_engine.py:362).
    assert "publish_sigma_alarm_metric" in names
    assert "publish_validation_metrics" in names
    # No client was built, and a caller that reaches for one fails loudly rather
    # than succeeding against nothing.
    assert null.cloudwatch is None
    assert null.namespace == "Sentra/SecurityController"
    assert null.total_calls == len(names)


def test_null_audit_writer_swallows_log_signals_and_log_decision():
    """``log_signals`` / ``log_decision`` are fired-and-forgotten at
    ``validation_service.py:912,925``, so a failure there is swallowed rather
    than surfaced — which is why the null object, not the credential floor, is
    the primary control for this store."""
    from app.utils.audit_logger import AuditLogger

    assert AuditLogger is not NullAuditWriter

    null = NullAuditWriter()
    names = _assert_full_parity(AuditLogger, null)

    assert "log_signals" in names
    assert "log_decision" in names
    assert null.cloudwatch_logs is None
    assert null.total_calls == len(names)


def test_null_objects_record_call_counts():
    """The manifest reports "0 CloudWatch calls attempted" as *evidence* rather
    than as an assertion, so the null objects have to count."""
    metrics = NullMetricsPublisher()
    audit = NullAuditWriter()

    assert metrics.total_calls == 0
    assert audit.total_calls == 0

    asyncio.run(metrics.publish_sigma_alarm_metric("PromptSignatureRulesUnavailable"))
    asyncio.run(metrics.publish_sigma_alarm_metric("PromptSignatureRulesStalePinned"))
    asyncio.run(metrics.publish_validation_metrics("DENY", 12.5, "agent-1", 0.4))
    asyncio.run(audit.log_decision({"decision": "DENY"}))

    assert metrics.calls["publish_sigma_alarm_metric"] == 2
    assert metrics.calls["publish_validation_metrics"] == 1
    assert metrics.total_calls == 3
    assert audit.calls["log_decision"] == 1
    assert audit.total_calls == 1

    # Counters are per-instance, not class state.
    assert NullMetricsPublisher().total_calls == 0


def test_null_objects_do_not_swallow_private_names():
    """A private attribute that does not exist must raise, not resolve to a no-op
    coroutine — otherwise an internal probe like ``getattr(self, "_x", None)``
    silently changes meaning."""
    null = NullMetricsPublisher()
    with pytest.raises(AttributeError):
        null._not_a_real_attribute


def test_substitution_lands_before_app_import():
    """The substitution must land **before** the app modules that consume the
    symbols are imported — and only a subprocess can prove an ordering.

    ``sigma_engine`` imports ``MetricsPublisher`` lazily *inside* the method
    (``sigma_engine.py:361``), so it would resolve through ``sys.modules`` at call
    time whatever the order. The module-scope consumers are where the ordering
    actually bites: ``app/services/conversation_service.py:14`` binds
    ``AuditLogger`` at import, so if ``enforce()`` ran after that import it would
    hold the real, CloudWatch-constructing class for the rest of the run.
    """
    script = textwrap.dedent(
        """
        import sys

        assert "app.utils.metrics_publisher" not in sys.modules
        assert "app.utils.audit_logger" not in sys.modules
        assert "app.services.conversation_service" not in sys.modules

        from benchmarks.core import isolation
        from benchmarks.core.null_objects import NullAuditWriter, NullMetricsPublisher

        record = isolation.enforce()

        assert sys.modules["app.utils.metrics_publisher"].MetricsPublisher \\
            is NullMetricsPublisher
        assert sys.modules["app.utils.audit_logger"].AuditLogger is NullAuditWriter

        # Imported AFTER enforce() — the lazy consumer resolves to the null symbol.
        import app.validators.sigma_engine  # noqa: F401
        from app.utils.metrics_publisher import MetricsPublisher
        assert MetricsPublisher is NullMetricsPublisher

        # The module-scope consumer: this is the assertion that fails if the
        # substitution is moved after the app imports.
        import app.services.conversation_service as conversation_service
        assert conversation_service.AuditLogger is NullAuditWriter

        record.release()
        print("SUBSTITUTION-OK")
        """
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(REPO_ROOT),
        env=hermetic_subprocess_env(),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert "SUBSTITUTION-OK" in result.stdout
