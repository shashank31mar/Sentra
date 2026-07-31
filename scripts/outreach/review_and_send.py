#!/usr/bin/env python3
"""Interactive review + send — the two human gates.

Subcommands (the flow):
  show                 Gate 1: print the newest pending daily file as a review table
                       (fund · contact · verification · subject · body · LinkedIn note).
  draft [--only 1,3]   Create Gmail drafts (pitch PDF attached) for approved rows.
                       Marks each row draft_created + records gmail_draft_id.
  send  [--only 1,3]   Gate 2: batch-send the created drafts (respects dry_run + throttle).
                       Marks sent + records gmail_msg_id; appends to sent_log.

Typical use (also driven conversationally by Claude):
  python scripts/outreach/review_and_send.py show
  # (you approve in chat / decide the subset)
  python scripts/outreach/review_and_send.py draft --only 1,2,4,5
  # (you eyeball the drafts in Gmail, then say "go ahead")
  python scripts/outreach/review_and_send.py send --only 1,2,4,5
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # make `lib` importable

from lib import daily  # noqa: E402
from lib.config import load_config, resolve  # noqa: E402
from lib.gmail import GmailClient  # noqa: E402


def _load_pending(cfg: dict) -> tuple[Path, dict]:
    daily_dir = resolve(cfg["state"]["daily_dir"])
    path = daily.latest_pending(daily_dir)
    if path is None:
        print("[review] No pending daily file. Run prep_daily.py first (or all are sent/skipped).")
        raise SystemExit(0)
    return path, daily.read_daily(path)


def _parse_only(only: str | None, count: int) -> set[int]:
    """--only '1,3,5' -> {0,2,4} (1-indexed input). None -> all indices."""
    if not only:
        return set(range(count))
    idx = set()
    for tok in only.split(","):
        tok = tok.strip()
        if tok.isdigit():
            idx.add(int(tok) - 1)
    return {i for i in idx if 0 <= i < count}


def _gmail(cfg: dict) -> GmailClient:
    g = cfg["gmail"]
    return GmailClient(resolve(g["credentials"]), resolve(g["token"]), g["scopes"])


# --- Gate 1: show ---------------------------------------------------------
def cmd_show(cfg: dict) -> int:
    path, data = _load_pending(cfg)
    drafts = data["drafts"]
    dropped = data.get("dropped") or []
    if dropped:
        print(f"\n⚠️  Stage-0 dropped {len(dropped)} fund(s) today for a FRESH competitor conflict:")
        for d in dropped:
            hr = " (REVIEW DROP — rescue?)" if d.get("review_drop") else ""
            print(f"     • {d.get('fund')} → {d.get('competitor')} — {d.get('evidence','')}{hr}")
            print(f"       source: {d.get('source','?')}")

    print(f"\n=== GATE 1 REVIEW — {path.name} — {len(drafts)} drafts ===\n")
    for i, d in enumerate(drafts, 1):
        c = d.get("critic", {})
        conf = d.get("conflict", {})
        flag = " ⚠️ VERIFY CONTACT" if c.get("verdict") == "verify_contact" else ""
        li_only = " [LinkedIn-note-only — no email]" if d.get("email") in (None, "none", "") else ""
        print(f"── [{i}] {d.get('fund')} — {d.get('prestige')}{flag}{li_only}")
        print(f"   Conflict re-check (today): {conf.get('verdict','?')}"
              + (f" — adjacent: {conf.get('adjacent_bet')}" if conf.get('adjacent_bet') else "")
              + (f"  [src {conf.get('source')}]" if conf.get('source') else ""))
        print(f"   Contact : {d.get('partner')} ({d.get('title','?')}) — {d.get('linkedin_url','?')}")
        print(f"   Email   : {d.get('email','none')}  "
              f"[{d.get('email_provenance','?')} / conf {d.get('email_confidence','?')}]")
        print(f"   Verify  : {d.get('person_recency','?')}")
        print(f"   Portfolio hook: {', '.join(d.get('portfolio_cos', []))}")
        print(f"   Critic  : reply={c.get('reply_likelihood')} voice={c.get('voice_ok')} "
              f"claims={c.get('claims_ok')} hook_true={c.get('hook_true')} → {c.get('verdict')}")
        if c.get("notes"):
            print(f"             notes: {c.get('notes')}")
        print(f"   Subject : {d.get('subject')}")
        print("   ---- email ----")
        for line in str(d.get("body", "")).splitlines():
            print(f"   | {line}")
        print(f"   ---- LinkedIn note ({len(d.get('linkedin_note',''))} chars) ----")
        print(f"   | {d.get('linkedin_note','')}")
        print()
    print("Approve a subset, then: review_and_send.py draft --only 1,2,4  (then eyeball in Gmail, then send).")
    return 0


# --- draft creation -------------------------------------------------------
def cmd_draft(cfg: dict, only: str | None) -> int:
    path, data = _load_pending(cfg)
    drafts = data["drafts"]
    picked = _parse_only(only, len(drafts))
    pitch_pdf = resolve(cfg["attachment"]["pitch_pdf"])
    sender = cfg["sender"]["address"]
    if not sender:
        print("[draft] config.sender.address is empty — set your Gmail address first.", file=sys.stderr)
        return 2
    client = _gmail(cfg)

    made = 0
    for i in sorted(picked):
        d = drafts[i]
        if d.get("email") in (None, "none", ""):
            print(f"[draft] [{i+1}] {d.get('fund')} is LinkedIn-note-only — skipping Gmail draft.")
            continue
        if d.get("status") == "sent":
            print(f"[draft] [{i+1}] {d.get('fund')} already sent — skipping.")
            continue
        msg = GmailClient.build_message(
            sender=sender, to=d["email"], subject=d["subject"],
            body=d["body"], attachment=pitch_pdf,
        )
        res = client.create_draft(msg)
        d["gmail_draft_id"] = res.get("id")
        d["status"] = "draft_created"
        made += 1
        print(f"[draft] [{i+1}] {d.get('fund')} -> draft {res.get('id')} (PDF attached)")

    daily.save_daily(path, data)
    print(f"\n[draft] Created {made} Gmail drafts. Open Gmail, eyeball them + the attachment.")
    print("[draft] When happy, say go ahead:  review_and_send.py send --only <same subset>")
    return 0


# --- Gate 2: send ---------------------------------------------------------
def cmd_send(cfg: dict, only: str | None) -> int:
    path, data = _load_pending(cfg)
    drafts = data["drafts"]
    picked = _parse_only(only, len(drafts))
    dry_run = cfg["send"].get("dry_run", True)
    throttle = cfg["send"].get("throttle_seconds", 90)
    sent_log = resolve(cfg["state"]["sent_log"])
    sent_log.parent.mkdir(parents=True, exist_ok=True)
    client = _gmail(cfg)

    to_send = [
        i for i in sorted(picked)
        if drafts[i].get("status") == "draft_created" and drafts[i].get("gmail_draft_id")
    ]
    if not to_send:
        print("[send] Nothing to send (create drafts first with `draft`).")
        return 0
    if dry_run:
        print(f"[send] DRY-RUN: would send {len(to_send)} drafts. Set config.send.dry_run=false to send for real.")
        for i in to_send:
            print(f"   would send [{i+1}] {drafts[i].get('fund')} -> {drafts[i].get('email')}")
        return 0

    sent = 0
    with sent_log.open("a") as log:
        for n, i in enumerate(to_send):
            d = drafts[i]
            res = client.send_draft(d["gmail_draft_id"])
            d["gmail_msg_id"] = res.get("id")
            d["status"] = "sent"
            log.write(json.dumps({
                "fund": d.get("fund"), "email": d.get("email"),
                "date": date.today().isoformat(), "gmail_msg_id": res.get("id"),
            }) + "\n")
            sent += 1
            print(f"[send] ✓ [{i+1}] {d.get('fund')} -> {d.get('email')} (msg {res.get('id')})")
            if n < len(to_send) - 1:
                time.sleep(throttle)

    daily.save_daily(path, data)
    print(f"\n[send] Sent {sent}. Run reconcile.py to update the tracker.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("show")
    dp = sub.add_parser("draft"); dp.add_argument("--only", default=None)
    sp = sub.add_parser("send"); sp.add_argument("--only", default=None)
    args = ap.parse_args()

    cfg = load_config()
    if args.cmd == "show":
        return cmd_show(cfg)
    if args.cmd == "draft":
        return cmd_draft(cfg, args.only)
    if args.cmd == "send":
        return cmd_send(cfg, args.only)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
