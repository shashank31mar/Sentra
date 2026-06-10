"""
Audit Logger for Security Controller

Writes validation decisions to CloudWatch Logs for audit trail.
All logging is asynchronous (fire-and-forget) to avoid blocking validation.

Workstream 17 (LLD 17): augmented with `log_signals()` — a dual-write that
adds per-validator rows to DynamoDB (`sentra-validation-signals`) alongside
the single combined CloudWatch event. Legacy `log_decision` is preserved
for callers that don't yet pass a Signals list; it routes through
`log_signals` internally so the new code path is the only writer.
"""
import logging
import json
import time
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

from app.combiners import Signal
from app.config import settings
from app.utils.signal_store_writer import SignalStoreWriter

logger = logging.getLogger(__name__)


class AuditLogger:
    """
    Writes audit logs to CloudWatch Logs.
    
    Log Structure:
    - Log Group: /sentra/audit-logs
    - Log Stream: One per session_id
    - Format: JSON for CloudWatch Insights queries
    """
    
    def __init__(self):
        self.cloudwatch_logs = boto3.client('logs', region_name=settings.aws_region)
        self.log_group = settings.cloudwatch_log_group
        self._ensure_log_group_exists()
        # DDB dual-write target — Workstream 17. Constructed lazily so unit
        # tests can monkey-patch or swap the writer without DDB connections.
        self._signal_store: Optional[SignalStoreWriter] = None

    def _get_signal_store(self) -> SignalStoreWriter:
        if self._signal_store is None:
            self._signal_store = SignalStoreWriter()
        return self._signal_store
    
    def _ensure_log_group_exists(self):
        """Create log group if it doesn't exist"""
        try:
            self.cloudwatch_logs.create_log_group(logGroupName=self.log_group)
            logger.info(f"Created CloudWatch log group: {self.log_group}")
        except ClientError as e:
            if e.response['Error']['Code'] != 'ResourceAlreadyExistsException':
                logger.warning(f"Could not create log group: {e}")
    
    async def log_decision(
        self,
        decision: str,
        request: Dict[str, Any],
        session: Dict[str, Any],
        validation_result: Optional[Dict[str, Any]] = None,
        latency_ms: float = 0.0
    ):
        """
        Legacy single-signal logger. Preserved for callers that haven't yet
        switched to log_signals. Internally routes through log_signals with a
        single synthesized Signal so the new write path is the only writer.

        Args:
            decision: ALLOW or DENY
            request: ValidationRequest dict
            session: Session context dict
            validation_result: Result from validator (for DENY)
            latency_ms: Validation latency in milliseconds
        """
        synthesized = self._synthesize_signal_from_legacy(decision, validation_result)
        await self.log_signals(
            request=request,
            session=session,
            signals=[synthesized],
            latency_ms=latency_ms,
        )

    @staticmethod
    def _synthesize_signal_from_legacy(
        decision: str, validation_result: Optional[Dict[str, Any]]
    ) -> Signal:
        """Build a Signal from the legacy (decision, validation_result) pair.

        Used for the back-compat path only. Real validators stamp their own
        source via the @stamps decorator now; this helper exists so callers
        that haven't migrated still produce a valid DDB row.
        """
        vr = validation_result or {}
        return Signal(
            source=vr.get("source") or "sentra.combined",
            decision=decision,
            reason=vr.get("reason") if decision == "DENY" else None,
            priority=0,
            threat_type=vr.get("threat_type"),
            matched_rule=vr.get("matched_rule"),
            severity=vr.get("severity"),
            metadata={
                "violation_type": vr.get("violation_type"),
                "violated_policy": vr.get("violated_policy"),
                "legacy_synthesized": True,
            },
        )

    async def log_signals(
        self,
        request: Dict[str, Any],
        session: Dict[str, Any],
        signals: List[Signal],
        latency_ms: float = 0.0,
    ):
        """Dual-write per-validator signals to DDB + a combined CloudWatch event.

        Workstream 17 / LLD 17 §7.
        - DDB write: best-effort, budgeted (200ms by default). Failure logs
          a warning but does not raise — CloudWatch event still goes.
        - CloudWatch event: existing single-event-per-validation format,
          augmented with a `signals[]` array carrying the contributors.

        Args:
            request: ValidationRequest dict.
            session: Session context dict.
            signals: List of Signal objects produced by the validators that
                ran. The first DENY signal (if any) drives the legacy
                `decision`/`reason` fields on the CloudWatch event so the
                existing CloudWatch consumers keep working unchanged.
            latency_ms: validate_tool_call latency.
        """
        # Pick the dominant signal for legacy CW fields. We use the same
        # deny-overrides semantics as the combiner — sigma-DENY beats
        # trust-ALLOW in the combined view. Importing the combiner here is
        # fine — this is the audit path, not the hot read path.
        #
        # IMPORTANT semantics for /v1/logs consumers (Kiro review P1):
        # the CloudWatch event's top-level `decision`/`reason`/`threat_type`
        # fields are now ALWAYS the deny-overrides combined verdict — even
        # on short-circuit paths where only one validator ran. This is
        # consistent with what /v1/validate returns to the caller and what
        # the legacy log_decision() emitted, but the *source* of the reason
        # may be a single validator (e.g. trust_checker on an early DENY)
        # while threat_type comes from that same validator's signal. The
        # full per-validator breakdown is always in the `signals[]` array
        # for any consumer that wants more granularity.
        from app.combiners import DenyOverrides
        combined = DenyOverrides().combine(signals) if signals else None
        decision = combined.decision if combined else "ALLOW"
        legacy_vr = self._legacy_vr_from_signal(combined) if combined else None

        # CloudWatch event (compliance archive — backward-compatible).
        try:
            log_event = self._build_log_event(
                decision=decision,
                request=request,
                session=session,
                validation_result=legacy_vr,
                latency_ms=latency_ms,
            )
            # Workstream 17 — add signals[] for new consumers.
            log_event["signals"] = [s.to_dict() for s in signals]
            await self._write_log_event(
                session_id=request.get("session_id"),
                log_event=log_event,
            )
        except Exception as e:
            logger.exception(f"Failed to write audit log to CloudWatch: {e}")

        # DDB dual-write (fast-read substrate).
        if signals:
            try:
                shared = self._shared_attrs_from_request(request, session)
                writer = self._get_signal_store()
                writer.write_signals(
                    session_id=request.get("session_id") or "unknown",
                    request_id=request.get("request_id") or "unknown",
                    signals=signals,
                    shared_attrs=shared,
                )
            except Exception as e:
                # Per LLD 17 §11: never raise into validation path.
                logger.warning(f"signal_store.write.failure (dual-write): {e}")

    @staticmethod
    def _legacy_vr_from_signal(signal: Signal) -> Dict[str, Any]:
        """Map a Signal back to the dict shape _build_log_event expects.

        Bridges the new combiner output to the existing CloudWatch event
        builder so we don't have to rewrite _build_log_event in this pass.
        """
        return {
            "reason": signal.reason,
            "threat_type": signal.threat_type,
            "matched_rule": signal.matched_rule,
            "severity": signal.severity,
            "violation_type": (signal.metadata or {}).get("violation_type"),
            "violated_policy": (signal.metadata or {}).get("violated_policy"),
            "platform": (signal.metadata or {}).get("platform"),
            "cloud_region": (signal.metadata or {}).get("cloud_region"),
        }

    @staticmethod
    def _shared_attrs_from_request(
        request: Dict[str, Any], session: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Build the shared-attribute dict propagated to every signal row.

        These attributes are query-friendly: filtering DDB items by agent_id
        or platform is much faster than parsing nested metadata.
        """
        trust_score_before = session.get("trust_score", 100.0)
        shared = {
            "agent_id": request.get("agent_id"),
            "tool_name": request.get("tool_name"),
            "tool_params": request.get("tool_params") or {},
            "user_input": (request.get("user_input") or "")[:200],
            "platform": request.get("platform"),
            "cloud_region": request.get("cloud_region"),
            "operation_type": request.get("operation_type"),
            "trust_score_before": trust_score_before,
        }
        # Caller IP (captured at the /v1/validate route from the gateway's X-Forwarded-For). Lets the
        # detail/forensics view answer "which IP called". Omitted (not written) when unknown.
        source_ip = (request.get("context") or {}).get("ip_address")
        if source_ip:
            shared["source_ip"] = source_ip
        return shared
    
    def _build_log_event(
        self,
        decision: str,
        request: Dict[str, Any],
        session: Dict[str, Any],
        validation_result: Optional[Dict[str, Any]],
        latency_ms: float
    ) -> Dict[str, Any]:
        """Build audit log event structure"""
        
        # Base event
        event = {
            "request_id": request.get("request_id"),
            "session_id": request.get("session_id"),
            "agent_id": request.get("agent_id"),
            "tool_name": request.get("tool_name"),
            "operation_type": request.get("operation_type"),
            "decision": decision,
            "timestamp": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
            "latency_ms": round(latency_ms, 2)
        }
        
        # Add trust score info
        trust_score_before = session.get("trust_score", 100.0)
        event["trust_score_before"] = trust_score_before
        
        if decision == "DENY" and validation_result:
            # DENY-specific fields
            event["reason"] = validation_result.get("reason", "Unknown")
            
            # Only include optional fields if they have values (not None)
            threat_type = validation_result.get("threat_type")
            if threat_type:
                event["threat_type"] = threat_type
            
            severity = validation_result.get("severity")
            if severity:
                event["severity"] = severity
            
            matched_rule = validation_result.get("matched_rule")
            if matched_rule:
                event["matched_rule"] = matched_rule
            
            violation_type = validation_result.get("violation_type")
            if violation_type:
                event["violation_type"] = violation_type
            
            # Calculate trust score after penalty
            penalty = validation_result.get("penalty", 0)
            trust_score_after = max(0.0, trust_score_before + penalty)
            event["trust_score_after"] = trust_score_after
            event["trust_delta"] = penalty
        else:
            # ALLOW-specific fields
            event["reason"] = "All validation checks passed"
            event["trust_score_after"] = trust_score_before
            event["trust_delta"] = 0.0
        
        # Add action_id for reversible actions
        if request.get("operation_type") == "WRITE" and request.get("tool_name") in ["process_refund"]:
            # Generate action_id for reversible actions
            timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            import secrets
            random_hex = secrets.token_hex(3)
            action_id = f"act-{request.get('tool_name')}-{timestamp_str}-{random_hex}"
            event["action_id"] = action_id
            event["reversible"] = True
            event["rollback_status"] = "NOT_ROLLED_BACK"
        
        # Add user input (truncated for security)
        user_input = request.get("user_input", "")
        event["user_input"] = user_input[:200] if len(user_input) > 200 else user_input
        
        # Add multi-agent context (Workstream 12)
        context = request.get("context", {})
        multi_agent_context = {
            "conversation_id": context.get("conversation_id"),
            "parent_request_id": context.get("parent_request_id"),
            "caller_agent_id": context.get("caller_agent_id"),
            "call_depth": context.get("call_depth", 0)
        }
        event["multi_agent_context"] = multi_agent_context
        
        # Add tool_params for rollback support
        event["tool_params"] = request.get("tool_params", {})

        # Workstream 15: cross-cloud audit fields. Prefer policy-derived values
        # on the validation_result; fall back to request-side hints from the
        # interceptor. Skip writing the fields if neither is available.
        result_platform = (validation_result or {}).get("platform") if validation_result else None
        result_region = (validation_result or {}).get("cloud_region") if validation_result else None
        platform = result_platform or request.get("platform")
        cloud_region = result_region or request.get("cloud_region")
        if platform:
            event["platform"] = platform
        if cloud_region:
            event["cloud_region"] = cloud_region

        return event
    
    async def _write_log_event(self, session_id: str, log_event: Dict[str, Any]):
        """
        Write log event to CloudWatch Logs.
        
        Uses session_id as log stream name for easy querying.
        """
        try:
            log_stream_name = session_id
            
            # Create log stream if it doesn't exist
            try:
                self.cloudwatch_logs.create_log_stream(
                    logGroupName=self.log_group,
                    logStreamName=log_stream_name
                )
            except ClientError as e:
                if e.response['Error']['Code'] != 'ResourceAlreadyExistsException':
                    raise
            
            # Put log event
            self.cloudwatch_logs.put_log_events(
                logGroupName=self.log_group,
                logStreamName=log_stream_name,
                logEvents=[
                    {
                        'timestamp': int(time.time() * 1000),
                        'message': json.dumps(log_event)
                    }
                ]
            )
            
            logger.debug(f"Wrote audit log for session {session_id}")
            
        except Exception as e:
            logger.exception(f"Failed to write log event to CloudWatch: {e}")
            # Don't raise - logging failures should not block validation

    async def query_logs_by_conversation(
        self,
        conversation_id: str,
        start_time_hours_ago: int = 24
    ) -> list:
        """
        Query all audit logs for a conversation using CloudWatch Logs Insights.
        
        Args:
            conversation_id: Conversation identifier
            start_time_hours_ago: How far back to search (default 24 hours)
            
        Returns:
            List of log entries sorted by timestamp
        """
        try:
            # Build CloudWatch Logs Insights query
            query = f"""
            fields @timestamp, @message
            | filter multi_agent_context.conversation_id = "{conversation_id}"
            | sort @timestamp asc
            | limit 1000
            """
            
            # Calculate time range
            end_time = int(time.time())
            start_time = end_time - (start_time_hours_ago * 3600)
            
            # Start query
            response = self.cloudwatch_logs.start_query(
                logGroupName=self.log_group,
                queryString=query,
                startTime=start_time,
                endTime=end_time
            )
            
            query_id = response['queryId']
            
            # Wait for query to complete (with timeout)
            max_attempts = 30
            for attempt in range(max_attempts):
                result = self.cloudwatch_logs.get_query_results(queryId=query_id)
                status = result['status']
                
                if status == 'Complete':
                    break
                elif status in ['Failed', 'Cancelled']:
                    logger.error(f"CloudWatch Logs query {status}: {query_id}")
                    return []
                
                time.sleep(0.5)
            else:
                logger.error(f"CloudWatch Logs query timed out: {query_id}")
                return []
            
            # Parse results
            logs = []
            for row in result.get('results', []):
                message_field = next(
                    (f for f in row if f['field'] == '@message'),
                    None
                )
                if message_field:
                    try:
                        log_entry = json.loads(message_field['value'])
                        logs.append(log_entry)
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse log entry: {message_field['value'][:100]}")
            
            logger.info(
                f"Found {len(logs)} logs for conversation {conversation_id}",
                extra={"conversation_id": conversation_id, "count": len(logs)}
            )
            return logs
            
        except ClientError as e:
            logger.exception(f"CloudWatch Logs query failed: {e}")
            return []
        except Exception as e:
            logger.exception(f"Unexpected error querying logs: {e}")
            return []
