"""
Demo Orchestrator - Main FastAPI Application
Sentra MVP - Workstream 13, Task 1.1
"""

import os
import logging
from datetime import datetime

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pythonjsonlogger import jsonlogger

# ==================== Logging Configuration ====================

root_logger = logging.getLogger()
root_logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))
root_logger.handlers.clear()

handler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter(
    fmt='%(asctime)s %(levelname)s %(name)s %(message)s',
    json_ensure_ascii=False
)
handler.setFormatter(formatter)
root_logger.addHandler(handler)

logger = logging.getLogger(__name__)


# ==================== Environment Variables ====================

PORT = int(os.environ.get('PORT', 8080))
SERVICE_NAME = os.environ.get('SERVICE_NAME', 'demo-orchestrator')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')


# ==================== FastAPI App ====================

app = FastAPI(
    title="Sentra Demo Orchestrator",
    description="Security scenario orchestration for Sentra MVP demos",
    version="1.0.0"
)


# ==================== Health Check ====================

@app.get("/health")
@app.get("/v1/health")
async def health_check() -> JSONResponse:
    """Health check endpoint for ALB/ECS"""
    from app.utils.yaml_loader import get_scenario_ids
    
    health = {
        "status": "ok",
        "service": SERVICE_NAME,
        "timestamp": datetime.utcnow().isoformat(),
        "checks": {}
    }
    
    # Check scenarios directory
    try:
        scenario_ids = get_scenario_ids()
        health["checks"]["scenarios"] = {
            "status": "ok",
            "count": len(scenario_ids),
            "ids": scenario_ids
        }
    except Exception as e:
        health["checks"]["scenarios"] = {
            "status": "error",
            "error": str(e)
        }
    
    return JSONResponse(status_code=200, content=health)


# ==================== Startup Event ====================

@app.on_event("startup")
async def startup_event():
    """Log service startup, discover Bedrock agents, and optionally auto-start continuous scenarios"""
    from app.utils.yaml_loader import get_scenario_ids
    from app.orchestrator import get_orchestrator
    from app.clients.bedrock_client import BedrockAgentClient
    
    scenario_ids = get_scenario_ids()
    
    logger.info(
        "Demo Orchestrator started",
        extra={
            "service": SERVICE_NAME,
            "version": "1.0.0",
            "port": PORT,
            "aws_region": AWS_REGION,
            "scenarios_loaded": len(scenario_ids),
            "scenario_ids": scenario_ids
        }
    )
    
    # Discover Bedrock agents at startup (runtime discovery - no hardcoded IDs)
    bedrock_client = BedrockAgentClient(region=AWS_REGION)
    discovered_agents = await bedrock_client.discover_agents()
    logger.info(
        "Bedrock agent discovery complete",
        extra={
            "discovered_agents": list(discovered_agents.keys()),
            "agent_details": {
                name: {"agent_id": cfg.get("agent_id"), "agent_name": cfg.get("agent_name")}
                for name, cfg in discovered_agents.items()
            }
        }
    )
    
    # Auto-start continuous scenarios if enabled
    auto_start = os.environ.get("AUTO_START_CONTINUOUS", "false").lower() == "true"
    if auto_start:
        orchestrator = get_orchestrator()
        result = await orchestrator.start_all_continuous()
        logger.info(
            "Auto-started continuous scenarios",
            extra={
                "started_count": result.get("started_count", 0),
                "scenarios": [s.get("scenario_id") for s in result.get("scenarios", [])]
            }
        )


# ==================== Request Logging Middleware ====================

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all incoming requests"""
    logger.info(
        "Request received",
        extra={
            "method": request.method,
            "path": request.url.path,
            "client": request.client.host if request.client else "unknown"
        }
    )
    response = await call_next(request)
    return response


# ==================== Include API Routes ====================

from app.api.routes import router as demo_router
app.include_router(demo_router)


# ==================== Root Endpoint ====================

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": SERVICE_NAME,
        "version": "1.0.0",
        "status": "running",
        "endpoints": [
            "/health",
            "/demo/scenarios",
            "/demo/scenarios/{id}",
            "/demo/scenarios/{id}/trigger",
            "/demo/scenarios/{id}/start",
            "/demo/scenarios/{id}/pause",
            "/demo/comparison"
        ]
    }


# ==================== Main ====================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
