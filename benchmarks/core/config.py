"""CLI argument parsing and configuration for benchmark harness (LLD 41 §4.8)."""

import argparse
from dataclasses import dataclass
import sys
from typing import List, Optional


# Map of CLI flags that move numbers to their manifest locations for testing validation
NUMBER_MOVING_FLAGS = {
    "adapter": "benchmark.adapter",
    "mode": "mode",
    "suite": "benchmark.suites",
    "arms": "results.mode_b.arms",
    "attack": "benchmark.attack",
    "transport": "engine.transport",
    "base_url": "engine.base_url",
    "resume": "accounting.resumed_from",
    "allow_dirty": "benchmark.dirty",
    "user_tasks": "benchmark.task_subset",
    "injection_tasks": "benchmark.task_subset",
}


@dataclass(frozen=True)
class BenchmarkRunConfig:
    adapter: str
    mode: str = "A"
    suite: Optional[List[str]] = None
    arms: List[str] = None
    attack: Optional[str] = None
    model: str = "qwen2.5:3b"
    transport: str = "in-process"
    base_url: Optional[str] = None
    concurrency: int = 4
    resume: Optional[str] = None
    allow_dirty: bool = False
    user_tasks: Optional[List[str]] = None
    injection_tasks: Optional[List[str]] = None

    def __post_init__(self):
        if self.concurrency > 8:
            print("Error: --concurrency cannot exceed hard cap of 8.", file=sys.stderr)
            sys.exit(1)
        if self.mode not in ("A", "B", "AB"):
            print(f"Error: Invalid mode '{self.mode}'. Must be A, B, or AB.", file=sys.stderr)
            sys.exit(1)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sentra Security Benchmark Harness")
    parser.add_argument("--adapter", required=True, help="Benchmark adapter name (e.g. agentdojo, asb)")
    parser.add_argument("--mode", default="A", choices=["A", "B", "AB"], help="Execution mode (A, B, or AB)")
    parser.add_argument("--suite", nargs="*", help="Specific suite(s) to run")
    parser.add_argument("--arms", default="P1,P2,P3", help="Comma-separated arms for Mode B")
    parser.add_argument("--attack", help="Specific attack name")
    parser.add_argument("--model", default="qwen2.5:3b", help="Model name (e.g. qwen2.5:3b)")
    parser.add_argument("--transport", default="in-process", choices=["in-process", "hosted"], help="Transport mode")
    parser.add_argument("--base-url", help="Base URL for hosted transport")
    parser.add_argument("--concurrency", type=int, default=4, help="Concurrency limit (max 8)")
    parser.add_argument("--resume", help="Resume run from specified run_id")
    parser.add_argument("--allow-dirty", action="store_true", help="Allow running with uncommitted git changes")
    parser.add_argument("--user-tasks", nargs="*", help="Filter user tasks")
    parser.add_argument("--injection-tasks", nargs="*", help="Filter injection tasks")
    return parser


def parse_cli_args(args: Optional[List[str]] = None) -> BenchmarkRunConfig:
    parser = build_parser()
    parsed = parser.parse_args(args)

    arms_list = [a.strip() for a in parsed.arms.split(",") if a.strip()]

    config = BenchmarkRunConfig(
        adapter=parsed.adapter,
        mode=parsed.mode,
        suite=parsed.suite,
        arms=arms_list,
        attack=parsed.attack,
        model=parsed.model,
        transport=parsed.transport,
        base_url=parsed.base_url,
        concurrency=parsed.concurrency,
        resume=parsed.resume,
        allow_dirty=parsed.allow_dirty,
        user_tasks=parsed.user_tasks,
        injection_tasks=parsed.injection_tasks,
    )
    return config
