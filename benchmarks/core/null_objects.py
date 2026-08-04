"""Null stand-ins for the two AWS-writing utilities the in-process rig reaches.

LLD 41 §4.7 (I4) / §11 stores #4 and #5 · WS-B milestone B2.

Why these exist
---------------
Two of the seven AWS-touching stores on the in-process validate path build their
boto3 client **directly in ``__init__``**, bypassing the ``app.utils.clients``
registry, so there is no existing seam to swap:

* ``MetricsPublisher.__init__`` → ``boto3.client('cloudwatch')``
  (``app/utils/metrics_publisher.py:34``), reached lazily from
  ``sigma_engine.py:362`` / ``:478``. **This is the observed live contamination
  path**: a smoke run of ``scripts/meas_d2_d3_fp_budget.py`` already called
  ``PutMetricData`` with no AWS deployment, and only failed because that shell's
  credentials happened to be fake.
* ``AuditLogger.__init__`` → ``boto3.client('logs')``
  (``app/utils/audit_logger.py:110``), reached through
  ``_fire_and_forget(...)`` at ``validation_service.py:912,925``. Being
  fire-and-forget, a failure here is *swallowed* rather than surfaced — which is
  exactly why a null object rather than the credential floor is the primary
  control for that store.

These are the **cleanliness and performance layer**, not the correctness floor.
The floor is I2 (credential sentinelization in :mod:`benchmarks.core.isolation`):
even with every null object missing, an AWS call fails at the API with
``InvalidClientTokenId``. What these buy is a quiet, fast run — no wasted network
attempts and no 30-second botocore retry storms inside a 40-minute run. The two
mechanisms are independent by design: forgetting either still fails safe.

The catch-all, and the assumption it rests on
---------------------------------------------
Method parity is provided structurally by ``__getattr__`` rather than by a
hand-maintained list of no-ops: ``MetricsPublisher`` carries ~20 public methods
and grows, and a missing one is an ``AttributeError`` four hours into a run.
The catch-all returns a **coroutine** function because every public method on
both real classes is ``async``. That assumption is not left implicit — it is
pinned by ``benchmarks/tests/test_null_objects.py``, which introspects the real
classes and fails if a public *sync* method ever appears (at which point the
catch-all would hand back an un-awaited coroutine and silently do nothing).
"""
from __future__ import annotations

from collections import Counter


class _CountingNullObject:
    """Base for a null object that swallows every public call and counts it.

    The counting is not decoration: the run manifest reports "0 CloudWatch calls
    attempted" as *evidence* rather than as an assertion (LLD 41 §4.7), and that
    number has to come from somewhere.
    """

    def __init__(self, *args, **kwargs):
        # Accept whatever the real constructor accepts and build nothing. The
        # whole point is that no boto3 client is constructed here.
        self._calls: Counter = Counter()

    # -- introspection ----------------------------------------------------- #
    @property
    def calls(self) -> Counter:
        """Per-method-name call counts. A property (not an instance attribute)
        so it resolves through normal lookup and never reaches ``__getattr__``."""
        return self._calls

    @property
    def total_calls(self) -> int:
        return sum(self._calls.values())

    # -- the catch-all ------------------------------------------------------ #
    def __getattr__(self, name: str):
        # Private / dunder names are NOT swallowed: an internal attribute that
        # does not exist should fail loudly rather than resolve to a no-op
        # coroutine (this also keeps `self._calls` honest before __init__ runs).
        if name.startswith("_"):
            raise AttributeError(
                f"{type(self).__name__} has no attribute {name!r} "
                "(private names are not null-substituted)"
            )

        async def _null_call(*args, **kwargs):
            self._calls[name] += 1
            return None

        _null_call.__name__ = name
        _null_call.__qualname__ = f"{type(self).__name__}.{name}"
        _null_call.__doc__ = (
            f"Null no-op standing in for {type(self).__name__}.{name} "
            "(LLD 41 §4.7 I4). Records the call; performs no I/O."
        )
        return _null_call


class NullMetricsPublisher(_CountingNullObject):
    """Substituted over ``app.utils.metrics_publisher.MetricsPublisher``.

    Mirrors the real object's public *data* attributes so a caller that reads
    ``.namespace`` gets a string rather than a coroutine factory. ``cloudwatch``
    is deliberately ``None`` — a code path that reaches for the client itself,
    rather than going through a publish method, must fail loudly instead of
    silently succeeding against nothing.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.namespace = "Sentra/SecurityController"
        self.cloudwatch = None


class NullAuditWriter(_CountingNullObject):
    """Substituted over ``app.utils.audit_logger.AuditLogger``.

    Covers ``log_signals`` and ``log_decision`` (the two the validate path fires)
    plus everything else on the class via the catch-all. ``cloudwatch_logs`` is
    ``None`` for the same reason as ``NullMetricsPublisher.cloudwatch``; the log
    group names are carried as plain strings because they are read, not called.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cloudwatch_logs = None
        self.log_group = "_benchmark/null-audit"
        self.canary_log_group = "_benchmark/null-audit-canary"
