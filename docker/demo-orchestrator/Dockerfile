# Demo Orchestrator - Dockerfile
# Builds the Demo Orchestrator service for ECS deployment
#
# Build from Sentra root:
#   docker build -f docker/demo-orchestrator/Dockerfile -t sentra/demo-orchestrator:latest .
#
# Run:
#   docker run -p 8080:8080 sentra/demo-orchestrator:latest

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better layer caching
COPY src/demo-orchestrator/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/demo-orchestrator/app/ ./app/
COPY src/demo-orchestrator/scenarios/ ./scenarios/

# Set environment variables
ENV PORT=8080
ENV SCENARIOS_DIR=/app/scenarios

# Expose port (must match ECS task definition)
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Run application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
