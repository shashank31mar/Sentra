"""Unit tests for cloud_provider resolution (WS-21 Kombai crash fix)."""
from app.utils.cloud import resolve_cloud_provider


def test_stored_cloud_provider_wins():
    assert resolve_cloud_provider({"cloud_provider": "azure", "platform": "bedrock"}) == "azure"


def test_derive_from_platform_when_missing():
    assert resolve_cloud_provider({"platform": "bedrock"}) == "aws"
    assert resolve_cloud_provider({"platform": "azure_foundry"}) == "azure"
    assert resolve_cloud_provider({"platform": "vertex_ai"}) == "gcp"
    assert resolve_cloud_provider({"platform": "sentra"}) == "aws"


def test_unknown_when_neither_present():
    assert resolve_cloud_provider({}) == "unknown"
    assert resolve_cloud_provider({"platform": "something-new"}) == "unknown"
    assert resolve_cloud_provider(None) == "unknown"
