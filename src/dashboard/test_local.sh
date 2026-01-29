#!/bin/bash
# Quick test script for local dashboard development

set -e

echo "🚀 Sentra Dashboard - Local Test Script"
echo "========================================"
echo ""

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo "❌ Docker is not running. Please start Docker and try again."
    exit 1
fi

echo "✅ Docker is running"
echo ""

# Build the image
echo "📦 Building Docker image..."
docker build -f ../../docker/dashboard/Dockerfile -t sentra/dashboard:local ../.. > /tmp/dashboard_build.log 2>&1

if [ $? -eq 0 ]; then
    echo "✅ Docker build successful"
else
    echo "❌ Docker build failed. Check /tmp/dashboard_build.log for details"
    exit 1
fi

echo ""

# Stop any existing containers
echo "🧹 Cleaning up existing containers..."
docker stop $(docker ps -q --filter "ancestor=sentra/dashboard:local") 2>/dev/null || true
docker rm $(docker ps -aq --filter "ancestor=sentra/dashboard:local") 2>/dev/null || true

echo ""

# Run the container
echo "🚀 Starting dashboard container..."
docker run -d -p 8501:8501 --name sentra-dashboard-test sentra/dashboard:local > /dev/null

echo "⏳ Waiting for dashboard to start (10 seconds)..."
sleep 10

# Check health
echo ""
echo "🏥 Checking health endpoint..."
HEALTH_CHECK=$(curl -s http://localhost:8501/_stcore/health 2>&1)

if [ "$HEALTH_CHECK" = "ok" ]; then
    echo "✅ Health check passed"
else
    echo "⚠️  Health check returned: $HEALTH_CHECK"
fi

echo ""
echo "✅ Dashboard is running!"
echo ""
echo "📊 Access the dashboard at: http://localhost:8501"
echo ""
echo "To view logs:"
echo "  docker logs -f sentra-dashboard-test"
echo ""
echo "To stop the dashboard:"
echo "  docker stop sentra-dashboard-test"
echo "  docker rm sentra-dashboard-test"
echo ""
