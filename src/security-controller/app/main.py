"""
Security Controller - FastAPI Application Entry Point

This is the core security enforcement engine that validates EVERY tool call
from EVERY agent before execution.
"""
import logging
import secrets
import time
from contextlib import asynccontextmanager
from typing import Dict

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pythonjsonlogger import jsonlogger

from app.api import routes
from app.api import tenancy_routes
from app.config import settings
from app.services.validation_service import PipelineError

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

    # WS-M M1.0 (FIX-B) — fail-secure boot backstop for the ALB-OIDC signer/issuer
    # pin. The pin defends the ADR-037 in-service control-plane auth boundary against
    # a multi-stack ES256 forgery (any in-region ALB / any Cognito pool token in acct
    # 531109575379 would otherwise verify — lld/39 §3.1). The gate existed + was
    # tested but had NO production caller, and empty pins ship in every CDK config,
    # so prod stayed inert. This wires the ONLY live caller: on a real deployment
    # (`alb_oidc_pin_enforce_at_boot` set by compute_stack.py) a genuinely-unpinned
    # prod RAISES here → the ECS task never becomes healthy → an unpinned control
    # plane never takes traffic. Inert for local dev / the hermetic test suite (flag
    # default off). Better a loud boot failure than a silent forgery window.
    settings.assert_alb_oidc_pin_ready_at_boot()
    logger.info("ALB-OIDC pin readiness verified (WS-M M1.0)")

    # Build the ValidationService once and reuse it for every request
    # (LLD 24 / WS24 M2). Per-request construction rebuilt ~10 boto3 clients and
    # discarded the Sigma rule cache, adding hundreds of ms per call. __init__ does
    # no network I/O (client objects + a local YAML read only), so it is safe here.
    from app.services import ValidationService
    app.state.validation_service = ValidationService()
    logger.info("ValidationService singleton initialized")

    # WS-L M1.4 (SEC-5) — fail fast at boot if any registered node source lacks a
    # priority / display label (or a request-phase source is missing from the
    # fallback order). An unregistered source silently ranks priority 0 and loses
    # tie-breaks → audit mis-attribution. Better a loud boot failure than silent drift.
    from app.services.scheduler import assert_registration_complete
    assert_registration_complete(app.state.validation_service)
    logger.info("Detection-depth node registration verified (WS-L SEC-5)")

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

# ============================================================
# WS-F F6.6 (lld/35 §6f items 1+2) — honest error contract.
# NO @app.exception_handler existed before this (verified). An unhandled path fell
# back to a fabricated 200-body DENY (via _create_error_response, now removed) or a
# leaked default-500 detail. These handlers surface the HONEST 5XX with a
# CUSTOMER-SAFE body (never the internal exception / stack / host / query) + a
# correlation id the customer can quote to support (the real detail is logged
# server-side). The PEP's `fail_secure` decides what to do from the status code.
# ============================================================

@app.exception_handler(PipelineError)
async def _pipeline_error_handler(request: Request, exc: PipelineError) -> JSONResponse:
    """A total inability-to-evaluate the pipeline -> honest 500 + customer-safe body."""
    return JSONResponse(
        status_code=500,
        content={
            "error": exc.public_message,
            "correlation_id": exc.correlation_id,
        },
    )


@app.exception_handler(Exception)
async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Catch-all for any path that raises an unhandled exception. Logs the internal
    detail under a correlation id server-side; returns ONLY a sanitized message + the
    id (no exception text / stack / host / query leaks across the API boundary)."""
    correlation_id = secrets.token_hex(8)
    logger.exception(
        "Unhandled exception (correlation_id=%s) on %s %s",
        correlation_id, request.method, request.url.path,
    )
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "correlation_id": correlation_id,
        },
    )


# Include API routes
app.include_router(routes.router)
# Multi-tenancy control plane (LLD-26): tenants, members, invites, credentials,
# GET /v1/me. Mounted under the same /v1 prefix.
app.include_router(tenancy_routes.router)
# WS-G G0.2 / D14 (ADR-039): PUBLIC org-first login resolver. Mounted on a
# NON-`/v1` path (`/public/resolve-org`) so it is reachable before Cognito and is
# NOT caught by the priority-5 `/v1/*` deny rule at the ALB.
app.include_router(tenancy_routes.public_router)


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
