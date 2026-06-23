"""
Security Controller - FastAPI Application Entry Point

This is the core security enforcement engine that validates EVERY tool call
from EVERY agent before execution.
"""
import logging
import time
from contextlib import asynccontextmanager
from typing import Dict

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pythonjsonlogger import jsonlogger

from app.api import routes
from app.api import tenancy_routes
from app.config import settings

# Configure structured JSON logging
logger = logging.getLogger()
logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter(
    fmt="%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S"
)
logHandler.setFormatter(formatter)
logger.addHandler(logHandler)
logger.setLevel(getattr(logging, settings.log_level))


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    Handles startup and shutdown events.
    """
    # Startup
    logger.info("Security Controller starting up", extra={
        "environment": settings.environment,
        "port": settings.port,
        "aws_region": settings.aws_region
    })

    # Build the ValidationService once and reuse it for every request
    # (LLD 24 / WS24 M2). Per-request construction rebuilt ~10 boto3 clients and
    # discarded the Sigma rule cache, adding hundreds of ms per call. __init__ does
    # no network I/O (client objects + a local YAML read only), so it is safe here.
    from app.services import ValidationService
    app.state.validation_service = ValidationService()
    logger.info("ValidationService singleton initialized")

    yield
    
    # Shutdown
    logger.info("Security Controller shutting down")


# Initialize FastAPI application
app = FastAPI(
    title="Sentra Security Controller",
    description="Core security enforcement engine for AI agent tool call validation",
    version="1.0.0",
    lifespan=lifespan
)

# Configure CORS for API Gateway integration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to API Gateway domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(routes.router)
# Multi-tenancy control plane (LLD-26): tenants, members, invites, credentials,
# GET /v1/me. Mounted under the same /v1 prefix.
app.include_router(tenancy_routes.router)


@app.get("/")
async def root() -> Dict[str, str]:
    """Root endpoint - redirect to health check"""
    return {
        "service": "Sentra Security Controller",
        "version": "1.0.0",
        "status": "operational",
        "health_check": "/health"
    }


# Export for testing
__all__ = ["app"]
