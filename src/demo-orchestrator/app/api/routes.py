"""
Demo Orchestrator API Routes
Sentra MVP - Workstream 13, Tasks 1.4 & 2.3 & 2.4
"""

import logging
import time
from typing import Optional, Dict
from fastapi import APIRouter, HTTPException

from app.utils.yaml_loader import load_all_scenarios, load_scenario
from app.orchestrator import get_orchestrator
from app.clients.security_client import SecurityControllerClient
from app.clients.cloudwatch_client import CloudWatchLogsClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/demo", tags=["demo"])

# Agent registry cache
_agent_registry_cache: Dict[str, dict] = {}
_security_client: SecurityControllerClient = None

# Comparison cache (60 second TTL)
_comparison_cache: Dict[str, dict] = {}
_comparison_cache_time: Dict[str, float] = {}
COMPARISON_CACHE_TTL = 60  # seconds


def _get_security_client() -> SecurityControllerClient:
    """Get or create security controller client."""
    global _security_client
    if _security_client is None:
        _security_client = SecurityControllerClient()
    return _security_client


def _get_agent_registry() -> Dict[str, dict]:
    """
    Load agent registry from Security Controller API (cached)
    
    Returns:
        Dict mapping agent_id to agent metadata including platform and security_type
    """
    global _agent_registry_cache
    
    if _agent_registry_cache:
        return _agent_registry_cache
    
    try:
        client = _get_security_client()
        # Use enrich=false for fast response (only need basic metadata)
        response = client.get_agents(enrich=False)
        agents = response.get('agents', [])
        
        _agent_registry_cache = {
            agent['agent_id']: {
                'platform': agent.get('platform', 'sentra'),
                'security_type': agent.get('security_type', 'secured'),
                'visibility': agent.get('visibility', 'external'),
                'name': agent.get('name', agent['agent_id']),
                'type': agent.get('type', 'unknown')
            }
            for agent in agents
        }
        
        logger.info(f"Loaded {len(_agent_registry_cache)} agents from Security Controller")
        return _agent_registry_cache
        
    except Exception as e:
        logger.warning(f"Could not load agent registry: {e}")
        return {}


def _get_agent_category(agent_id: str) -> str:
    """
    Get category key for agent: {platform}_{security_type}
    e.g., "sentra_secured", "bedrock_unsecured"
    """
    registry = _get_agent_registry()
    
    if agent_id in registry:
        agent = registry[agent_id]
        return f"{agent['platform']}_{agent['security_type']}"
    
    # Default for unknown agents
    return "sentra_secured"


@router.get("/scenarios")
async def list_scenarios():
    """
    List all available scenarios with metadata and status
    
    Returns:
        List of scenarios with id, name, mode, interval, prompt count, status
    """
    scenarios = load_all_scenarios()
    orchestrator = get_orchestrator()
    
    return {
        "scenarios": [
            {
                "scenario_id": s.scenario_id,
                "name": s.name,
                "description": s.description,
                "mode": s.mode,
                "interval": s.interval,
                "prompt_count": len(s.prompts),
                "agents": {
                    "self_hosted": s.agents.self_hosted,
                    "bedrock": s.agents.bedrock
                },
                "status": orchestrator.get_status(s.scenario_id)
            }
            for s in scenarios
        ],
        "total": len(scenarios),
        "running_count": len(orchestrator.running_scenarios)
    }


@router.get("/scenarios/{scenario_id}")
async def get_scenario_details(scenario_id: str):
    """
    Get detailed scenario configuration including prompts
    
    Args:
        scenario_id: Scenario identifier
    
    Returns:
        Full scenario configuration with status
    """
    try:
        scenario = load_scenario(scenario_id)
        orchestrator = get_orchestrator()
        
        return {
            **scenario.model_dump(),
            "status": orchestrator.get_status(scenario_id)
        }
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"Scenario '{scenario_id}' not found"
        )
    except Exception as e:
        logger.error(f"Error loading scenario {scenario_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Error loading scenario: {str(e)}"
        )


