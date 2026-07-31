"""Read/write the per-day prep file — the handoff between the unattended 8 AM prep
and the interactive review (Gate 1).

The 8 AM job writes state/daily/<date>.yaml with the 10 vetted drafts. The review
step reads the newest pending one. Schema is a plain dict so the headless prep
(which writes YAML directly) and Python both agree on the shape.

Per-fund draft record (what Gate 1 shows you):
  fund, prestige, partner, title, firm, linkedin_url,
  email, email_provenance, email_confidence, person_recency,
  portfolio_cos: [..],
  subject, body, linkedin_note,
  critic: {reply_likelihood, voice_ok, claims_ok, hook_true, verdict, notes},
  status: prepared|approved|skipped|draft_created|sent,
  gmail_draft_id, gmail_msg_id
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import yaml


def daily_path(daily_dir: Path, day: str | None = None) -> Path:
    day = day or date.today().isoformat()
    return daily_dir / f"{day}.yaml"


def write_daily(daily_dir: Path, drafts: list[dict], day: str | None = None) -> Path:
    daily_dir.mkdir(parents=True, exist_ok=True)
    path = daily_path(daily_dir, day)
    payload = {
        "day": day or date.today().isoformat(),
        "count": len(drafts),
        "drafts": drafts,
    }
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=100))
    return path


def read_daily(path: Path) -> dict:
    with path.open() as fh:
        data = yaml.safe_load(fh) or {}
    if "drafts" not in data:
        raise ValueError(f"{path} has no 'drafts' key")
    return data


def latest_pending(daily_dir: Path) -> Path | None:
    """Newest daily file that still has at least one draft not yet sent/skipped."""
    if not daily_dir.exists():
        return None
    candidates = sorted(daily_dir.glob("*.yaml"), reverse=True)
    for path in candidates:
        try:
            data = read_daily(path)
        except (ValueError, yaml.YAMLError):
            continue
        for d in data.get("drafts", []):
            if d.get("status") in (None, "prepared", "approved", "draft_created"):
                return path
    return None


def save_daily(path: Path, data: dict) -> None:
    """Persist an updated daily dict back to disk (after status changes)."""
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100))
