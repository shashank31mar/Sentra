#!/usr/bin/env python3
"""Real form-liveness check — 'does this pitch form actually work?', not 'does the URL 200?'.

Pitch forms (Typeform / Webflow / Squarespace) render client-side, so a raw HTTP 200 says
nothing about whether the form is live and accepting submissions. This drives headless Chrome
to render the page, then inspects the post-JS DOM for:
  - real input surface (input / textarea / contenteditable / typeform renderer), AND
  - absence of a 'closed / not accepting responses / expired' state.

Verdict per URL: LIVE | CLOSED | NO_FORM | UNREACHABLE — with the evidence snippet.

Usage:
  python scripts/outreach/check_forms.py --day 2026-07-28      # check every form in the daily file, write results back
  python scripts/outreach/check_forms.py <url> [<url> ...]     # ad-hoc check
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

CLOSED_PATTERNS = [
    r"form is closed", r"no longer accepting", r"not accepting responses",
    r"this typeform is closed", r"has been closed", r"is closed\b",
    r"applications? (are )?closed", r"submissions? (are )?closed",
    r"window (is )?closed", r"expired", r"no longer available",
    r"call closed", r"currently closed",
]
# real interactive input surface in the rendered DOM
FIELD_PATTERNS = [
    r"<textarea", r"<input\b(?![^>]*type=[\"'](hidden|submit|button|search)[\"'])",
    r"contenteditable=[\"']true[\"']", r"data-qa-input", r"typeform",
    r"role=[\"']textbox[\"']", r"class=[\"'][^\"']*(form-input|field|Field)",
]
SUBMIT_PATTERNS = [r"type=[\"']submit[\"']", r">\s*submit\s*<", r">\s*apply\s*<",
                   r">\s*send\s*<", r">\s*start\s*<", r"data-qa=[\"']start-button"]


def render_dom(url: str, timeout: int = 45) -> str | None:
    """Dump the post-JS rendered DOM via headless Chrome."""
    if not Path(CHROME).exists():
        raise FileNotFoundError(f"Chrome not found at {CHROME}")
    with tempfile.TemporaryDirectory() as prof:
        try:
            out = subprocess.run(
                [CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                 f"--user-data-dir={prof}", "--virtual-time-budget=8000",
                 "--run-all-compositor-stages-before-draw", "--dump-dom", url],
                capture_output=True, text=True, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return None
    return out.stdout or None


def classify(url: str) -> dict:
    dom = render_dom(url)
    if not dom:
        return {"url": url, "verdict": "UNREACHABLE", "evidence": "no DOM rendered (timeout/crash)"}
    low = dom.lower()
    closed_hit = next((p for p in CLOSED_PATTERNS if re.search(p, low)), None)
    has_field = any(re.search(p, dom, re.I) for p in FIELD_PATTERNS)
    has_submit = any(re.search(p, dom, re.I) for p in SUBMIT_PATTERNS)

    if closed_hit:
        # a closed banner is decisive even if skeleton fields exist
        m = re.search(r".{0,40}" + closed_hit + r".{0,40}", low)
        return {"url": url, "verdict": "CLOSED", "evidence": (m.group(0) if m else closed_hit).strip()}
    if has_field and has_submit:
        return {"url": url, "verdict": "LIVE", "evidence": "rendered input fields + submit control present"}
    if has_field:
        return {"url": url, "verdict": "LIVE", "evidence": "rendered input fields present (submit inferred)"}
    return {"url": url, "verdict": "NO_FORM", "evidence": "no interactive input surface in rendered DOM"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--day")
    ap.add_argument("urls", nargs="*")
    args = ap.parse_args()

    if args.urls:
        for u in args.urls:
            r = classify(u)
            print(f"{r['verdict']:11} | {u}\n            {r['evidence']}")
        return 0

    if not args.day:
        print("give --day YYYY-MM-DD or one or more URLs", file=sys.stderr)
        return 2

    import yaml
    from lib import daily
    from lib.config import load_config, resolve
    cfg = load_config()
    path = daily.daily_path(resolve(cfg["state"]["daily_dir"]), args.day)
    data = daily.read_daily(path)
    changed = 0
    for x in data.get("drafts", []):
        u = x.get("pitch_form_url")
        if u in (None, "none", ""):
            continue
        r = classify(u)
        x["pitch_form_liveness"] = r["verdict"]
        x["pitch_form_liveness_evidence"] = r["evidence"]
        # a dead form must not be presented as a usable channel
        if r["verdict"] in ("CLOSED", "NO_FORM", "UNREACHABLE"):
            x["pitch_form_url_dead"] = u
            x["pitch_form_url"] = "none"
        changed += 1
        print(f"{r['verdict']:11} | {x['fund']:26} | {u}\n            {r['evidence']}")
    daily.save_daily(path, data)
    print(f"\nchecked {changed} form(s); daily file updated. Re-render: render_review.py --day {args.day}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