@router.post("/scenarios/{scenario_id}/trigger")
async def trigger_scenario(scenario_id: str):
    """
    Execute scenario once immediately
    
    Args:
        scenario_id: Scenario identifier
    
    Returns:
        Execution results with run_id and summary
    """
    orchestrator = get_orchestrator()
    
    try:
        result = await orchestrator.trigger_once(scenario_id)
        
        if result.get("status") == "error":
            raise HTTPException(
                status_code=404 if "not found" in result.get("message", "") else 500,
                detail=result.get("message")
            )
        
        # Calculate summary stats
        all_results = (
            result.get("results", {}).get("self_hosted", []) +
            result.get("results", {}).get("bedrock_secured", []) +
            result.get("results", {}).get("bedrock_unsecured", [])
        )
        
        total = len(all_results)
        matches = sum(1 for r in all_results if r.get("match", False))
        
        return {
            "status": "completed",
            "scenario_id": scenario_id,
            "run_id": result.get("run_id"),
            "timestamp": result.get("timestamp"),
            "duration_ms": result.get("duration_ms"),
            "summary": {
                "total_prompts": total,
                "expected_matches": matches,
                "match_rate": round(matches / total * 100, 1) if total > 0 else 0
            },
            "results": result.get("results", {})
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error executing scenario {scenario_id}: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Execution error: {str(e)}"
        )


@router.post("/scenarios/{scenario_id}/start")
async def start_continuous(scenario_id: str):
    """
    Start continuous execution for a scenario
    
    Args:
        scenario_id: Scenario identifier
    
    Returns:
        Status with interval info
    """
    orchestrator = get_orchestrator()
    result = await orchestrator.start_continuous(scenario_id)
    
    if result.get("status") == "error":
        raise HTTPException(
            status_code=404 if "not found" in result.get("message", "") else 400,
            detail=result.get("message")
        )
    
    return result


@router.post("/scenarios/{scenario_id}/pause")
async def pause_continuous(scenario_id: str):
    """
    Pause continuous execution for a scenario
    
    Args:
        scenario_id: Scenario identifier
    
    Returns:
        Status confirmation
    """
    orchestrator = get_orchestrator()
    result = await orchestrator.pause_continuous(scenario_id)
    return result


@router.post("/scenarios/pause-all")
async def pause_all_scenarios():
    """Pause all running scenarios"""
    orchestrator = get_orchestrator()
    result = await orchestrator.pause_all()
    return result


@router.post("/scenarios/start-all")
async def start_all_continuous():
    """Start all continuous-mode scenarios"""
    orchestrator = get_orchestrator()
    result = await orchestrator.start_all_continuous()
    return result


@router.get("/status")
async def get_orchestrator_status():
    """Get overall orchestrator status"""
    orchestrator = get_orchestrator()
    return orchestrator.get_status()


@router.get("/agents")
async def list_agents():
    """
    List all registered external agents with their platform and security type
    
    Returns:
        List of external agents (visibility != 'internal') with metadata
    """
    registry = _get_agent_registry()
    
    # Filter to external agents only
    external_agents = [
        {
            "agent_id": agent_id,
            "name": metadata.get("name", agent_id),
            "platform": metadata.get("platform", "sentra"),
            "security_type": metadata.get("security_type", "secured"),
            "type": metadata.get("type", "unknown")
        }
        for agent_id, metadata in registry.items()
        if metadata.get("visibility", "external") != "internal"
    ]
    
    return {
        "agents": external_agents,
        "total": len(external_agents)
    }


@router.post("/agents/refresh")
async def refresh_agent_registry():
    """
    Refresh agent registry cache from Security Controller
    
    Call this after updating agent metadata to reload the cache.
    """
    global _agent_registry_cache
    _agent_registry_cache = {}
    
    registry = _get_agent_registry()
    
    return {
        "status": "refreshed",
        "agents_loaded": len(registry)
    }


