"""
API Routes for Security Controller

Implements all REST endpoints:
- GET /v1/health - Health check with dependency verification
- POST /v1/validate - Tool call validation with 5-step pipeline
- GET /v1/logs - Query audit logs (Task 10)
- GET /v1/sessions - Query sessions (Task 11)
- GET /v1/metrics - Query summary metrics (Task 11)

All business logic is delegated to service classes in app/services/.
Routes are kept clean and focused on HTTP handling only.
"""
import logging
from typing import Dict, Optional

from fastapi import APIRouter, HTTPException, Header, Request

from app.api.models import (
    ValidationRequest,
    PolicyCreateRequest,
    PolicyUpdateRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1")


@router.get("/health")
async def health_check() -> Dict:
    """
    Health check endpoint with dependency verification.
    
    Checks connectivity to:
    - DynamoDB (sentra-session-context, sentra-policies)
    - S3 (sentra-mvp-artifacts)
    - CloudWatch Logs
    
    Returns:
        200 OK if all dependencies are healthy
        503 Service Unavailable if any dependency is unhealthy
    """
    from app.services import HealthService
    
    health_service = HealthService()
    response, is_healthy = await health_service.check_health()
    
    if not is_healthy:
        raise HTTPException(status_code=503, detail=response)
    
    return response


@router.post("/validate")
async def validate_tool_call(request: ValidationRequest, http_request: Request) -> Dict:
    """
    Validate tool call before execution.

    Runs 5-step validation pipeline:
    1. Trust Score Check (fail-fast if suspended/quarantined)
    2. Policy Engine (agent authorization)
    3. Sigma Rule Engine (threat detection)
    4. Context Validator (tool sequence validation)
    5. Abuse Detector (rate limiting)

    Returns:
        ValidationResponse (ALLOW) or ValidationDenyResponse (DENY)
    """
    from app.services import ValidationService

    # Capture the caller IP for the audit trail / forensics view. Behind API Gateway + VPC Link the
    # real client is the first hop of X-Forwarded-For; fall back to the socket peer. Stored on the
    # request context so it propagates to every signal row (audit_logger._shared_attrs_from_request).
    xff = http_request.headers.get("x-forwarded-for")
    source_ip = (xff.split(",")[0].strip() if xff else None) or (
        http_request.client.host if http_request.client else None
    )
    if source_ip:
        request.context = {**(request.context or {}), "ip_address": source_ip}

    validation_service = ValidationService()
    return await validation_service.validate_tool_call(request)


# ============================================================
# Task 10: GET /v1/logs - Query Audit Logs
# ============================================================

@router.get("/logs")
async def get_logs(
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit: int = 100,
    session_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    decision: Optional[str] = None,
    threat_type: Optional[str] = None
) -> Dict:
    """
    Query audit logs from CloudWatch Logs.
    
    Query Parameters:
        since: Start time (ISO 8601 timestamp, default: 1 hour ago)
        until: End time (ISO 8601 timestamp, default: now)
        limit: Max results (default: 100, max: 1000)
        session_id: Filter by session ID
        agent_id: Filter by agent ID
        decision: Filter by decision (ALLOW/DENY)
        threat_type: Filter by threat type
    
    Returns:
        LogsResponse with logs array, total, has_more, next_token
    """
    from app.services.logs_service import LogsService
    
    logs_service = LogsService()
    return await logs_service.query_logs(
        since=since,
        until=until,
        limit=limit,
        session_id=session_id,
        agent_id=agent_id,
        decision=decision,
        threat_type=threat_type
    )


# ============================================================
# Workstream 17 / LLD 17 — Validation Signal Store endpoints
# ============================================================


def _decisions_service():
    """Lazy singleton — boto3 client init has nontrivial cold-start cost."""
    from app.services.decisions_service import DecisionsService
    global _decisions_service_instance
    try:
        return _decisions_service_instance
    except NameError:
        _decisions_service_instance = DecisionsService()
        return _decisions_service_instance


@router.get("/sessions/{session_id}/decisions")
async def get_session_decisions(
    session_id: str,
    request_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    limit: int = 100,
) -> Dict:
    """LLD 17 §8.2 — signals grouped by request_id, combiner applied per group.

    Dashboard hot path. p95 target ≤100ms (single DDB partition Query).
    """
    return _decisions_service().get_session_decisions(
        session_id=session_id, request_id=request_id, agent_id=agent_id, limit=limit
    )


@router.get("/sessions/{session_id}/signals")
async def get_session_signals(
    session_id: str,
    request_id: Optional[str] = None,
    source: Optional[str] = None,
    agent_id: Optional[str] = None,
    limit: int = 100,
) -> Dict:
    """LLD 17 §8.3 — raw signal list, no combiner applied. For debugging /
    advanced UI drill-down."""
    return _decisions_service().get_session_signals(
        session_id=session_id, request_id=request_id, source=source,
        agent_id=agent_id, limit=limit,
    )


@router.get("/decisions")
async def scan_decisions(
    since: Optional[str] = None,
    until: Optional[str] = None,
    agent_id: Optional[str] = None,
    decision: Optional[str] = None,
    threat_type: Optional[str] = None,
    session_id: Optional[str] = None,
    limit: int = 50,
    cursor: Optional[str] = None,
) -> Dict:
    """LLD 17 §8.4 — paginated time-range scan via GSI 2.

    For cross-session views. The cursor is an opaque base64 token —
    consumers must round-trip it unchanged.
    """
    try:
        return _decisions_service().scan_decisions(
            since=since, until=until, agent_id=agent_id,
            decision=decision, threat_type=threat_type, session_id=session_id,
            limit=limit, cursor=cursor,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/sessions/{session_id}/signals", status_code=201)
async def post_session_signal(session_id: str, signal: Dict) -> Dict:
    """LLD 17 §8.1 — external producer signal write (Bedrock/Azure connectors).

    Validates source against taxonomy (lenient — unknown sources are
    stored with priority=0 plus a warning). Returns 400 on malformed
    payload, 201 on success.
    """
    try:
        return _decisions_service().post_signal(
            session_id=session_id, signal_data=signal
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


# ============================================================
# Task 11: GET /v1/sessions - Query Sessions
# ============================================================

@router.get("/sessions")
async def get_sessions(
    status: Optional[str] = None,
    agent_id: Optional[str] = None,
    limit: int = 50
) -> Dict:
    """
    Query active sessions from DynamoDB.
    
    Query Parameters:
        status: Filter by quarantine status (active/quarantined/suspended)
        agent_id: Filter by agent ID
        limit: Max results (default: 50, max: 200)
    
    Returns:
        SessionsResponse with sessions array and total count
    """
    from app.utils.session_manager import SessionManager
    
    session_manager = SessionManager()
    return await session_manager.query_sessions(
        status=status,
        agent_id=agent_id,
        limit=limit
    )


# ============================================================
# Task 11: GET /v1/metrics - Query Summary Metrics
# ============================================================

@router.get("/metrics")
async def get_metrics(
    since: Optional[str] = None,
    until: Optional[str] = None
) -> Dict:
    """
    Query summary metrics from CloudWatch Logs.
    
    Query Parameters:
        since: Start time (ISO 8601 timestamp, default: 1 hour ago)
        until: End time (ISO 8601 timestamp, default: now)
    
    Returns:
        MetricsResponse with aggregated metrics
    """
    from app.services.metrics_service import MetricsService
    
    metrics_service = MetricsService()
    return await metrics_service.query_metrics(
        since=since,
        until=until
    )


# ============================================================
# Workstream 21: SOC Console dashboard metrics (T20-T22)
# Served from CloudWatch Metrics (GetMetricData) + DDB joins. See LLD 21 §10.6.
# ============================================================

_VALID_METRIC_RANGES = {"1h", "24h", "7d", "30d"}


def _trust_status(score: Optional[float]) -> str:
    """Map a 0-100 trust score to a status band (LLD 21 §11.2)."""
    if score is None:
        return "unknown"
    if score >= 80:
        return "healthy"
    if score >= 50:
        return "degraded"
    return "critical"


@router.get("/metrics/overview")
async def get_metrics_overview(range: str = "24h") -> Dict:
    """WS-21 T20: single call backing the dashboard KPI cards.

    CloudWatch (GetMetricData) for counts/latency/deny/trust + DDB for
    agent/provider/session counts. P0: delta% and false_positive_pct are null.
    """
    if range not in _VALID_METRIC_RANGES:
        raise HTTPException(
            status_code=400,
            detail=f"range must be one of {sorted(_VALID_METRIC_RANGES)}",
        )
    from app.services.metrics_query_service import MetricsQueryService
    from app.services.agent_service import AgentService
    from app.utils.session_manager import SessionManager

    mq = MetricsQueryService()
    cw = mq.overview(range)
    distribution = await AgentService().get_cloud_provider_distribution()
    session_manager = SessionManager()
    quarantined = await session_manager.count_sessions_by_status("quarantined")
    suspended = await session_manager.count_sessions_by_status("suspended")
    below_threshold = await session_manager.count_agents_below_trust(70.0)

    # WS-21 T01: keep the CloudWatch session gauges (QuarantinedSessions /
    # SuspendedSessions) fresh. The controller has no scheduler, so we emit the
    # fleet gauge on dashboard reads (cadence = dashboard load). Fire-and-forget;
    # the console itself reads the counts above straight from DDB.
    from app.utils.metrics_publisher import MetricsPublisher
    await MetricsPublisher().publish_session_metrics(quarantined, suspended)

    return {
        "range": range,
        "threats_blocked": cw["threats_blocked"],
        "threats_blocked_delta_pct": None,  # P0: prior-window compare not wired
        "attack_categories": mq.attack_category_count(),
        "active_agents": distribution["total_nodes"],
        "clouds": distribution["clouds"],
        "trust_score": cw["trust_score"],
        "trust_status": _trust_status(cw["trust_score"]),
        "agents_below_threshold": below_threshold,
        "requests_total": cw["requests_total"],
        "avg_latency_ms": cw["avg_latency_ms"],
        "quarantined": quarantined,
        "false_positive_pct": None,  # P0: captured silently via verdict (T34), not shown
    }


@router.get("/metrics/platform-distribution")
async def get_platform_distribution() -> Dict:
    """WS-21 T21: agent counts grouped by hosting cloud_provider."""
    from app.services.agent_service import AgentService

    distribution = await AgentService().get_cloud_provider_distribution()
    return {
        "total_nodes": distribution["total_nodes"],
        "providers": distribution["providers"],
    }


@router.get("/metrics/decisions-timeseries")
async def get_decisions_timeseries(range: str = "24h", bucket: str = "1h") -> Dict:
    """WS-21 T22: allowed-vs-blocked dense time-series (Chart.js area chart)."""
    if range not in _VALID_METRIC_RANGES:
        raise HTTPException(
            status_code=400,
            detail=f"range must be one of {sorted(_VALID_METRIC_RANGES)}",
        )
    from app.services.metrics_query_service import MetricsQueryService

    try:
        return MetricsQueryService().decisions_timeseries(range, bucket)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# ============================================================
# Workstream 21 Phase 3: Discovery (read-model), attach, verdict (T30-T34)
# ============================================================

@router.get("/discovery/agents")
async def discovery_agents(
    cloud_provider: Optional[str] = None,
    framework: Optional[str] = None,
    risk: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    cursor: Optional[str] = None,
) -> Dict:
    """WS-21 T32: detected-agents table (static, policy-derived read-model)."""
    from app.services.discovery_service import DiscoveryService
    try:
        return await DiscoveryService().list_discovered(
            cloud_provider=cloud_provider, framework=framework, risk=risk,
            status=status, limit=limit, cursor=cursor,
        )
    except ValueError as exc:  # malformed cursor
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/discovery/summary")
async def discovery_summary() -> Dict:
    """WS-21 T32: discovery KPI cards."""
    from app.services.discovery_service import DiscoveryService
    return await DiscoveryService().summary()


@router.get("/discovery/platforms")
async def discovery_platforms() -> Dict:
    """WS-21 T32: per-cloud-provider detected counts (status idle in P0)."""
    from app.services.discovery_service import DiscoveryService
    return await DiscoveryService().platforms()


@router.post("/discovery/import", status_code=201)
async def discovery_import(request: Dict) -> Dict:
    """WS-21 T32: promote discovered agents to managed (D2 contract)."""
    from app.services.discovery_service import DiscoveryService
    agent_ids = request.get("agent_ids")
    enforcement_mode = request.get("enforcement_mode", "monitor")
    try:
        return await DiscoveryService().import_agents(agent_ids or [], enforcement_mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/agents/{agent_id}/policies")
async def attach_agent_policy(agent_id: str, request: Dict) -> Dict:
    """WS-21 T33: attach a policy to an agent."""
    policy_id = request.get("policy_id")
    if not policy_id:
        raise HTTPException(status_code=400, detail="policy_id is required")
    from app.services.agent_service import AgentService
    try:
        return await AgentService().attach_policy(agent_id, policy_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.delete("/agents/{agent_id}/policies/{policy_id}")
async def detach_agent_policy(agent_id: str, policy_id: str) -> Dict:
    """WS-21 T33: detach a policy from an agent."""
    from app.services.agent_service import AgentService
    try:
        return await AgentService().detach_policy(agent_id, policy_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post("/decisions/{decision_id}/verdict")
async def post_decision_verdict(decision_id: str, request: Dict) -> Dict:
    """WS-21 T34: capture an operator FP/FN verdict (silent in P0). decision_id
    = '<session_id>:<request_id>'."""
    valid = {"false_positive", "confirmed_threat", "false_negative", "confirmed_safe"}
    verdict = request.get("verdict")
    reason = request.get("reason")
    operator_id = request.get("operator_id")
    if verdict not in valid:
        raise HTTPException(status_code=400, detail=f"verdict must be one of {sorted(valid)}")
    if not reason or not operator_id:
        raise HTTPException(status_code=400, detail="reason and operator_id are required")
    try:
        return _decisions_service().record_verdict(decision_id, verdict, reason, operator_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


# ============================================================
# Task 5: GET /v1/agents - Agent Management APIs
# ============================================================

@router.get("/agents")
async def get_agents(enrich: bool = True) -> Dict:
    """
    List all registered agents.
    
    Args:
        enrich: If True (default), include runtime statistics. Set to False for fast response.
    
    Returns:
        AgentsResponse with agents array and total count
        
    Response Fields (per agent):
        - agent_id: Agent identifier
        - name: Agent display name
        - platform: Platform (sentra/bedrock)
        - security_type: Security type (secured/unsecured)
        - visibility: Visibility (external/internal)
        - type: Agent type (query/action/orchestrator)
        - status: Agent status from DynamoDB
        
    Additional fields when enrich=true:
        - uptime_seconds: Service uptime in seconds
        - last_seen: Last activity timestamp (ISO 8601)
        - trust_score_avg: Average trust score across sessions
        - requests_total: Total requests (last 24h)
        - requests_allowed: Allowed requests count
        - requests_denied: Denied requests count
        - active_sessions: Number of active sessions
    """
    from app.services.agent_service import AgentService
    
    agent_service = AgentService()
    return await agent_service.list_agents(enrich=enrich)


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str) -> Dict:
    """
    Get detailed information about a specific agent.
    
    Path Parameters:
        agent_id: Agent identifier
    
    Returns:
        Agent details with runtime statistics
        
    HTTP Status Codes:
        200 OK - Agent found
        404 Not Found - Agent doesn't exist
    """
    from app.services.agent_service import AgentService
    
    agent_service = AgentService()
    agent = await agent_service.get_agent(agent_id)
    
    if not agent:
        raise HTTPException(
            status_code=404,
            detail=f"Agent {agent_id} not found"
        )
    
    return agent


@router.get("/agents/{agent_id}/tools")
async def get_agent_tools(agent_id: str) -> Dict:
    """
    Get list of allowed tools for an agent.
    
    Path Parameters:
        agent_id: Agent identifier
    
    Returns:
        ToolsResponse with tools array and total count
        
    Response Fields (per tool):
        - tool_id: Tool identifier
        - name: Tool name
        - type: Tool type (READ/WRITE/ADMIN)
        - description: Tool description
        - parameters: Tool parameters schema
        - rate_limit: Rate limit (requests per minute)
    
    HTTP Status Codes:
        200 OK - Success (empty array if agent has no tools)
        404 Not Found - Agent doesn't exist
    """
    from app.services.agent_service import AgentService
    
    agent_service = AgentService()
    result = await agent_service.get_agent_tools(agent_id)
    
    # Check if agent exists (service returns empty tools array for non-existent agents)
    # We need to verify agent exists first
    if result.get('error') and 'not found' in result.get('error', '').lower():
        raise HTTPException(
            status_code=404,
            detail=f"Agent {agent_id} not found"
        )
    
    return result


# ============================================================
# Task 6: GET /v1/policies and GET /v1/sigma-rules
# ============================================================

@router.get("/policies")
async def get_policies(
    agent_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
    cursor: Optional[str] = None
) -> Dict:
    """
    Query agent policies with optional filters.
    
    Query Parameters:
        agent_id: Filter by agent ID (optional)
        status: Filter by status (active/inactive/deprecated) (optional)
        limit: Max results (default: 50, max: 200)
    
    Returns:
        PoliciesResponse with policies array, total, and has_more flag
        
    Response Fields (per policy):
        - policy_id: Policy identifier
        - agent_id: Agent this policy applies to
        - name: Policy name
        - description: Policy description
        - status: Policy status (active/inactive/deprecated)
        - rule: Policy rule expression
        - action: Action to take (DENY/ALLOW/WARN)
        - severity: Severity level (critical/high/medium/low)
        - match_count_24h: Number of matches in last 24 hours
        - created_at: Creation timestamp
        - updated_at: Last update timestamp
    
    HTTP Status Codes:
        200 OK - Success (empty array if no matches)
        400 Bad Request - Invalid status or limit
    """
    from app.services.policy_service import PolicyService
    
    # Validate limit
    if limit < 1 or limit > 200:
        raise HTTPException(
            status_code=400,
            detail="Limit must be between 1 and 200"
        )
    
    # Validate status if provided
    valid_statuses = ['active', 'inactive', 'deprecated']
    if status and status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
        )
    
    policy_service = PolicyService()
    try:
        return await policy_service.query_policies(
            agent_id=agent_id,
            status=status,
            limit=limit,
            cursor=cursor
        )
    except ValueError as exc:  # malformed cursor
        raise HTTPException(status_code=400, detail=str(exc))


# ============================================================
# Workstream 11: Policy CRUD Operations
# LLD 11 Reference: Agent Policy CRUD Operations
# ============================================================

@router.get("/policies/{policy_id}")
async def get_policy_by_id(
    policy_id: str,
    include_content: bool = True
) -> Dict:
    """
    Get single policy with full content from S3.

    Path Parameters:
        policy_id: Policy identifier

    Query Parameters:
        include_content: Include S3 YAML content (default: true)

    Returns:
        Policy metadata and optional content from S3

    HTTP Status Codes:
        200 OK - Policy found
        404 Not Found - Policy not found

    Reference: LLD 11 Section 3.4
    """
    from app.services.policy_service import PolicyService
    from app.exceptions import NotFoundException

    try:
        policy_service = PolicyService()
        
        # Get metadata
        metadata = await policy_service.get_policy(policy_id)
        if not metadata:
            raise NotFoundException(f"Policy {policy_id} not found")
        
        # Optionally get content from S3
        content = None
        if include_content:
            content = await policy_service.get_policy_content(policy_id)
        
        return {
            "success": True,
            "policy": {
                "metadata": metadata,
                "content": content
            }
        }
    except NotFoundException as e:
        raise HTTPException(status_code=e.status_code, detail=e.to_dict())


@router.post("/policies", status_code=201)
async def create_policy(
    request: PolicyCreateRequest,
    operator_email: str = Header(None, alias="X-Operator-Email")
) -> Dict:
    """
    Create a new agent policy with hybrid storage.

    Request Body:
        PolicyCreateRequest with schema_version, agent_id, name, version,
        allowed_tools, policies array

    Headers:
        X-Operator-Email: Email of operator creating policy (optional)

    Returns:
        Created policy metadata with policy_id, version, s3_key

    HTTP Status Codes:
        201 Created - Policy created successfully
        400 Bad Request - Validation failed
        409 Conflict - Policy already exists

    Reference: LLD 11 Section 3.1
    """
    from app.services.policy_service import PolicyService
    from app.exceptions import ValidationException, ConflictException

    try:
        policy_service = PolicyService()
        return await policy_service.create_policy(
            # exclude_none: don't write optional fields the caller omitted
            # (platform, cloud_region, allowed_agents, cross_cloud_dependencies,
            # max_calls_per_minute) to S3 as explicit nulls. A null
            # max_calls_per_minute crashed the abuse detector (int > None). WS15.
            policy_data=request.dict(exclude_none=True),
            operator_email=operator_email or "unknown"
        )
    except ValidationException as e:
        raise HTTPException(status_code=e.status_code, detail=e.to_dict())
    except ConflictException as e:
        raise HTTPException(status_code=e.status_code, detail=e.to_dict())


@router.put("/policies/{policy_id}")
async def update_policy(
    policy_id: str,
    request: PolicyUpdateRequest,
    operator_email: str = Header(None, alias="X-Operator-Email")
) -> Dict:
    """
    Update existing policy (creates new S3 version).

    Path Parameters:
        policy_id: Policy identifier

    Request Body:
        PolicyUpdateRequest (same as create)

    Headers:
        X-Operator-Email: Email of operator updating policy (optional)

    Returns:
        Updated policy metadata with new version

    HTTP Status Codes:
        200 OK - Policy updated successfully
        400 Bad Request - Validation failed
        403 Forbidden - Cannot update disabled policy
        404 Not Found - Policy not found

    Reference: LLD 11 Section 3.2
    """
    from app.services.policy_service import PolicyService
    from app.exceptions import (
        ValidationException,
        NotFoundException,
        ForbiddenException
    )

    try:
        policy_service = PolicyService()
        return await policy_service.update_policy(
            policy_id=policy_id,
            # exclude_none: don't write optional fields the caller omitted
            # (platform, cloud_region, allowed_agents, cross_cloud_dependencies,
            # max_calls_per_minute) to S3 as explicit nulls. A null
            # max_calls_per_minute crashed the abuse detector (int > None). WS15.
            policy_data=request.dict(exclude_none=True),
            operator_email=operator_email or "unknown"
        )
    except ValidationException as e:
        raise HTTPException(status_code=e.status_code, detail=e.to_dict())
    except NotFoundException as e:
        raise HTTPException(status_code=e.status_code, detail=e.to_dict())
    except ForbiddenException as e:
        raise HTTPException(status_code=e.status_code, detail=e.to_dict())


@router.delete("/policies/{policy_id}")
async def delete_policy(
    policy_id: str,
    operator_email: str = Header(None, alias="X-Operator-Email")
) -> Dict:
    """
    Soft delete policy (set status=disabled).

    Path Parameters:
        policy_id: Policy identifier

    Headers:
        X-Operator-Email: Email of operator deleting policy (optional)

    Returns:
        Success response with disabled status

    HTTP Status Codes:
        200 OK - Policy disabled successfully (idempotent)
        403 Forbidden - Cannot delete system policies
        404 Not Found - Policy not found

    Note: This is a soft delete. The policy is marked as disabled but not removed
    from DynamoDB or S3, preserving the audit trail.

    Reference: LLD 11 Section 3.3
    """
    from app.services.policy_service import PolicyService
    from app.exceptions import NotFoundException, ForbiddenException

    try:
        policy_service = PolicyService()
        return await policy_service.delete_policy(
            policy_id=policy_id,
            operator_email=operator_email or "unknown"
        )
    except NotFoundException as e:
        raise HTTPException(status_code=e.status_code, detail=e.to_dict())
    except ForbiddenException as e:
        raise HTTPException(status_code=e.status_code, detail=e.to_dict())


@router.get("/sigma-rules")
async def get_sigma_rules(
    status: Optional[str] = None,
    level: Optional[str] = None,
    limit: int = 50,
    cursor: Optional[str] = None
) -> Dict:
    """
    List Sigma rules with match counts.
    
    Query Parameters:
        status: Filter by status (stable/experimental/deprecated) (optional)
        level: Filter by severity level (critical/high/medium/low) (optional)
        limit: Max results (default: 50, max: 200)
    
    Returns:
        SigmaRulesResponse with rules array, total, and has_more flag
        
    Response Fields (per rule):
        - rule_id: Sigma rule identifier
        - title: Rule title
        - description: Rule description
        - status: Rule status (stable/experimental/deprecated)
        - level: Severity level (critical/high/medium/low)
        - tags: Rule tags (e.g., attack.llm01, owasp.llm.top10.2025)
        - patterns_count: Number of detection patterns
        - match_count_24h: Matches in last 24 hours
        - match_count_7d: Matches in last 7 days
        - last_matched: Last match timestamp
        - s3_key: S3 key for full rule content
        - created_at: Creation timestamp
        - updated_at: Last update timestamp
    
    Note: Returns metadata only. Full rule content (YAML) is in S3.
    
    HTTP Status Codes:
        200 OK - Success (empty array if no rules)
        400 Bad Request - Invalid status or level
    """
    from app.services.sigma_rules_service import SigmaRulesService
    
    # Validate limit
    if limit < 1 or limit > 200:
        raise HTTPException(
            status_code=400,
            detail="Limit must be between 1 and 200"
        )
    
    # Validate status if provided
    valid_statuses = ['stable', 'experimental', 'deprecated']
    if status and status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
        )
    
    # Validate level if provided
    valid_levels = ['critical', 'high', 'medium', 'low']
    if level and level not in valid_levels:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid level. Must be one of: {', '.join(valid_levels)}"
        )
    
    sigma_rules_service = SigmaRulesService()
    try:
        return await sigma_rules_service.list_sigma_rules(
            status=status,
            level=level,
            limit=limit,
            cursor=cursor
        )
    except ValueError as exc:  # malformed cursor
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/sigma-rules/{rule_id}")
async def update_sigma_rule(rule_id: str, request: Dict) -> Dict:
    """
    Update Sigma rule (enable/disable).

    Args:
        rule_id: Rule identifier
        request: {"status": "enabled" | "disabled"}  (native "stable"/"deprecated" also accepted)

    Returns:
        Success response or error
    """
    from app.services.sigma_rules_service import SigmaRulesService, _enabled_to_ddb_status

    requested = request.get('status')
    ddb_status = _enabled_to_ddb_status(requested)
    if ddb_status is None:
        raise HTTPException(
            status_code=400,
            detail="Invalid status. Must be one of: enabled, disabled",
        )

    service = SigmaRulesService()
    success = await service.update_rule_status(rule_id, ddb_status)

    if not success:
        raise HTTPException(status_code=404, detail="Rule not found")

    # Echo the console's vocabulary back, not the stored value.
    api_status = "enabled" if ddb_status == "stable" else "disabled"
    return {"success": True, "rule_id": rule_id, "status": api_status}


# ============================================================
# Workstream 12: Conversation Timeline API
# ============================================================

@router.get("/logs/conversation/{conversation_id}")
async def get_conversation_timeline(conversation_id: str) -> Dict:
    """
    Get complete timeline of a conversation (cross-agent).

    Returns hierarchical tree of requests showing parent-child relationships.

    Path Parameters:
        conversation_id: Conversation identifier (e.g., conv-abc123)

    Returns:
        ConversationTimelineResponse with:
        - conversation_id: The conversation identifier
        - total_requests: Total number of requests in conversation
        - timeline: Hierarchical tree of requests with children
        - statistics: Summary stats (allowed/denied counts, agents involved)

    Example Response:
        {
            "conversation_id": "conv-abc123",
            "total_requests": 3,
            "timeline": [
                {
                    "request_id": "req-cqa-001",
                    "agent_id": "customer-query-agent",
                    "tool_name": "call_payment_agent",
                    "decision": "ALLOW",
                    "children": [
                        {
                            "request_id": "req-pay-001",
                            "agent_id": "payment-agent",
                            "tool_name": "process_refund",
                            "decision": "ALLOW",
                            "children": []
                        }
                    ]
                }
            ],
            "statistics": {
                "total_allowed": 3,
                "total_denied": 0,
                "agents_involved": ["customer-query-agent", "payment-agent"],
                "max_call_depth": 1
            }
        }

    HTTP Status Codes:
        200 OK - Success (empty timeline if conversation not found)
    """
    from app.services.conversation_service import ConversationService

    conversation_service = ConversationService()
    return await conversation_service.get_timeline(conversation_id)


# ============================================================
# Task 12 & 13: POST /v1/rollback - Manual Rollback
# ============================================================

@router.post("/rollback")
async def rollback_action(request: Dict) -> Dict:
    """
    Manually rollback a reversible action.
    
    Request Body:
        action_id: Unique action identifier
        action_type: Type of action (e.g., "process_refund")
        reason: Reason for rollback
        operator_id: Operator performing rollback
    
    Returns:
        Success response with rollback details or error response
    
    HTTP Status Codes:
        200 OK - Rollback successful
        404 Not Found - Action doesn't exist
        400 Bad Request - Action not reversible or already rolled back
        500 Internal Server Error - Rollback failed
    """
    from app.utils.rollback_coordinator import RollbackCoordinator
    
    # Validate request
    action_id = request.get("action_id")
    action_type = request.get("action_type")
    reason = request.get("reason")
    operator_id = request.get("operator_id")
    
    if not all([action_id, action_type, reason, operator_id]):
        raise HTTPException(
            status_code=400,
            detail="Missing required fields: action_id, action_type, reason, operator_id"
        )
    
    # Execute rollback
    rollback_coordinator = RollbackCoordinator()
    result = await rollback_coordinator.rollback_action(
        action_id=action_id,
        action_type=action_type,
        reason=reason,
        operator_id=operator_id
    )
    
    # Handle result
    if not result.get("success"):
        message = result.get("message", "Rollback failed")
        
        if "not found" in message.lower():
            raise HTTPException(status_code=404, detail=message)
        elif "already rolled back" in message.lower():
            raise HTTPException(status_code=400, detail=message)
        elif "not reversible" in message.lower():
            raise HTTPException(status_code=400, detail=message)
        else:
            raise HTTPException(status_code=500, detail=message)
    
    return result


@router.post("/rollback/conversation/{conversation_id}")
async def rollback_conversation(conversation_id: str, request: Dict) -> Dict:
    """
    Roll back ALL WRITE operations in a conversation.
    
    Fetches all audit logs for the conversation, filters for reversible
    WRITE operations, and executes rollback in LIFO order (last action first).
    
    Path Parameters:
        conversation_id: Conversation identifier (e.g., conv-abc123)
    
    Request Body:
        reason: Reason for rollback
        operator_id: Operator performing rollback (optional, default: "system")
    
    Returns:
        Rollback summary with:
        - success: Whether all rollbacks succeeded
        - conversation_id: The conversation identifier
        - rolled_back_count: Number of actions rolled back
        - failed_count: Number of failed rollbacks
        - rolled_back_actions: List of rolled back action details
        - failed_actions: List of failed action details with errors
    
    Example Response:
        {
            "success": true,
            "conversation_id": "conv-abc123",
            "rolled_back_count": 2,
            "failed_count": 0,
            "rolled_back_actions": [
                {"action_id": "act-001", "tool_name": "process_refund"},
                {"action_id": "act-002", "tool_name": "create_order"}
            ],
            "failed_actions": [],
            "reason": "Refund denied - rolling back transaction"
        }
    
    HTTP Status Codes:
        200 OK - Rollback completed (check success field for partial failures)
        400 Bad Request - Missing required fields
        500 Internal Server Error - Rollback failed completely
    """
    from app.utils.rollback_coordinator import RollbackCoordinator
    
    # Validate request
    reason = request.get("reason")
    if not reason:
        raise HTTPException(
            status_code=400,
            detail="Missing required field: reason"
        )
    
    operator_id = request.get("operator_id", "system")
    
    # Execute conversation rollback
    rollback_coordinator = RollbackCoordinator()
    result = await rollback_coordinator.rollback_conversation(
        conversation_id=conversation_id,
        reason=reason,
        operator_id=operator_id
    )
    
    return result


# ============================================================
# Task 13: POST /v1/quarantine/{session_id} - Manual Quarantine
# ============================================================

@router.post("/quarantine/{session_id}")
async def quarantine_session(session_id: str, request: Dict) -> Dict:
    """
    Manually quarantine a session (operator override).
    
    Path Parameters:
        session_id: Session identifier
    
    Request Body:
        reason: Reason for quarantine
        operator_id: Operator performing quarantine
    
    Returns:
        Success response with updated session or error response
    
    HTTP Status Codes:
        200 OK - Session quarantined
        404 Not Found - Session doesn't exist
        400 Bad Request - Session already quarantined/suspended
        500 Internal Server Error - Update failed
    """
    from app.utils.session_manager import SessionManager
    
    # Validate request
    reason = request.get("reason")
    operator_id = request.get("operator_id")
    
    if not all([reason, operator_id]):
        raise HTTPException(
            status_code=400,
            detail="Missing required fields: reason, operator_id"
        )
    
    # Execute quarantine
    session_manager = SessionManager()
    
    try:
        # Get session first to check if it exists
        session = await session_manager.get_session(session_id)
        
        if not session:
            raise HTTPException(
                status_code=404,
                detail=f"Session {session_id} not found"
            )
        
        # Idempotent: re-quarantining an already-quarantined/suspended session is a no-op success,
        # not a 400 — operators and retries should be safe to repeat (idempotency / ops review).
        current_status = session.get('quarantine_status', 'active')
        if current_status in ['quarantined', 'suspended']:
            return {
                "success": True,
                "message": f"Session {session_id} already {current_status}",
                "session_id": session_id,
                "previous_status": current_status,
                "new_status": current_status,
                "trust_score": session.get('trust_score'),
                "idempotent": True,
            }

        # Quarantine session
        updated_session = await session_manager.manual_quarantine(
            session_id=session_id,
            reason=reason,
            operator_id=operator_id
        )

        return {
            "success": True,
            "message": f"Session {session_id} quarantined successfully",
            "session_id": session_id,
            "previous_status": current_status,
            "new_status": updated_session.get('quarantine_status'),
            "trust_score": updated_session.get('trust_score')
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to quarantine session {session_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to quarantine session: {str(e)}"
        )


@router.delete("/quarantine/{session_id}")
async def release_session(session_id: str, operator_id: str = "operator") -> Dict:
    """Release a session from quarantine ('un-quarantine'; operator override). Idempotent.

    Sets quarantine_status back to 'active' and restores trust above the quarantine threshold so the
    session isn't immediately re-quarantined. Releasing an already-active session is a no-op success.
    """
    from app.utils.session_manager import SessionManager

    session_manager = SessionManager()
    try:
        session = await session_manager.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
        current_status = session.get('quarantine_status', 'active')
        if current_status == 'active':
            return {
                "success": True, "message": f"Session {session_id} already active",
                "session_id": session_id, "new_status": "active", "idempotent": True,
            }
        updated = await session_manager.manual_release(session_id, operator_id)
        return {
            "success": True, "message": f"Session {session_id} released from quarantine",
            "session_id": session_id, "previous_status": current_status,
            "new_status": updated.get('quarantine_status'), "trust_score": updated.get('trust_score'),
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Failed to release session {session_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to release session: {str(e)}")
