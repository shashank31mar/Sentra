# WS-J canary — the 8th image (ECS synthetic monitor, Runner B). lld/38 §9, Ji.1.
#
# Increment 2 (J8, §5C): httpx + boto3 + **Playwright/headless Chromium**. The console
# UI sweep + the real Cognito hosted-UI login (D-4) run in the SAME hourly container as
# the httpx black-box scenarios. The console/oidc-authed modules are requires_live AND
# import-guard playwright, so a browserless run (a lean edition / the PR gate) SKIP-
# collects them rather than erroring collection (the lean-alarm-blanking invariant).
# The container runs the transport-parameterized scenario library against the LIVE
# deployed API Gateway + console (CANARY_TARGET=live) and writes results via the plugin.
#
# Build from Sentra root:
#   docker build -f docker/canary/Dockerfile -t sentra/canary:latest .
#
# Run (hourly, via EventBridge Scheduler → ecs:RunTask):
#   docker run -e CANARY_TARGET=live -e SENTRA_API_GW_URL=... -e SENTRA_CONSOLE_URL=... \
#              -e CANARY_RESULTS_TABLE=sentra-canary-results sentra/canary:latest

FROM python:3.11-slim

WORKDIR /app

# Runtime deps. J8 adds Playwright; httpx/boto3 remain for the pure-httpx scenario lane.
# Chromium ~doubles image size vs Increment-1 (§12 cost, accepted for the console lane).
RUN pip install --no-cache-dir \
    "httpx>=0.27,<1" \
    "boto3>=1.34" \
    "pytest>=8" \
    "pytest-cov>=5" \
    "playwright>=1.44,<2"

# Install headless Chromium + its OS deps. --with-deps runs apt-get for the shared libs
# (fonts, nss, etc.) headless Chromium needs on slim. Under Fargate there are no user
# namespaces, so scenarios launch Chromium with --no-sandbox --headless=new (see
# conftest._ConsoleSession). SEC-10: NO trace/screenshot is ever captured (prod cookies).
RUN playwright install --with-deps chromium

# The scenario library + the controller app. In the LIVE container only the two
# black-box httpx scenario modules (test_all_routes.py + test_metrics_live.py) are
# actually collected — conftest.py's CANARY_TARGET-driven collect_ignore excludes
# every app-standing-up / meta / harness-unit module, so their module-level
# app.*/aegion_guard/fastapi/pydantic imports never run (the lean image has NO
# fastapi/pydantic/SDK, so collecting them would ModuleNotFoundError at collection
# and blank out every alarm's metric). The app/ tree is COPIED anyway for the
# inprocess/build-time story + so a future non-lean edition can widen the live set;
# the live entrypoint hits deployed URLs and does not stand up the app.
COPY tests/canary/ ./tests/canary/
# The canary conftest EXTENDS the integration conftest (J1.1 hard rule — re-exports its
# service_urls/aws_config fixtures by file path, tests/canary/conftest.py:28). Without
# tests/integration/conftest.py in the image, canary conftest import fails at collection
# → FileNotFoundError → the whole suite errors (exit 4, zero checks). It is stdlib+pytest
# only, so it stays lean.
COPY tests/integration/ ./tests/integration/
COPY src/security-controller/app/ ./app/
COPY scripts/schemas/ ./schemas/

ENV CANARY_TARGET=live \
    PYTHONPATH=/app:/app/tests \
    PYTHONUNBUFFERED=1
    # PYTHONUNBUFFERED: without it the pytest/suite stdout is block-buffered and a
    # short-lived Fargate task can exit before the awslogs driver flushes, leaving the
    # CloudWatch stream EMPTY — a live monitor with no readable run output. Force line-
    # buffered so every run's pass/fail summary reaches /ecs/sentra/canary.

# The overlap guard + suite + CloudWatch metric emission all run from the entrypoint
# wrapper (canary.entrypoint.main) — a BARE ``pytest`` here never calls the overlap
# guard, never emits ChecksPassed/ChecksFailed/InfraErrors/ChecksExpected/
# ProductFivexxFail, so every canary_stack alarm would watch a metric that is never
# produced (the dead-seam bug). main() runs guard_at_most_one → the suite (with the
# reporting plugin) → emit_run_metrics, and exits non-zero on any FAIL.
CMD ["python", "-m", "canary.entrypoint"]
