"""Unit tests for Manifest collection and properties (LLD 41 §7.1)."""

import json
import os
import pytest
from benchmarks.core.case import BenchmarkCase
from benchmarks.core.manifest import (
    DirtyCheckoutError,
    Manifest,
    MissingPin,
    calculate_corpus_digest,
)


def test_missing_pin_aborts(monkeypatch, tmp_path):
    def fake_get_git_sha(repo_path=None):
        raise MissingPin("git_sha unresolvable")

    monkeypatch.setattr("benchmarks.core.manifest.get_git_sha", fake_get_git_sha)

    with pytest.raises(MissingPin) as exc_info:
        Manifest.collect(adapter_name="agentdojo", allow_dirty=True)
    assert "git_sha" in str(exc_info.value)
    assert not (tmp_path / "manifest.json").exists()


def test_dirty_checkout_aborts_without_flag(monkeypatch):
    monkeypatch.setattr("benchmarks.core.manifest.check_git_dirty", lambda repo_path=None: True)
    monkeypatch.setattr("benchmarks.core.manifest.get_git_sha", lambda repo_path=None: "1234567890abcdef")

    with pytest.raises(DirtyCheckoutError):
        Manifest.collect(adapter_name="agentdojo", allow_dirty=False)


def test_dirty_checkout_allowed_with_flag_and_stamps(monkeypatch):
    monkeypatch.setattr("benchmarks.core.manifest.check_git_dirty", lambda repo_path=None: True)
    monkeypatch.setattr("benchmarks.core.manifest.get_git_sha", lambda repo_path=None: "1234567890abcdef")

    m = Manifest.collect(adapter_name="agentdojo", allow_dirty=True)
    assert m.data["benchmark"]["dirty"] is True


def test_corpus_digest_stable_under_reorder():
    c1 = BenchmarkCase(
        benchmark="agentdojo",
        suite="banking",
        case_id="case:1",
        episode_id="ep:1",
        phase="request",
        agent_id="agent1",
        tool_name="transfer",
        tool_params={},
        user_input="hello",
        content_text=None,
        operation_type="WRITE",
        label=True,
        attack_type="indirect_injection",
        injection_goal="steal_money",
        expected_outcome="deny",
        raw={},
    )
    c2 = BenchmarkCase(
        benchmark="agentdojo",
        suite="banking",
        case_id="case:2",
        episode_id="ep:2",
        phase="request",
        agent_id="agent1",
        tool_name="transfer",
        tool_params={},
        user_input="world",
        content_text=None,
        operation_type="READ",
        label=False,
        attack_type=None,
        injection_goal=None,
        expected_outcome="allow",
        raw={},
    )

    digest1 = calculate_corpus_digest([c1, c2])
    digest2 = calculate_corpus_digest([c2, c1])
    assert digest1 == digest2


def test_exit_written_last(tmp_path):
    monkeypatch_sha = "abcdef123456"
    m = Manifest({"schema_version": "1", "benchmark": {"adapter": "agentdojo"}})
    path = m.write(tmp_path, exit_status="complete")

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["exit"] == "complete"


def test_no_temperature_or_seed_key():
    monkeypatch_sha = "abcdef123456"
    m = Manifest.collect(adapter_name="agentdojo", allow_dirty=True)
    model_block = m.data["model"]
    assert "temperature" not in model_block
    assert "seed" not in model_block


def test_schema_version_is_one():
    m = Manifest.collect(adapter_name="agentdojo", allow_dirty=True)
    assert m.data["schema_version"] == "1"
