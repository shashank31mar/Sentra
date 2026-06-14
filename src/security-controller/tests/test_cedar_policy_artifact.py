"""Tests for the Cedar co-artifact storage convention (CT06c).

Asserts the §7.1 storage model: the structured `.yaml` is the source of truth,
the `.cedar` is a derived co-artifact at the same key, and the two are fully
independent — deleting/regenerating the `.cedar` never touches the structured
source (so `allowed_callers` / `cross_cloud_dependencies` / `max_calls_per_minute`
survive).
"""
import boto3
import pytest
import yaml
from moto import mock_aws

from app.validators.cedar.policy_artifact import (
    FORMAT_CEDAR,
    FORMAT_YAML,
    CompiledPolicyNotFound,
    cedar_key_for,
    is_cedar_format,
    load_compiled_policies,
    put_compiled_policies,
)

BUCKET = "sentra-test-artifacts"
SRC_KEY = "policies/agents/acme-payments-agent/v3.yaml"


def test_cedar_key_swaps_extension():
    assert cedar_key_for("policies/agents/x/v3.yaml") == "policies/agents/x/v3.cedar"
    assert cedar_key_for("policies/agents/x/v3.yml") == "policies/agents/x/v3.cedar"
    assert cedar_key_for("policies/agents/x/v3.json") == "policies/agents/x/v3.cedar"


def test_cedar_key_source_key_unchanged():
    # The convention derives the .cedar key; the source key value is never mutated.
    src = "policies/agents/x/v3.yaml"
    derived = cedar_key_for(src)
    assert src == "policies/agents/x/v3.yaml"
    assert derived != src


def test_cedar_key_unexpected_extension_appends():
    assert cedar_key_for("weird/key.txt") == "weird/key.txt.cedar"


def test_is_cedar_format():
    assert is_cedar_format({"policy_format": FORMAT_CEDAR}) is True
    assert is_cedar_format({"policy_format": FORMAT_YAML}) is False
    assert is_cedar_format({}) is False


@mock_aws
def test_both_artifacts_coexist_at_convention_keys():
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)

    structured = {
        "agent_id": "acme-payments-agent",
        "allowed_tools": ["process_refund"],
        "allowed_callers": ["orchestrator"],
        "cross_cloud_dependencies": [{"tool": "sim_swap", "requires": "verify_identity"}],
        "max_calls_per_minute": 60,
    }
    s3.put_object(Bucket=BUCKET, Key=SRC_KEY, Body=yaml.dump(structured).encode())
    put_compiled_policies(s3, BUCKET, SRC_KEY, 'permit(principal, action, resource);')

    keys = {o["Key"] for o in s3.list_objects_v2(Bucket=BUCKET)["Contents"]}
    assert SRC_KEY in keys
    assert "policies/agents/acme-payments-agent/v3.cedar" in keys


@mock_aws
def test_loader_reads_compiled_cedar():
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    put_compiled_policies(s3, BUCKET, SRC_KEY, '// compiled\npermit(principal, action, resource);')

    text = load_compiled_policies(s3, BUCKET, SRC_KEY)
    assert "permit(principal, action, resource)" in text


@mock_aws
def test_missing_cedar_raises_not_found():
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    s3.put_object(Bucket=BUCKET, Key=SRC_KEY, Body=b"agent_id: x")  # source only

    with pytest.raises(CompiledPolicyNotFound):
        load_compiled_policies(s3, BUCKET, SRC_KEY)


@mock_aws
def test_deleting_cedar_does_not_lose_structured_fields():
    """The independence guarantee: dropping the .cedar leaves the structured
    source (and its non-Cedar fields) fully intact."""
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    structured = {
        "agent_id": "acme-payments-agent",
        "allowed_callers": ["orchestrator"],
        "cross_cloud_dependencies": [{"tool": "sim_swap", "requires": "verify_identity"}],
        "max_calls_per_minute": 60,
    }
    s3.put_object(Bucket=BUCKET, Key=SRC_KEY, Body=yaml.dump(structured).encode())
    put_compiled_policies(s3, BUCKET, SRC_KEY, "permit(principal, action, resource);")

    # Delete the generated co-artifact.
    s3.delete_object(Bucket=BUCKET, Key=cedar_key_for(SRC_KEY))

    # Source survives with every non-Cedar field.
    loaded = yaml.safe_load(s3.get_object(Bucket=BUCKET, Key=SRC_KEY)["Body"].read())
    assert loaded["allowed_callers"] == ["orchestrator"]
    assert loaded["cross_cloud_dependencies"][0]["requires"] == "verify_identity"
    assert loaded["max_calls_per_minute"] == 60
    with pytest.raises(CompiledPolicyNotFound):
        load_compiled_policies(s3, BUCKET, SRC_KEY)
