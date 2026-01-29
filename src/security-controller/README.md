# Sentra Security Controller

Core security enforcement engine that validates EVERY tool call from EVERY agent before execution.

## Features

- **5-Step Validation Pipeline**: Trust Score Check → Policy Engine → Sigma Rule Engine → Context Validator → Abuse Detector
- **Trust Scoring**: Asymmetric recovery algorithm (0-100 scale)
- **Manual Quarantine**: Operator override for suspicious sessions
- **Manual Rollback**: Reverse refund actions
- **Fail-Secure**: Deny by default when dependencies fail
- **Target Latency**: < 100ms p95

## Project Structure

```
Sentra/src/security-controller/
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI app entry point
│   ├── config.py                   # Configuration management
│   ├── api/
│   │   ├── __init__.py
│   │   ├── routes.py               # REST API endpoints
│   │   └── models.py               # Pydantic schemas (TODO)
│   ├── validators/
│   │   ├── trust_checker.py        # Trust score validation (TODO)
│   │   ├── policy_engine.py        # Policy evaluation (TODO)
│   │   ├── sigma_engine.py         # Threat detection (TODO)
│   │   ├── context_validator.py    # Tool sequence validation (TODO)
│   │   └── abuse_detector.py       # Rate limiting (TODO)
│   └── utils/
│       ├── session_manager.py      # DynamoDB session CRUD (TODO)
│       ├── rollback_coordinator.py # Manual rollback logic (TODO)
│       ├── audit_logger.py         # CloudWatch logging (TODO)
│       └── metrics_publisher.py    # CloudWatch metrics (TODO)
├── tests/
│   ├── __init__.py
│   └── test_health.py              # Health endpoint tests
├── requirements.txt
├── Dockerfile                      # Docker image (TODO)
└── README.md
```

## Installation

### Local Development

```bash
# Create virtual environment
cd Sentra/src/security-controller
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Set environment variables (copy .env.example to .env and edit)
cp .env.example .env

# Run application
uvicorn app.main:app --reload --port 8080
```

### Docker

```bash
# Build image
docker build -t sentra/security-controller:latest .

# Run container
docker run -p 8080:8080 \
  -e AWS_REGION=us-east-1 \
  -e AWS_ACCESS_KEY_ID=$AWS_ACCESS_KEY_ID \
  -e AWS_SECRET_ACCESS_KEY=$AWS_SECRET_ACCESS_KEY \
  sentra/security-controller:latest
```

## Configuration

All configuration is loaded from environment variables. See `.env.example` for available options.

Key settings:
- `AWS_REGION`: AWS region (default: us-east-1)
- `DYNAMODB_SESSION_TABLE`: Session context table name
- `DYNAMODB_POLICIES_TABLE`: Agent policies table name
- `S3_BUCKET`: Artifacts bucket for Sigma rules
- `LOG_LEVEL`: Logging level (INFO, DEBUG, WARNING, ERROR)

## API Endpoints

### GET /v1/health

Health check with dependency verification.

**Response (200 OK)**:
```json
{
  "status": "healthy",
  "timestamp": "2025-01-16T10:00:00Z",
  "version": "1.0.0",
  "dependencies": {
    "dynamodb_session_table": "healthy",
    "dynamodb_policies_table": "healthy",
    "s3": "healthy",
    "cloudwatch": "healthy"
  },
  "uptime_seconds": 3600
}
```

**Response (503 Service Unavailable)**:
```json
{
  "status": "unhealthy",
  "dependencies": {
    "dynamodb_session_table": "unhealthy",
    ...
  },
  "errors": [
    "DynamoDB connection timeout"
  ]
}
```

### POST /v1/validate (Placeholder)

Tool call validation endpoint. Currently returns placeholder response.

Will be fully implemented in Task 3.

## Testing

```bash
# Install test dependencies
pip install pytest pytest-asyncio httpx

# Run tests
pytest tests/ -v

# Run with coverage
pytest tests/ -v --cov=app --cov-report=html
```

## Deployment

See [Workstream 3 Tasks](../../tasks/workstream-3-security-controller.md) for deployment instructions.

## Development Status

- [x] Task 1: FastAPI project setup and health endpoint
- [ ] Task 1.5: Configuration seeding script
- [ ] Task 2: Session manager with atomic updates
- [ ] Task 3: POST /v1/validate endpoint (basic structure)
- [ ] Task 4-8: Validation pipeline implementation
- [ ] Task 9: Audit logging and metrics
- [ ] Task 10-11: Query APIs
- [ ] Task 12-13: Rollback and quarantine
- [ ] Task 14-15: CloudWatch alarms and testing
- [ ] Task 16: Documentation

## References

- [LLD 03: Security Controller](../../lld/03-security-controller.md)
- [Workstream 3 Tasks](../../tasks/workstream-3-security-controller.md)
- [Best Practices](../../best-practices.md)
