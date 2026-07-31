#!/usr/bin/env python3
"""Render a daily prep file to a readable Markdown review — the founder-facing artifact.

Turns state/daily/<date>.yaml into state/daily/<date>-review.md: a channel-first table
(best channel per fund: verified email / pitch form / LinkedIn), then one section per
fund (contact, verification, portfolio hook, adjacent-bet daylight, subject, full email,
LinkedIn note, and the pitch-form URL + ready-to-paste answers when one exists), then the
dropped-for-conflict table.

Run:  python scripts/outreach/render_review.py [--day YYYY-MM-DD]
Called automatically at the end of prep_daily.py.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib import daily  # noqa: E402
from lib.config import load_config, resolve  # noqa: E402


def _has_form(x: dict) -> bool:
    return x.get("pitch_form_url") not in (None, "none", "")


def render(data: dict, day: str) -> str:
    drafts = data.get("drafts", [])
    dropped = data.get("dropped", [])
    L: list[str] = []
    L.append(f"# VC Outreach — Review ({day})\n")
    L.append(f"**{len(drafts)} to reach out to** · **{len(dropped)} dropped for competitor conflict** (bottom table).\n")
    L.append("**Channels** (apply via the easiest): a **pitch form** = you paste the prepared answers + submit; "
             "**email** = I create a Gmail draft with the pitch PDF; **LinkedIn** = the ≤300-char note.\n")
    L.append("**Two flags:** `verify_contact` on a draft = written & clean, but the email/contact is unverified/missing — "
             "prefer the form or LinkedIn. `review_drop` in the dropped table = removed for a possible conflict, ambiguous — confirm or overturn.\n")

    L.append("## Channels\n")
    L.append("| # | Fund | Best channel | Pitch form | Email | LinkedIn |")
    L.append("|---|------|-------------|-----------|-------|----------|")
    for i, x in enumerate(drafts, 1):
        form = x.get("pitch_form_url") if _has_form(x) else "—"
        em = x["email"] if x["email"] not in (None, "none", "") else "—"
        L.append(f"| {i} | {x['fund']} | **{x.get('best_channel','?')}** | {form} | {em} | note ready |")
    L.append("")

    for i, x in enumerate(drafts, 1):
        em = x["email"] if x["email"] not in (None, "none", "") else "**NONE**"
        L.append(f"\n---\n\n## {i}. {x['fund']}  ·  _{x.get('conflict',{}).get('verdict','?')}_  ·  channel: **{x.get('best_channel','?')}**\n")
        L.append(f"- **Partner:** {x.get('partner','')} — {x.get('title','')}")
        L.append(f"- **LinkedIn:** {x.get('linkedin_url','')}")
        L.append(f"- **Email:** {em}  ·  _{x.get('email_provenance','?')} / {x.get('email_confidence','?')}_")
        if _has_form(x):
            v = "verified" if x.get("pitch_form_verified") else "unconfirmed"
            L.append(f"- **Pitch form:** {x['pitch_form_url']}  ·  _{x.get('pitch_form_type','')} ({v})_")
        L.append(f"- **Verify:** {x.get('person_recency','')}")
        L.append(f"- **Portfolio hook:** {', '.join(c.split(' —')[0].split(' (')[0] for c in x.get('portfolio_cos', []))}")
        L.append(f"- **Adjacent bet named:** {x.get('conflict',{}).get('adjacent_bet','')}")
        c = x.get("critic", {})
        status = "⚠️ verify_contact (email unverified — draft is ready)" if c.get("verdict") == "verify_contact" else "pass"
        L.append(f"- **Status:** {status}  ·  reply={c.get('reply_likelihood')} · voice={c.get('voice_ok')} · claims={c.get('claims_ok')} · hook_true={c.get('hook_true')}")
        li_only = x["email"] in (None, "none", "")
        if not li_only:
            # Email channel — show subject + body (which references the attached pitch PDF).
            L.append(f"\n**Subject:** {x.get('subject','')}\n")
            L.append("**Email (pitch PDF attached on send):**\n")
            L.append("```")
            L.append(str(x.get("body", "")).strip())
            L.append("```\n")
        else:
            # LinkedIn-only — NO email, NO attachment. Invite note + a fuller LinkedIn message.
            L.append("\n**LinkedIn-only** — no email/attachment. Send the connection note; after connecting, send the message below (offers the deck, never says 'attached').\n")
        L.append(f"**LinkedIn note / invite** ({len(x.get('linkedin_note',''))} chars):\n")
        L.append("```")
        L.append(x.get("linkedin_note", ""))
        L.append("```")
        if x.get("linkedin_message"):
            L.append(f"\n**LinkedIn message (InMail / after connecting — no attachment, offers deck):**")
            if x.get("linkedin_subject"):
                L.append(f"\n_Subject:_ {x['linkedin_subject']}\n")
            L.append("```")
            L.append(str(x["linkedin_message"]).strip())
            L.append("```")
        if _has_form(x) and x.get("pitch_form_answers", "").strip():
            L.append("\n**Pitch-form answers (paste into the form):**\n")
            L.append("```")
            L.append(x["pitch_form_answers"].strip())
            L.append("```")

    L.append("\n---\n\n## Dropped for competitor conflict (NOT contacted)\n")
    L.append("| Fund | Competitor | review_drop? | Source |")
    L.append("|------|-----------|-------------|--------|")
    for dr in dropped:
        rd = "**YES — confirm/overturn**" if dr.get("review_drop") else "no (settled)"
        L.append(f"| {dr.get('fund')} | {str(dr.get('competitor',''))[:50]} | {rd} | {str(dr.get('source',''))[:40]} |")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day", default=date.today().isoformat())
    args = ap.parse_args()
    cfg = load_config()
    daily_dir = resolve(cfg["state"]["daily_dir"])
    day_path = daily.daily_path(daily_dir, args.day)
    if not day_path.exists():
        print(f"[render] no daily file for {args.day}: {day_path}", file=sys.stderr)
        return 2
    data = daily.read_daily(day_path)
    out = day_path.with_name(f"{args.day}-review.md")
    out.write_text(render(data, args.day))
    print(f"[render] wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
