"""
Customer Query Agent - Main FastAPI Application
Sentra MVP - Workstream 7
"""

import os
import logging
from datetime import datetime
from typing import Dict, Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import boto3
import requests
from pythonjsonlogger import jsonlogger

# ==================== Logging Configuration ====================

# Configure root logger to ensure all module loggers inherit settings
root_logger = logging.getLogger()
root_logger.setLevel(os.environ.get('LOG_LEVEL', 'INFO'))

# Clear any existing handlers to avoid duplicates
root_logger.handlers.clear()

# Create handler with JSON formatter
handler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter(
    fmt='%(asctime)s %(levelname)s %(name)s %(message)s',
    json_ensure_ascii=False
)
handler.setFormatter(formatter)
root_logger.addHandler(handler)

# Create module logger (will inherit root config)
logger = logging.getLogger(__name__)


# ==================== Environment Variables ====================

PORT = int(os.environ.get('PORT', 8080))
SERVICE_NAME = os.environ.get('SERVICE_NAME', 'customer-query-agent')
DEMO_CUSTOMERS_TABLE = os.environ.get('DEMO_CUSTOMERS_TABLE', 'sentra-demo-customers')
DEMO_ORDERS_TABLE = os.environ.get('DEMO_ORDERS_TABLE', 'sentra-demo-orders')
SECURITY_CONTROLLER_URL = os.environ.get('SECURITY_CONTROLLER_URL', 'http://security-controller.sentra.internal:8080')
# Default to Sonnet 3.5 v2 (optimized for agentic tasks - faster and cheaper than Opus 4)
# Sonnet 3.5 is ideal for tool selection and result summarization
# Note: NOT using Sonnet 4.5 as it has built-in guardrails that conflict with our Security Controller
# Using inference profile for v2 (required for on-demand throughput)
BEDROCK_MODEL_ID = os.environ.get('BEDROCK_MODEL_ID', 'us.anthropic.claude-3-5-sonnet-20241022-v2:0')
AWS_REGION = os.environ.get('AWS_REGION', 'us-east-1')


# ==================== FastAPI App ====================

app = FastAPI(
    title="Customer Query Agent",
    description="AI-powered customer and order query agent for Sentra MVP",
    version="1.0.0"
)


# ==================== Health Check Endpoint ====================

@app.get("/v1/health")
async def health_check() -> JSONResponse:
    """
    Health check endpoint for ALB target group

    Verifies connectivity to:
    1. DynamoDB (demo-customers, demo-orders)
    2. Security Controller (optional - won't fail if down)
    3. Bedrock (optional - won't fail if down)

    Returns:
        200 OK if service is healthy
        503 Service Unavailable if critical dependencies are down
    """
    health = {
        "status": "ok",
        "service": SERVICE_NAME,
        "timestamp": datetime.utcnow().isoformat(),
        "checks": {}
    }

    # Check 1: DynamoDB - demo-customers table
    try:
        dynamodb = boto3.client('dynamodb', region_name=AWS_REGION)
        dynamodb.describe_table(TableName=DEMO_CUSTOMERS_TABLE)
        health["checks"]["dynamodb_customers"] = "ok"
        logger.info(f"DynamoDB health check passed: {DEMO_CUSTOMERS_TABLE}")
    except Exception as e:
        health["checks"]["dynamodb_customers"] = f"error: {str(e)}"
        health["status"] = "unhealthy"
        logger.error(f"DynamoDB health check failed: {DEMO_CUSTOMERS_TABLE}", extra={"error": str(e)})

    # Check 2: DynamoDB - demo-orders table
    try:
        dynamodb.describe_table(TableName=DEMO_ORDERS_TABLE)
        health["checks"]["dynamodb_orders"] = "ok"
        logger.info(f"DynamoDB health check passed: {DEMO_ORDERS_TABLE}")
    except Exception as e:
        health["checks"]["dynamodb_orders"] = f"error: {str(e)}"
        health["status"] = "unhealthy"
        logger.error(f"DynamoDB health check failed: {DEMO_ORDERS_TABLE}", extra={"error": str(e)})

    # Check 3: Security Controller (optional - won't fail if down)
    try:
        response = requests.get(
            f"{SECURITY_CONTROLLER_URL}/v1/health",
            timeout=2.0
        )
        health["checks"]["security_controller"] = "ok" if response.status_code == 200 else "degraded"
        logger.info(f"Security Controller health check: {response.status_code}")
    except Exception as e:
        health["checks"]["security_controller"] = "unavailable"
        logger.warning("Security Controller unavailable (non-critical)", extra={"error": str(e)})
        # Don't mark as unhealthy - Security Controller may be temporarily down

    # Check 4: Bedrock (optional - won't fail if down)
    try:
        bedrock = boto3.client('bedrock', region_name=AWS_REGION)
        # Just check if we can access Bedrock service (doesn't validate model access)
        bedrock.list_foundation_models()
        health["checks"]["bedrock"] = "ok"
        logger.info("Bedrock health check passed")
    except Exception as e:
        health["checks"]["bedrock"] = "unavailable"
        logger.warning("Bedrock unavailable (non-critical)", extra={"error": str(e)})
        # Don't mark as unhealthy - Bedrock may be temporarily unavailable

    # Determine status code
    status_code = 200 if health["status"] == "ok" else 503

    return JSONResponse(status_code=status_code, content=health)


# ==================== Startup Event ====================

@app.on_event("startup")
async def startup_event():
    """Log service startup"""
    logger.info(
        "Customer Query Agent started",
        extra={
            "service": SERVICE_NAME,
            "version": "1.0.0",
            "port": PORT,
            "aws_region": AWS_REGION,
            "bedrock_model": BEDROCK_MODEL_ID,
            "customers_table": DEMO_CUSTOMERS_TABLE,
            "orders_table": DEMO_ORDERS_TABLE,
            "security_controller": SECURITY_CONTROLLER_URL
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
    logger.info(
        "Request completed",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code
        }
    )
    return response


# ==================== Include API Routes ====================

from app.api.routes import router as api_router
app.include_router(api_router)


# ==================== Root Endpoint ====================

@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "service": SERVICE_NAME,
        "version": "1.0.0",
        "status": "running",
        "endpoints": [
            "/v1/health",  # Health check for ALB
            "/v1/agents/customer-query/query",  # Claude-based query endpoint
            "/v1/agents/customer-query/action",  # Claude-based action endpoint
            "/v1/execute"  # Post-validation direct execution
        ]
    }


# ==================== Main ====================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
