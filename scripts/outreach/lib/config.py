"""Config + path helpers for the outreach automation.

Every path in config.yaml is repo-root-relative; resolve against the repo root
(three levels up from this file: lib/ -> outreach/ -> scripts/ -> repo).
"""
from __future__ import annotations

import functools
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
CONFIG_PATH = REPO_ROOT / "scripts" / "outreach" / "config.yaml"


@functools.lru_cache(maxsize=1)
def load_config() -> dict:
    with CONFIG_PATH.open() as fh:
        cfg = yaml.safe_load(fh)
    if not isinstance(cfg, dict):
        raise ValueError(f"config.yaml did not parse to a mapping: {CONFIG_PATH}")
    return cfg


def resolve(rel_path: str) -> Path:
    """Resolve a repo-root-relative path from config to an absolute Path."""
    return (REPO_ROOT / rel_path).resolve()
