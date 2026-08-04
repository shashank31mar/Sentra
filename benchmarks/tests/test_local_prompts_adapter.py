"""Unit tests for local_prompts adapter (LLD 41 §5.1, WS-C milestone C5)."""

import pytest
from benchmarks.adapters.local_prompts.adapter import LABELED_PROMPTS_PATH, LocalPromptsAdapter
from benchmarks.core.case import BenchmarkCase


def test_reads_corpus_in_place():
    adapter = LocalPromptsAdapter()
    assert str(LABELED_PROMPTS_PATH).endswith("demo-agents/eval/labeled_prompts.jsonl")
    assert LABELED_PROMPTS_PATH.exists()


def test_flat_rows_become_benchmark_cases():
    adapter = LocalPromptsAdapter()
    cases = list(adapter.iter_cases())
    assert len(cases) > 0
    c0 = cases[0]
    assert isinstance(c0, BenchmarkCase)
    assert c0.phase == "content"
    assert c0.benchmark == "local_prompts"


def test_unsupported_methods_raise_clearly():
    adapter = LocalPromptsAdapter()
    with pytest.raises(NotImplementedError) as exc_info:
        adapter.tool_manifest(suite="default")
    assert "local_prompts adapter is Mode A corpus only" in str(exc_info.value)
