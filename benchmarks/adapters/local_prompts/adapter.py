"""Local Prompts Adapter reading demo-agents/eval/labeled_prompts.jsonl in-place (LLD 41 §5.1, WS-C milestone C5)."""

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List

from app.api.models import CONTENT_TEXT_MAX_LEN
from benchmarks.core.adapter import BenchmarkAdapter, ToolManifest
from benchmarks.core.case import BenchmarkCase
from benchmarks.core.registry import register


_REPO_ROOT = Path(__file__).resolve().parents[3]
LABELED_PROMPTS_PATH = _REPO_ROOT / "demo-agents" / "eval" / "labeled_prompts.jsonl"


class LocalPromptsAdapter:
    name: str = "local_prompts"
    upstream_repo: str = str(LABELED_PROMPTS_PATH.parent)

    def iter_cases(self, *, suite: str | None = None) -> Iterator[BenchmarkCase]:
        if not LABELED_PROMPTS_PATH.exists():
            raise FileNotFoundError(f"Local prompts corpus file not found at {LABELED_PROMPTS_PATH}")

        raw_cases: List[BenchmarkCase] = []
        with open(LABELED_PROMPTS_PATH, "r", encoding="utf-8") as f:
            for idx, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                data = json.loads(line)
                text = data.get("text", "")
                if len(text) > CONTENT_TEXT_MAX_LEN:
                    text = text[:CONTENT_TEXT_MAX_LEN]
                
                label_val = bool(data.get("label", 0))
                case_id = f"local_prompts:default:prompt_{idx:04d}"
                
                case = BenchmarkCase(
                    benchmark=self.name,
                    suite="default",
                    case_id=case_id,
                    episode_id=case_id,
                    phase="content",
                    agent_id="bench-local-prompts",
                    tool_name="ingest_content",
                    tool_params={},
                    user_input="",
                    content_text=text,
                    operation_type="READ",
                    label=label_val,
                    attack_type="indirect_injection" if label_val else None,
                    injection_goal="local_prompt_test" if label_val else None,
                    expected_outcome="deny" if label_val else "allow",
                    raw=data,
                )
                raw_cases.append(case)

        # Protocol requirement: deterministic order by case_id
        for case in sorted(raw_cases, key=lambda c: c.case_id):
            yield case

    def tool_manifest(self, *, suite: str) -> ToolManifest:
        raise NotImplementedError("local_prompts adapter is Mode A corpus only; tool_manifest is not implemented")

    def run_arm(self, *, arm: Any, ctx: Any) -> Any:
        raise NotImplementedError("local_prompts adapter is Mode A corpus only; run_arm is not implemented")

    def score_run(self, *, with_arm: Any, without_arm: Any) -> Any:
        raise NotImplementedError("local_prompts adapter is Mode A corpus only; score_run is not implemented")


# Register in adapter registry
register("local_prompts", lambda: LocalPromptsAdapter())