@router.post("/comparison/refresh")
async def refresh_comparison_cache():
    """
    Clear comparison cache to force fresh data on next request.
    
    Useful after running scenarios to see updated metrics immediately.
    """
    global _comparison_cache, _comparison_cache_time
    _comparison_cache = {}
    _comparison_cache_time = {}
    
    return {
        "status": "cache_cleared",
        "message": "Comparison cache cleared. Next request will fetch fresh data."
    }


@router.get("/comparison")
async def get_comparison_metrics(
    scenario_id: Optional[str] = None,
    hours: int = 24,
    include_prompts: bool = False
):
    """
    Get comparison metrics grouped by platform_securityType (cached for 60s)

    Returns metrics grouped dynamically based on agent registry:
    - sentra_secured
    - bedrock_secured
    - bedrock_unsecured

    Args:
        scenario_id: Filter by scenario (optional)
        hours: Time range in hours (default 24)
        include_prompts: Include per-prompt breakdown (default False)

    Returns:
        Aggregated metrics by agent category showing allow/deny rates.
        When include_prompts=True, also includes per-agent and per-prompt details.
    """
    # Check cache first
    cache_key = f"{scenario_id or 'all'}_{hours}_{include_prompts}"
    cached_time = _comparison_cache_time.get(cache_key, 0)
    
    if cache_key in _comparison_cache and (time.time() - cached_time) < COMPARISON_CACHE_TTL:
        logger.debug(f"Returning cached comparison for {cache_key}")
        return _comparison_cache[cache_key]
    
    # Cache miss - fetch fresh data
    logger.info(f"Fetching fresh comparison data for {cache_key}")
    security_client = SecurityControllerClient()
    cloudwatch_client = CloudWatchLogsClient()

    # Fetch logs in parallel: Security Controller AND CloudWatch
    import asyncio
    try:
        # Run both queries in parallel
        security_logs_task = security_client.query_logs(scenario_id=scenario_id, hours=hours)
        cloudwatch_logs_task = cloudwatch_client.query_demo_logs(
            scenario_id=scenario_id,
            hours=hours,
            agent_type="bedrock_unsecured"
        )

        security_logs, cw_logs = await asyncio.gather(
            security_logs_task,
            cloudwatch_logs_task,
            return_exceptions=True
        )

        # Handle results
        logs = security_logs if not isinstance(security_logs, Exception) else []
        if isinstance(security_logs, Exception):
            logger.warning(f"Security Controller query failed: {security_logs}")

        if not isinstance(cw_logs, Exception):
            logs.extend(cw_logs)
            logger.info(f"Added {len(cw_logs)} bedrock_unsecured logs from CloudWatch")
        else:
            logger.warning(f"CloudWatch query failed: {cw_logs}")

    except Exception as e:
        logger.error(f"Error fetching comparison data: {e}")
        logs = []
    
    # Group logs by category (platform_securityType)
    logs_by_category: Dict[str, list] = {}
    
    for log in logs:
        agent_id = log.get("agent_id", "")
        category = _get_agent_category(agent_id)
        
        if category not in logs_by_category:
            logs_by_category[category] = []
        logs_by_category[category].append(log)
    
    # Build comparison dict with aggregated metrics
    if not include_prompts:
        # EXISTING BEHAVIOR - Aggregated only
        comparison = {
            category: _aggregate_decisions(category_logs)
            for category, category_logs in logs_by_category.items()
        }

        # Ensure expected categories exist (even if empty)
        for expected in ["sentra_secured", "bedrock_secured", "bedrock_unsecured"]:
            if expected not in comparison:
                comparison[expected] = _aggregate_decisions([])

        # Alias sentra_secured as self_hosted for UI compatibility
        if "sentra_secured" in comparison:
            comparison["self_hosted"] = comparison["sentra_secured"]
    else:
        # NEW BEHAVIOR - Include per-prompt breakdown
        comparison = _build_detailed_comparison(logs, logs_by_category)
    
    result = {
        "time_range_hours": hours,
        "scenario_id": scenario_id,
        "total_logs": len(logs),
        "comparison": comparison,
        "cached": False
    }
    
    # Update cache
    _comparison_cache[cache_key] = {**result, "cached": True}
    _comparison_cache_time[cache_key] = time.time()
    
    return result


