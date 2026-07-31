#!/usr/bin/env python3
"""8 AM automated prep — unattended.

Dequeues the next N eligible funds (minus already-sent), renders the prep prompt,
invokes headless Claude Code (which reuses brand-voice / outreach skills to enrich,
draft, and self-review), and confirms the daily file was written.

Nothing here sends or drafts to Gmail — it only produces state/daily/<date>.yaml,
which the interactive review step (review_and_send.py) picks up at Gate 1.

Run:  python scripts/outreach/prep_daily.py [--day YYYY-MM-DD] [--n 10]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # make `lib` importable

from lib import daily, queue  # noqa: E402
from lib.config import REPO_ROOT, load_config, resolve  # noqa: E402


def _is_weekend(day: str) -> bool:
    return datetime.fromisoformat(day).weekday() >= 5  # 5=Sat, 6=Sun


def _fund_block(funds: list[dict]) -> str:
    """Render the dequeued funds as a readable list for the prompt."""
    lines = []
    for i, f in enumerate(funds, 1):
        lines.append(
            f"{i}. **{f.get('fund','?')}** "
            f"(prestige {f.get('prestige','?')}, {f.get('geo','?')}, "
            f"partner: {f.get('partner') or 'find one'})\n"
            f"   - Stage: {f.get('stage','?')} | lead-capable: {f.get('lead_capable', True)} "
            f"| known contact: {f.get('contact_hint','none-found')}\n"
            f"   - Why they fit (use for personalization): {f.get('thesis_evidence','')}"
        )
    return "\n".join(lines)


def build_prompt(cfg: dict, funds: list[dict], n: int, day: str, out_path: Path) -> Path:
    tpl = resolve(cfg["prep"]["prompt_template"]).read_text()
    pitch = resolve(cfg["prep"]["pitch_source"]).read_text()
    rubric = resolve(cfg["prep"]["rubric"]).read_text()

    voice_path = resolve(cfg["prep"].get("voice_profile", ""))
    voice = (
        voice_path.read_text()
        if voice_path and voice_path.exists()
        else "(No voice profile yet — write plainly and directly, like a technical founder. "
        "Short sentences, concrete proof over adjectives, no hype words, no corporate filler.)"
    )

    # {n} is the TARGET count (daily cap); the fund_block is the larger working set to refill from.
    prompt = (
        tpl.replace("{n}", str(n))
        .replace("{fund_block}", _fund_block(funds))
        .replace("{rubric}", rubric)
        .replace("{pitch}", pitch)
        .replace("{voice}", voice)
        .replace("{sign_off}", cfg["sender"]["sign_off"])
        .replace("{out_path}", str(out_path))
        .replace("{day}", day)
    )
    # Write the rendered prompt next to the daily dir for auditability + the @file handoff.
    prompt_dir = resolve(cfg["state"]["daily_dir"]) / "prompts"
    prompt_dir.mkdir(parents=True, exist_ok=True)
    prompt_file = prompt_dir / f"{day}.md"
    prompt_file.write_text(prompt)
    return prompt_file


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=date.today().isoformat())
    ap.add_argument("--n", type=int, default=None)
    ap.add_argument("--force-weekend", action="store_true")
    ap.add_argument("--refresh", action="store_true",
                    help="force a fresh batch even if a prior day's drafts are still un-sent")
    args = ap.parse_args()

    cfg = load_config()
    day = args.day
    n = args.n or cfg["send"]["daily_cap"]

    if _is_weekend(day) and not cfg["send"].get("weekends", False) and not args.force_weekend:
        print(f"[prep] {day} is a weekend and weekends are off; skipping.")
        return 0

    queue_path = resolve(cfg["queue"]["file"])
    if not queue_path.exists():
        print(
            f"[prep] Queue not found: {queue_path}\n"
            "       The curated send_queue.yaml must exist and be founder-approved first.",
            file=sys.stderr,
        )
        return 2

    daily_dir = resolve(cfg["state"]["daily_dir"])

    # RESUME-PENDING: if a prior day's drafts are still un-actioned (prepared / draft_created,
    # i.e. not yet sent or skipped), don't regenerate a fresh batch over the same funds — the
    # queue advances only when funds are actually sent/skipped. Point the founder at the pending
    # file to review instead. Use --refresh to force a new batch anyway.
    pending = daily.latest_pending(daily_dir)
    if pending is not None and not args.refresh:
        pdata = daily.read_daily(pending)
        n_open = sum(1 for d in pdata.get("drafts", [])
                     if d.get("status") in (None, "prepared", "draft_created"))
        print(f"[prep] {pending.name} still has {n_open} un-sent draft(s) — NOT regenerating.")
        print("[prep] Review/act on them first:  python scripts/outreach/review_and_send.py show")
        print("[prep] (Once sent or skipped, the next run advances to the next funds.)")
        print("[prep] Force a fresh batch anyway with:  prep_daily.py --refresh")
        return 0

    sent_log = resolve(cfg["state"]["sent_log"])
    dropped_log = resolve(cfg["state"]["dropped_log"])
    # Dequeue a working set LARGER than the cap so Stage-0 conflict drops can refill to n.
    mult = cfg["prep"].get("working_set_multiplier", 2)
    working = queue.next_batch(queue_path, sent_log, n * mult, dropped_log_path=dropped_log)
    if not working:
        print("[prep] Queue exhausted — no fresh funds left. 🎉 (Add more to send_queue.yaml.)")
        return 0

    out_path = daily.daily_path(daily_dir, day)
    prompt_file = build_prompt(cfg, working, n, day, out_path)

    cmd = cfg["prep"]["claude_cmd"].replace("{prompt_file}", str(prompt_file))
    print(f"[prep] {day}: prepping {len(working)} funds -> {out_path}")
    print(f"[prep] invoking: {cmd}")

    try:
        subprocess.run(
            cmd, shell=True, cwd=str(REPO_ROOT),
            timeout=cfg["prep"].get("timeout_seconds", 1800), check=True,
        )
    except subprocess.TimeoutExpired:
        print("[prep] headless prep timed out.", file=sys.stderr)
        return 3
    except subprocess.CalledProcessError as e:
        print(f"[prep] headless prep exited {e.returncode}.", file=sys.stderr)
        return 3

    # Fail loud if the model didn't actually write the file.
    if not out_path.exists():
        print(f"[prep] ERROR: prep finished but {out_path} was not written.", file=sys.stderr)
        return 4
    data = daily.read_daily(out_path)

    # Persist any funds Stage-0 dropped for a fresh conflict, so they aren't re-picked tomorrow.
    dropped = data.get("dropped") or []
    if dropped:
        dropped_log.parent.mkdir(parents=True, exist_ok=True)
        import json as _json
        with dropped_log.open("a") as fh:
            for d in dropped:
                fh.write(_json.dumps({
                    "fund": d.get("fund"), "competitor": d.get("competitor"),
                    "evidence": d.get("evidence"), "source": d.get("source"),
                    "review_drop": d.get("review_drop", False),
                    "day": day,
                }) + "\n")
        print(f"[prep] ⚠️  Stage-0 dropped {len(dropped)} fund(s) for fresh conflict:")
        for d in dropped:
            flag = " (REVIEW DROP — rescue?)" if d.get("review_drop") else ""
            print(f"        - {d.get('fund')} → {d.get('competitor')}{flag}")

    # Render the founder-facing Markdown review (channel-first).
    try:
        import render_review
        review_md = render_review.render(data, day)
        out_path.with_name(f"{day}-review.md").write_text(review_md)
        print(f"[prep] ✓ wrote review: {out_path.with_name(f'{day}-review.md')}")
    except Exception as e:  # rendering is a convenience; never fail the run on it
        print(f"[prep] (review-md render skipped: {e})")

    print(f"[prep] ✓ wrote {data.get('count', '?')} drafts to {out_path}")
    print("[prep] Review: open the -review.md, or: python scripts/outreach/review_and_send.py show")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
