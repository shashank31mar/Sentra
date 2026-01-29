# Payment Agent - Dockerfile
# Builds the Payment Agent service for ECS deployment
#
# Build from Sentra root:
#   docker build -f docker/payment-agent/Dockerfile -t sentra/payment-agent:latest .
#
# Run:
#   docker run -p 8080:8080 sentra/payment-agent:latest

FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better layer caching
COPY src/payment-agent/requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/payment-agent/app/ ./app/

# Expose port (must match ECS task definition)
EXPOSE 8080

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8080/v1/health || exit 1

# Run application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
