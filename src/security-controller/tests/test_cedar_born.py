"""Born-Cedar on save (CT12).

PolicyService._maybe_write_cedar generates + schema-validates the `.cedar`
co-artifact and writes it beside the structured source when `cedar_enabled`;
it's a no-op (structured-only) when the feature is off — so the default save
path is byte-identical to pre-Cedar.
"""
import boto3
import pytest
from moto import mock_aws

from app.config import settings
from app.services.policy_service import PolicyService
from app.validators.cedar import policy_artifact

BUCKET = "sentra-test-artifacts"
SRC_KEY = "policies/agents/acme/v1.yaml"
POLICY = {"agent_id": "acme", "allowed_tools": ["process_refund"], "allowed_agents": [],
          "max_refund_amount": 5000}


@pytest.fixture(autouse=True)
def _flags():
    before = settings.cedar_enabled
    yield
    settings.cedar_enabled = before


@mock_aws
def test_born_cedar_when_enabled():
    s3 = boto3.client("s3", region_name=settings.aws_region)
    s3.create_bucket(Bucket=BUCKET)
    settings.s3_bucket = BUCKET
    settings.cedar_enabled = True

    svc = PolicyService()
    fmt, genver = svc._maybe_write_cedar("agent-config-acme", POLICY, SRC_KEY)

    assert fmt == policy_artifact.FORMAT_CEDAR
    assert genver == "v1"
    # The .cedar co-artifact exists at the derived key and is valid Cedar.
    body = s3.get_object(Bucket=BUCKET, Key=policy_artifact.cedar_key_for(SRC_KEY))["Body"].read().decode()
    assert "permit(principal, action == Action::\"UseTool\"" in body


@mock_aws
def test_noop_when_disabled():
    s3 = boto3.client("s3", region_name=settings.aws_region)
    s3.create_bucket(Bucket=BUCKET)
    settings.s3_bucket = BUCKET
    settings.cedar_enabled = False

    svc = PolicyService()
    fmt, genver = svc._maybe_write_cedar("agent-config-acme", POLICY, SRC_KEY)

    assert fmt == policy_artifact.FORMAT_YAML
    assert genver is None
    # No co-artifact written.
    objs = s3.list_objects_v2(Bucket=BUCKET).get("Contents", [])
    assert objs == []
