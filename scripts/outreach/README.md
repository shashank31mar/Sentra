# VC Outreach Automation

Daily loop that preps 10 personalized, self-reviewed investor emails + LinkedIn notes,
surfaces them for a two-gate human review, and sends from your Gmail with the pitch PDF attached.

Full design: [../../docs/outreach-automation.md](../../docs/outreach-automation.md).

## The flow

```
8 AM (launchd, unattended)   prep_daily.py → headless Claude → state/daily/<date>.yaml
                                    (find 10 → enrich+verify → draft → self-review)
   │
   ▼  (you sit down)
GATE 1   review_and_send.py show          → you approve a subset (in chat or CLI)
   ▼
         review_and_send.py draft --only … → creates Gmail drafts (pitch PDF attached)
   ▼
GATE 2   (eyeball drafts in Gmail)         → you say "go ahead"
   ▼
         review_and_send.py send  --only … → batch-sends (throttled; respects dry_run)
   ▼
         reconcile.py                       → mirrors sends into outreach-tracker.md
```

## One-time setup

1. **Python deps** (already done if the venv exists):
   ```
   cd scripts/outreach && python3 -m venv venv && ./venv/bin/pip install -r requirements.txt
   ```
2. **Gmail OAuth** (only you can do this — your Google account). See design doc §6:
   - Google Cloud Console → new project → enable **Gmail API**.
   - **OAuth client ID**, type **Desktop app**, Testing mode, your address as a test user.
   - Download → save as `scripts/outreach/credentials.json`.
   - `./venv/bin/python setup_gmail_oauth.py` → approve in browser → `token.json` cached.
3. **Set your address** in `config.yaml` → `sender.address`.
4. **Approve the queue** — review `send_queue.yaml` (the curated eligible fund list).
5. *(Recommended)* **Voice profile** — run the `brand-voice` skill on 2-3 emails you've sent;
   save the profile to `templates/voice_profile.md` so drafts match your voice.
6. **Install the timer** (optional — you can also just run `prep_daily.py` by hand):
   ```
   cp ai.aegion.outreach-prep.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/ai.aegion.outreach-prep.plist
   ```

## Safety

- `config.yaml → send.dry_run: true` by default — `send` creates nothing live until you flip it.
- ≤ `daily_cap` (10) sends/weekday; throttled; weekends off.
- **Two human gates** — nothing sends without your chat approval *and* your "go ahead" after eyeballing Gmail.
- **Fail-secure eligibility** — the queue excludes competitor-backers and already-contacted funds; ambiguous → excluded.
- Secrets + PII (`credentials.json`, `token.json`, `state/`) are gitignored.

## Files

| File | Role |
|---|---|
| `send_queue.yaml` | curated eligible funds (Layer 0, you approve once) |
| `config.yaml` | throttle, dry_run, sender, scopes, paths |
| `prep_daily.py` | 8 AM: dequeue 10 → headless prep → daily file |
| `review_and_send.py` | `show` / `draft` / `send` — the two gates |
| `reconcile.py` | mirror sends into the tracker; list LinkedIn-only funds |
| `setup_gmail_oauth.py` | one-time authorize |
| `lib/` | config · queue · gmail · daily |
| `templates/prep_prompt.md` | the prep instructions (augment-portfolio + self-review) |
| `run_prep.sh` + `*.plist` | launchd wrapper + weekday-8AM timer |
| `tests/` | queue-logic tests (`./venv/bin/python -m pytest tests/`) |

## Tests

```
cd scripts/outreach && ./venv/bin/python -m pytest tests/ -v
```
