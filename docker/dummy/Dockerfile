# Dummy service for placeholder deployment
# This is a minimal FastAPI service that responds to health checks
FROM python:3.11-slim

WORKDIR /app

# Install minimal dependencies
RUN pip install --no-cache-dir fastapi==0.109.0 uvicorn[standard]==0.27.0

# Create a simple FastAPI app
RUN echo 'from fastapi import FastAPI\n\
app = FastAPI()\n\
\n\
@app.get("/v1/health")\n\
async def health():\n\
    return {"status": "healthy", "service": "dummy"}\n\
\n\
@app.get("/health")\n\
async def health_legacy():\n\
    return {"status": "healthy", "service": "dummy"}' > main.py

# Expose port
EXPOSE 8080

# Run application
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
