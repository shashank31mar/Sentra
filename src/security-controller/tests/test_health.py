"""
Unit tests for health check endpoint
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from app.main import app


@pytest.fixture
def client():
    """Create test client"""
    return TestClient(app)


def test_root_endpoint(client):
    """Test root endpoint returns service info"""
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "Sentra Security Controller"
    assert data["version"] == "1.0.0"
    assert data["status"] == "operational"


@patch('app.services.health_service.boto3.client')
def test_health_check_all_healthy(mock_boto3_client, client):
    """Test health check when all dependencies are healthy"""
    # Mock DynamoDB client
    mock_dynamodb = MagicMock()
    mock_dynamodb.describe_table.return_value = {"Table": {"TableName": "test"}}
    
    # Mock S3 client
    mock_s3 = MagicMock()
    mock_s3.head_bucket.return_value = {}
    
    # Mock CloudWatch Logs client
    mock_logs = MagicMock()
    mock_logs.describe_log_groups.return_value = {"logGroups": []}
    
    # Configure boto3.client to return appropriate mocks
    def client_side_effect(service, **kwargs):
        if service == 'dynamodb':
            return mock_dynamodb
        elif service == 's3':
            return mock_s3
        elif service == 'logs':
            return mock_logs
    
    mock_boto3_client.side_effect = client_side_effect
    
    response = client.get("/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["dependencies"]["dynamodb_session_table"] == "healthy"
    assert data["dependencies"]["dynamodb_policies_metadata_table"] == "healthy"
    assert data["dependencies"]["s3"] == "healthy"
    assert data["dependencies"]["cloudwatch"] == "healthy"
    assert "uptime_seconds" in data


@patch('app.services.health_service.boto3.client')
def test_health_check_dynamodb_unhealthy(mock_boto3_client, client):
    """Test health check when DynamoDB is unavailable"""
    # Mock DynamoDB client to raise exception
    mock_dynamodb = MagicMock()
    mock_dynamodb.describe_table.side_effect = Exception("Connection timeout")
    
    # Mock S3 and CloudWatch as healthy
    mock_s3 = MagicMock()
    mock_s3.head_bucket.return_value = {}
    
    mock_logs = MagicMock()
    mock_logs.describe_log_groups.return_value = {"logGroups": []}
    
    def client_side_effect(service, **kwargs):
        if service == 'dynamodb':
            return mock_dynamodb
        elif service == 's3':
            return mock_s3
        elif service == 'logs':
            return mock_logs
    
    mock_boto3_client.side_effect = client_side_effect
    
    response = client.get("/v1/health")
    # Should return 503 when critical dependency (DynamoDB) is down
    assert response.status_code == 503
    data = response.json()
    assert data["detail"]["status"] == "degraded"
    assert "errors" in data["detail"]
    assert len(data["detail"]["errors"]) > 0


def test_validate_endpoint_exists(client):
    """Test validate endpoint exists and requires request body"""
    # Test that endpoint exists (should fail with 422 for missing body, not 404)
    response = client.post("/v1/validate")
    assert response.status_code == 422  # Unprocessable Entity (missing required fields)
