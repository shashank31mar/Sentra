#!/usr/bin/env python3
"""Reconcile sent outreach into the human-readable tracker.

sent_log.jsonl is the machine idempotency key (written at send time). This step
mirrors newly-sent funds into pitch/internal/outreach-tracker.md so the tracker
stays the founder-facing source of truth, and lists any LinkedIn-note-only funds
the founder still needs to action by hand.

Idempotent: a fund already logged as reconciled is not appended twice. We track
what's been mirrored in state/reconciled.jsonl.

Run:  python scripts/outreach/reconcile.py [--day YYYY-MM-DD]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # make `lib` importable

from lib import daily  # noqa: E402
from lib.config import load_config, resolve  # noqa: E402

RECONCILE_MARKER = "<!-- outreach-automation: appended sends below -->"


def _load_reconciled(path: Path) -> set[str]:
    seen: set[str] = set()
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    seen.add(json.loads(line)["gmail_msg_id"])
                except (json.JSONDecodeError, KeyError):
                    continue
    return seen


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=date.today().isoformat())
    args = ap.parse_args()

    cfg = load_config()
    daily_dir = resolve(cfg["state"]["daily_dir"])
    day_path = daily.daily_path(daily_dir, args.day)
    if not day_path.exists():
        print(f"[reconcile] No daily file for {args.day}: {day_path}")
        return 0
    data = daily.read_daily(day_path)

    reconciled_log = resolve(cfg["state"]["sent_log"]).parent / "reconciled.jsonl"
    already = _load_reconciled(reconciled_log)

    tracker = resolve("pitch/internal/outreach-tracker.md")
    tracker_text = tracker.read_text() if tracker.exists() else ""
    if RECONCILE_MARKER not in tracker_text:
        tracker_text = tracker_text.rstrip() + f"\n\n---\n{RECONCILE_MARKER}\n"

    new_lines, manual, mirrored = [], [], []
    for d in data["drafts"]:
        if d.get("status") == "sent" and d.get("gmail_msg_id") not in already:
            new_lines.append(
                f"- {args.day} — **{d.get('fund')}** ({d.get('partner','?')}) — "
                f"email sent to {d.get('email')} + AegionAI-pitch.pdf. "
                f"[provenance: {d.get('email_provenance','?')}]"
            )
            mirrored.append(d)
        if d.get("email") in (None, "none", ""):
            manual.append(d)

    if new_lines:
        tracker_text = tracker_text.rstrip() + "\n" + "\n".join(new_lines) + "\n"
        tracker.write_text(tracker_text)
        with reconciled_log.open("a") as fh:
            for d in mirrored:
                fh.write(json.dumps({
                    "gmail_msg_id": d.get("gmail_msg_id"), "fund": d.get("fund"),
                    "day": args.day,
                }) + "\n")
        print(f"[reconcile] Appended {len(new_lines)} sent funds to {tracker}.")
    else:
        print("[reconcile] Nothing new to mirror into the tracker.")

    if manual:
        print(f"\n[reconcile] {len(manual)} LinkedIn-note-only funds need a manual invite from you:")
        for d in manual:
            print(f"   • {d.get('fund')} — {d.get('linkedin_url','?')}")
            print(f"     note: {d.get('linkedin_note','')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
