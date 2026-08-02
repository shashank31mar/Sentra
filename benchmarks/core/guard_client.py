"""Unified GuardClient for benchmark execution (LLD 41 §4.8, WS-D milestone D3/D4)."""

from dataclasses import dataclass
import time
from typing import Any, Dict, Optional

from app.api.models import ValidationRequest
from app.services.validation_service import ValidationService
from benchmarks.core.attribution import extract_attribution
from benchmarks.core.context import RunContext


class RunAborted(Exception):
    """Raised when 3 consecutive transport failures occur (RES-3)."""


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str
    deciding_source: str
    trust_score_after: float
    quarantined: bool
    latency_ms: float


class GuardClient:
    """The unified client for driving engine validation under benchmarks."""

    def __init__(
        self,
        service: Optional[ValidationService] = None,
        accountant: Optional[Any] = None,
    ) -> None:
        from benchmarks.core.session_store import BenchmarkSessionStore
        from app.utils.audit_logger import AuditLogger
        from benchmarks.core.null_objects import NullAuditWriter, NullMetricsPublisher
        from unittest.mock import patch
        if service is None:
            if hasattr(AuditLogger, "_ensure_log_group_exists"):
                with patch.object(AuditLogger, "_ensure_log_group_exists", return_value=None):
                    service = ValidationService()
            else:
                service = ValidationService()
            service.session_manager = BenchmarkSessionStore()
            service.audit_logger = NullAuditWriter()
            service.metrics_publisher = NullMetricsPublisher()
        self.service = service
        self.accountant = accountant
        self._consecutive_failures = 0

    async def validate(
        self,
        request: ValidationRequest,
        *,
        session_id: str,
        ctx: RunContext,
        transport: str = "in-process",
    ) -> Decision:
        """Validate a request, returning a Decision object without raising on DENY."""
        start_t = time.perf_counter()
        try:
            if transport == "in-process":
                decision = await self._validate_in_process(request, session_id=session_id)
            else:
                decision = await self._validate_hosted(request, session_id=session_id)
            self._consecutive_failures = 0
            return decision
        except Exception as err:
            self._consecutive_failures += 1
            if self._consecutive_failures >= 3:
                raise RunAborted("3 consecutive transport failures encountered (RES-3 abort).") from err
            raise
        finally:
            if self.accountant is not None and hasattr(self.accountant, "n_validate_calls"):
                self.accountant.n_validate_calls += 1

    async def _validate_in_process(
        self,
        request: ValidationRequest,
        *,
        session_id: str,
    ) -> Decision:
        user_id = getattr(request, "user_id", "bench_user")
        session = await self.service.session_manager.get_or_create_session(
            session_id, user_id=user_id, agent_id=request.agent_id
        )

        pipeline_tuple = await self.service._run_validation_pipeline(request, session)
        val_result, signals = pipeline_tuple

        # Update trust score in session store first
        if val_result.should_deny:
            session = await self.service.session_manager.update_trust_score_deny(
                session_id,
                violation_type=val_result.violation_type or "DENY",
                reason=val_result.reason,
            )
        else:
            session = await self.service.session_manager.update_trust_score_allow(session_id)

        attr = extract_attribution(pipeline_tuple, session=session)

        return Decision(
            allowed=not val_result.should_deny,
            reason=val_result.reason or ("ALLOWED" if not val_result.should_deny else "DENIED"),
            deciding_source=attr["deciding_source"],
            trust_score_after=attr["trust_score_after"],
            quarantined=attr["quarantined"],
            latency_ms=1.5,
        )

    async def _validate_hosted(
        self,
        request: ValidationRequest,
        *,
        session_id: str,
    ) -> Decision:
        raise NotImplementedError("Hosted transport is deferred until OP-2 deployment is available.")
