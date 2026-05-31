FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (curl for health checks)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first (for Docker layer caching)
COPY src/dashboard/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/dashboard/ .

# Copy common modules (for LLM response generator, etc.)
COPY src/common/ ./common/

# Workstream 15 M4: dashboard imports the cross-cloud `connectors` package
# (BedrockConnector, AzureConnector, ABCs) via agent_caller_factory. The
# package lives outside src/dashboard/, so it must be copied in explicitly.
COPY src/connectors/ ./connectors/

# Workstream 15 M4: cross-cloud agent inventory reads platform from this YAML.
# agent_caller_factory locates it via Path(__file__).resolve().parents[N] /
# "config" / "agent_policies.yaml"; ship the config so the factory works inside
# the container.
COPY config/ ./config/

# Workstream 15 M4: AzureConnector loads its agent spec (system prompt, tool
# schemas, Azure OpenAI deployment ref) from this JSON at runtime. Ship it
# under the same path the connector walks ancestors to find.
COPY infrastructure/azure/agent-spec/ ./infrastructure/azure/agent-spec/

# Workstream 15 M5: ship the control-plane CLIs so the cross-cloud demo
# runner can apply policy updates in-process for S2 (and any future scenario
# that mutates control-plane state during a demo).
COPY scripts/apply_policy.py ./scripts/apply_policy.py

# Workstream 15 M5: ship the cross-cloud scenario YAMLs so the dashboard's
# demo cards can resolve them at /app/cross_cloud_scenarios/. The orchestrator
# service ships its own copy via docker/demo-orchestrator/Dockerfile — this is
# the dashboard-side copy. We DON'T mount the orchestrator's `app/` here
# because it would collide with the dashboard's own /app working dir; the
# dashboard defines a focused local `scenario_models.py` that mirrors the
# orchestrator's cross-cloud schema (single canonical YAML, two thin parsers).
COPY src/demo-orchestrator/scenarios/ ./cross_cloud_scenarios/

# Expose Streamlit port (8501 is Streamlit default)
EXPOSE 8501

# Health check - Streamlit health endpoint
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:8501/_stcore/health || exit 1

# Run Streamlit on default port 8501
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
