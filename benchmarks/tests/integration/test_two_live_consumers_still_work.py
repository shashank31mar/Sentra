"""Integration test ensuring demo-agents/eval/labeled_prompts.jsonl path is preserved for existing consumers."""

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
LABELED_PROMPTS_PATH = _REPO_ROOT / "demo-agents" / "eval" / "labeled_prompts.jsonl"


def test_two_live_consumers_still_work():
    assert LABELED_PROMPTS_PATH.exists(), f"labeled_prompts.jsonl moved! Path {LABELED_PROMPTS_PATH} must exist."
