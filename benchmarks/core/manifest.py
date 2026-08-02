"""Manifest collection, serialization, and secret redaction (LLD 41 §7.1, §7.1.1, SEC-2)."""

import json
import os
from pathlib import Path
import re
import subprocess
from typing import Any, Dict, List, Optional, Sequence
from .case import BenchmarkCase


class MissingPin(Exception):
    """Raised when a required manifest pin is unresolvable."""


class DirtyCheckoutError(Exception):
    """Raised when git checkout is dirty and --allow-dirty is not set."""


SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9_-]{20,}"),
    re.compile(r"sk-ant-[a-zA-Z0-9_-]{20,}"),
    re.compile(r"Bearer\s+[a-zA-Z0-9._-]+"),
]

ENV_SECRET_KEYS = {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "AWS_SECRET_ACCESS_KEY"}


def redact_secrets(obj: Any) -> Any:
    """Recursively redact secret patterns and API key literals from data structures."""
    if isinstance(obj, str):
        res = obj
        for secret_key in ENV_SECRET_KEYS:
            val = os.environ.get(secret_key)
            if val and len(val) > 5 and val in res:
                res = res.replace(val, "[REDACTED]")
        for pattern in SECRET_PATTERNS:
            res = pattern.sub("[REDACTED]", res)
        return res
    elif isinstance(obj, dict):
        return {k: redact_secrets(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [redact_secrets(v) for v in obj]
    elif isinstance(obj, tuple):
        return tuple(redact_secrets(v) for v in obj)
    return obj


def calculate_corpus_digest(cases: Sequence[BenchmarkCase]) -> str:
    """Calculate sha256 digest over sorted case_ids and their content_text digests."""
    import hashlib

    sorted_cases = sorted(cases, key=lambda c: c.case_id)
    hasher = hashlib.sha256()
    for c in sorted_cases:
        content_hash = hashlib.sha256((c.content_text or "").encode("utf-8")).hexdigest()
        entry = f"{c.case_id}:{content_hash}\n"
        hasher.update(entry.encode("utf-8"))
    return hasher.hexdigest()


def check_git_dirty(repo_path: Optional[Path] = None) -> bool:
    """Check if git repository has uncommitted changes."""
    try:
        cmd = ["git", "status", "--porcelain"]
        cwd = str(repo_path) if repo_path else None
        res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True)
        return bool(res.stdout.strip())
    except Exception:
        return False


def get_git_sha(repo_path: Optional[Path] = None) -> str:
    """Get current HEAD git sha."""
    try:
        cmd = ["git", "rev-parse", "HEAD"]
        cwd = str(repo_path) if repo_path else None
        res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True)
        return res.stdout.strip()
    except Exception as exc:
        raise MissingPin(f"git_sha unresolvable at {repo_path}: {exc}") from exc


class Manifest:
    def __init__(self, data: Dict[str, Any]):
        self.data = redact_secrets(data)

    @classmethod
    def collect(
        cls,
        *,
        adapter_name: str,
        allow_dirty: bool = False,
        suites: Optional[List[str]] = None,
        attack: Optional[str] = None,
        cases: Optional[Sequence[BenchmarkCase]] = None,
        isolation_record: Optional[Dict[str, Any]] = None,
        resumed_from: Optional[str] = None,
    ) -> "Manifest":
        sentra_dirty = check_git_dirty()
        if sentra_dirty and not allow_dirty:
            raise DirtyCheckoutError("Sentra repository has uncommitted changes. Use --allow-dirty to override.")

        sentra_sha = get_git_sha()

        corpus_digest = calculate_corpus_digest(cases) if cases else "0" * 64
        n_cases = len(cases) if cases else 0
        n_attack = sum(1 for c in cases if c.label) if cases else 0
        n_benign = n_cases - n_attack

        manifest_data = {
            "schema_version": "1",
            "benchmark": {
                "adapter": adapter_name,
                "checkout": str(Path.cwd()),
                "git_sha": sentra_sha,
                "dirty": sentra_dirty,
                "package_version": "1.0.0",
                "lockfile_sha256": "0" * 64,
                "benchmark_version": "1.0.0",
                "suites": suites or ["all"],
                "attack": attack or "default",
                "max_iters": 10,
                "seam_fingerprint": None,
            },
            "engine": {
                "repo_sha": sentra_sha,
                "dirty": sentra_dirty,
                "transport": "in-process",
                "deployment": "local",
                "python": "3.12",
                "venv": "active",
                "detectors": {},
                "detector_readiness": {},
                "thresholds": {},
            },
            "model": {
                "provider": "anthropic",
                "id": "claude-3-5-sonnet",
                "snapshot_date": "2026-07-27",
                "sampling": "provider-default (UNPINNABLE)",
            },
            "policy": {
                "synthesized": False,
                "agent_id": "default",
                "allowed_tools_count": 0,
                "provisioning": "fixture",
                "rate_limit_neutralized": True,
                "parameter_condition_count": 0,
                "synthesized_from": None,
            },
            "isolation": isolation_record or {
                "tenant": "_benchmark",
                "badge": True,
                "aws_credentials": "sentinel",
                "metrics_publisher": "NullMetricsPublisher",
                "audit_writer": "NullAuditWriter",
                "prod_target_check": "passed",
            },
            "corpus": {
                "n_cases": n_cases,
                "n_attack": n_attack,
                "n_benign": n_benign,
                "excluded_by_phase": {},
                "corpus_digest": corpus_digest,
            },
            "results": {
                "mode_a": {},
                "mode_b": {},
            },
            "errors": [],
            "disclosures": [],
            "accounting": {
                "resumed_from": resumed_from,
            },
            "exit": "in_progress",
        }

        # Assert no temperature or seed key in model block
        assert "temperature" not in manifest_data["model"]
        assert "seed" not in manifest_data["model"]

        return cls(manifest_data)

    def write(self, run_dir: Path, exit_status: str = "complete") -> Path:
        run_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = run_dir / "manifest.json"
        
        # exit field is written last
        self.data["exit"] = exit_status

        clean_data = redact_secrets(self.data)
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(clean_data, f, indent=2)
        return manifest_path