def _aggregate_decisions(logs: list) -> dict:
    """Calculate decision percentages for a set of logs"""
    total = len(logs)
    if total == 0:
        return {
            "total": 0,
            "allowed": 0,
            "denied": 0,
            "allowed_pct": 0.0,
            "denied_pct": 0.0
        }

    allowed = len([log for log in logs if log.get("decision") == "ALLOW"])
    denied = len([log for log in logs if log.get("decision") == "DENY"])
    other = total - allowed - denied

    return {
        "total": total,
        "allowed": allowed,
        "denied": denied,
        "other": other,
        "allowed_pct": round(allowed / total * 100, 1),
        "denied_pct": round(denied / total * 100, 1)
    }


def _build_detailed_comparison(logs: list, logs_by_category: Dict[str, list]) -> dict:
    """
    Build detailed comparison with per-agent and per-prompt breakdown.

    Args:
        logs: All logs
        logs_by_category: Logs grouped by category (platform_securityType)

    Returns:
        Dict with category-level aggregates and per-agent prompt details
    """
    registry = _get_agent_registry()
    comparison = {}

    # Process each category
    for category, category_logs in logs_by_category.items():
        # Group logs by agent_id within this category
        logs_by_agent: Dict[str, list] = {}

        for log in category_logs:
            agent_id = log.get("agent_id", "unknown")
            if agent_id not in logs_by_agent:
                logs_by_agent[agent_id] = []
            logs_by_agent[agent_id].append(log)

        # Build agents dict with per-prompt details
        agents_dict = {}
        for agent_id, agent_logs in logs_by_agent.items():
            agent_metadata = registry.get(agent_id, {})

            # Build prompts array
            prompts_array = []
            for log in agent_logs:
                prompts_array.append({
                    "prompt_id": log.get("prompt_id", ""),
                    "prompt_text": log.get("prompt_text", ""),
                    "expected_decision": log.get("expected_decision", ""),
                    "actual_decision": log.get("decision", "UNKNOWN"),
                    "match": log.get("decision") == log.get("expected_decision"),
                    "expected_threat": log.get("expected_threat", ""),
                    "output_text": log.get("output_text", "")[:200],  # Truncate for response size
                    "reason": log.get("reason", ""),
                    "timestamp": log.get("timestamp", "")
                })

            # Calculate agent-level stats
            total = len(agent_logs)
            allowed = len([l for l in agent_logs if l.get("decision") == "ALLOW"])
            denied = len([l for l in agent_logs if l.get("decision") == "DENY"])

            agents_dict[agent_id] = {
                "platform": agent_metadata.get("platform", "sentra"),
                "security_type": agent_metadata.get("security_type", "secured"),
                "total": total,
                "allowed": allowed,
                "denied": denied,
                "allowed_pct": round(allowed / total * 100, 1) if total > 0 else 0.0,
                "denied_pct": round(denied / total * 100, 1) if total > 0 else 0.0,
                "prompts": prompts_array
            }

        # Calculate category-level aggregated stats
        category_stats = _aggregate_decisions(category_logs)
        category_stats["agents"] = agents_dict

        comparison[category] = category_stats

    # Ensure expected categories exist (even if empty)
    for expected in ["sentra_secured", "bedrock_secured", "bedrock_unsecured"]:
        if expected not in comparison:
            comparison[expected] = {
                **_aggregate_decisions([]),
                "agents": {}
            }

    # Alias sentra_secured as self_hosted for UI compatibility
    if "sentra_secured" in comparison:
        comparison["self_hosted"] = comparison["sentra_secured"]

    return comparison
