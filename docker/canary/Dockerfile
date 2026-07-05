# WS-J canary — the 8th image (ECS synthetic monitor, Runner B). lld/38 §9, Ji.1.
#
# Increment 1: httpx + boto3 ONLY — NO Playwright/Chromium (that is Increment-2,
# the console increment §8.4). The container runs the transport-parameterized
# scenario library against the LIVE deployed API Gateway (CANARY_TARGET=live) and
# writes results via the reporting plugin.
#
# Build from Sentra root:
#   docker build -f docker/canary/Dockerfile -t sentra/canary:latest .
#
# Run (hourly, via EventBridge Scheduler → ecs:RunTask):
#   docker run -e CANARY_TARGET=live -e SENTRA_API_GW_URL=... \
#              -e CANARY_RESULTS_TABLE=sentra-canary-results sentra/canary:latest

FROM python:3.11-slim

WORKDIR /app

# Lean runtime deps only (§12 cost) — no Playwright/Chromium in Increment 1.
RUN pip install --no-cache-dir \
    "httpx>=0.27,<1" \
    "boto3>=1.34" \
    "pytest>=8" \
    "pytest-cov>=5"

# The scenario library + the controller app (some scenarios import app models /
# the redactor for the shared contract shape; the live entrypoint hits deployed
# URLs and does not stand up the app).
COPY tests/canary/ ./tests/canary/
COPY src/security-controller/app/ ./app/
COPY scripts/schemas/ ./schemas/

ENV CANARY_TARGET=live \
    PYTHONPATH=/app:/app/tests

# The overlap guard + suite + metric emission run from the entrypoint; the suite
# excludes requires_live-inverse markers so only live-safe scenarios run in prod.
CMD ["pytest", "tests/canary/", "-v", \
     "-p", "canary.reporting_plugin", \
     "-m", "not pr_gate_only"]
