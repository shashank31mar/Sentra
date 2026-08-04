"""Run accounting and LLM cost estimation (LLD 41 §14.2, WS-E milestone E4)."""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


# Shared rate table from scripts/eval_ml_classifier.py
MODEL_RATES = {
    "claude-3-5-sonnet-20241022": {"input": 3.0 / 1_000_000, "output": 15.0 / 1_000_000},
    "claude-3-opus-20240229": {"input": 15.0 / 1_000_000, "output": 75.0 / 1_000_000},
    "claude-3-haiku-20240307": {"input": 0.25 / 1_000_000, "output": 1.25 / 1_000_000},
    "gpt-4o": {"input": 2.50 / 1_000_000, "output": 10.0 / 1_000_000},
    "gpt-4o-mini": {"input": 0.15 / 1_000_000, "output": 0.60 / 1_000_000},
}


def estimate_cost(model_id: str, input_tokens: int, output_tokens: int) -> float:
    """Calculate USD cost from tokens using pinned rate table."""
    rates = MODEL_RATES.get(model_id, MODEL_RATES["claude-3-5-sonnet-20241022"])
    return (input_tokens * rates["input"]) + (output_tokens * rates["output"])


@dataclass
class EpisodeAccounting:
    episode_id: str
    arm: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    n_validate_calls: int = 0
    wall_clock_s: float = 0.0


class RunAccountant:
    """Tracks token consumption, LLM spend, wall clock and validate calls per episode and arm."""

    def __init__(self, model_id: str = "claude-3-5-sonnet-20241022"):
        self.model_id = model_id
        self.episodes: Dict[Tuple[str, str], EpisodeAccounting] = {}
        self.n_validate_calls: int = 0
        self._start_time: float = time.time()

    def record_llm_call(
        self,
        episode_id: str,
        arm: str,
        input_tokens: int,
        output_tokens: int,
        model_id: Optional[str] = None,
    ) -> None:
        key = (episode_id, arm)
        if key not in self.episodes:
            self.episodes[key] = EpisodeAccounting(episode_id=episode_id, arm=arm)
        
        ep = self.episodes[key]
        ep.input_tokens += input_tokens
        ep.output_tokens += output_tokens
        used_model = model_id or self.model_id
        ep.cost_usd += estimate_cost(used_model, input_tokens, output_tokens)

    def record_validate_call(self, episode_id: Optional[str] = None, arm: Optional[str] = None) -> None:
        self.n_validate_calls += 1
        if episode_id and arm:
            key = (episode_id, arm)
            if key not in self.episodes:
                self.episodes[key] = EpisodeAccounting(episode_id=episode_id, arm=arm)
            self.episodes[key].n_validate_calls += 1

    def to_manifest_dict(self) -> Dict[str, Any]:
        total_input = sum(e.input_tokens for e in self.episodes.values())
        total_output = sum(e.output_tokens for e in self.episodes.values())
        total_cost = sum(e.cost_usd for e in self.episodes.values())
        wall_clock = time.time() - self._start_time

        by_arm: Dict[str, Dict[str, Any]] = {}
        for (ep_id, arm), ep in self.episodes.items():
            if arm not in by_arm:
                by_arm[arm] = {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "cost_usd": 0.0,
                    "n_validate_calls": 0,
                }
            by_arm[arm]["input_tokens"] += ep.input_tokens
            by_arm[arm]["output_tokens"] += ep.output_tokens
            by_arm[arm]["cost_usd"] += ep.cost_usd
            by_arm[arm]["n_validate_calls"] += ep.n_validate_calls

        return {
            "model_id": self.model_id,
            "total_input_tokens": total_input,
            "total_output_tokens": total_output,
            "total_cost_usd": round(total_cost, 4),
            "n_validate_calls": self.n_validate_calls,
            "wall_clock_s": round(wall_clock, 2),
            "by_arm": by_arm,
        }
