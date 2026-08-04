"""Unit tests for secret redaction in Manifest and Report (SEC-2)."""

import os
from benchmarks.core.manifest import Manifest, redact_secrets
from benchmarks.core.report import generate_report


def test_api_keys_never_serialized(monkeypatch, tmp_path):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-SECRET_TEST_KEY_123456789012345")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-proj-SECRET_OPENAI_KEY_987654321098765")

    m = Manifest.collect(adapter_name="agentdojo", allow_dirty=True)
    m.data["benchmark"]["raw"] = {
        "anthropic_key": os.environ["ANTHROPIC_API_KEY"],
        "openai_key": os.environ["OPENAI_API_KEY"],
    }
    
    path = m.write(tmp_path, exit_status="complete")
    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    assert "SECRET_TEST_KEY" not in content
    assert "SECRET_OPENAI_KEY" not in content
    assert "[REDACTED]" in content


def test_redact_secrets_catches_embedded_key_patterns():
    nested_data = {
        "outer": {
            "inner": "Bearer sk-ant-api03-abcdefghijklmnopqrstuvwxyz123456"
        }
    }
    redacted = redact_secrets(nested_data)
    assert "[REDACTED]" in redacted["outer"]["inner"]
    assert "sk-ant-api03" not in redacted["outer"]["inner"]
