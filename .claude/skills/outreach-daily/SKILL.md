---
name: outreach-daily
description: Run the VC outreach daily workflow on demand — dequeue the next working-set of eligible funds, fresh apple-to-apple competitor re-verify (drop conflicts, refill to the daily cap), enrich+verify contacts, draft email+subject+LinkedIn-note with the augment-portfolio hook, self-review, and write the day's review file. Same pipeline the 8 AM launchd timer runs. Use when the founder says "prepare N VCs", "run the outreach", "manually prepare the VC list", or "/outreach".
---

# Outreach Daily — manual full-workflow trigger

When the founder asks to prepare the VC list (any of: "prepare 10 VCs", "run outreach",
"manually prepare the list", `/outreach`), run the **entire** daily workflow — identical to the
8 AM automated job — not just a partial step. The founder explicitly wants the full workflow on
a manual trigger.

## Steps

1. **Run prep** (dequeues the working set, fresh conflict re-check + refill, enrich, draft,
   self-review, writes the day's file):
   ```
   scripts/outreach/venv/bin/python scripts/outreach/prep_daily.py --force-weekend
   ```
   - `--n N` if the founder asked for a specific count other than the configured `daily_cap`.
   - `--force-weekend` so a manual run works any day.
   - This is a **headless Claude call** with web access; it does the apple-to-apple competitor
     re-verify per [scripts/outreach/templates/competitor_rubric.md](../../../scripts/outreach/templates/competitor_rubric.md),
     drops funds that now back a true competitor, and refills from the remaining candidates.

2. **Report Stage-0 drops** to the founder from the command output — which funds were dropped
   today for a fresh conflict, the competitor, and the source URL. This is the correctness check
   the founder asked for; surface it, don't bury it.

3. **Gate 1 — paste the prepared list into chat** by running:
   ```
   scripts/outreach/venv/bin/python scripts/outreach/review_and_send.py show
   ```
   Present each fund: contact + verification (email provenance + confidence, LinkedIn + recency),
   today's conflict verdict, subject, email body, and LinkedIn note. Ask the founder which to
   approve (all or a subset).

4. **On approval → create Gmail drafts** (pitch PDF attached):
   ```
   scripts/outreach/venv/bin/python scripts/outreach/review_and_send.py draft --only <subset>
   ```

5. **Gate 2 — after the founder eyeballs the drafts in Gmail and says "go ahead":**
   ```
   scripts/outreach/venv/bin/python scripts/outreach/review_and_send.py send --only <subset>
   scripts/outreach/venv/bin/python scripts/outreach/reconcile.py
   ```
   (Sending respects `config.yaml → send.dry_run`; while true, `send` only reports.)

## Content conventions (enforce on every draft — manual runs and edits alike)
- **Email opener:** always `Hi <FirstName>,` (or `Hi <Firm> team,` if no name).
- **Email sign-off:** always exactly `Shashank Gupta` / `Founder, AegionAI` / `aegionai.ai` on their own lines.
- **LinkedIn note:** **≤ 270 characters** (LinkedIn's hard cap is 300 — stay under for margin; count them),
  and close with a low-key connect line — *"Would like to connect and see if it interests you"* —
  **never** "worth a call?" / "short call?" / "quick call?". A cold invite asks to connect, not to book time.
- **Channel dictates the artifact — do NOT say "pitch attached" on a LinkedIn-only fund.**
  - **Email fund** (has a usable address): the email body references the attached pitch PDF ("pitch attached"), because the send step attaches it.
  - **LinkedIn-only fund** (`email: none`): there is NO email and you CANNOT attach a PDF on LinkedIn. So (a) set `subject`/`body` to `(n/a — LinkedIn-only)` — never generate an email that claims an attachment that can't exist; (b) produce a **`linkedin_subject`** (InMail has a subject field — ≤75 chars, wedge-first, no hype) AND a **`linkedin_message`** (a ~130-180-word pitch to send after connecting / as InMail) that **offers** the deck ("Happy to share our deck") instead of claiming it's attached, and closes "Would like to connect and see if this interests you," signed `— Shashank, Founder, AegionAI`.
  - **Form fund:** the pitch is uploaded/linked in the form, per `pitch_form_answers` — again, no "attached" language in an email that isn't being sent.
- **Personalization:** augment-portfolio angle (name real portfolio cos; a fabricated/wrong-firm name is a fail),
  and for a CAUTION fund name the daylight vs. its adjacent bet.

## Rules
- Never skip the fresh conflict re-check — it's the whole point of the manual trigger too.
- Never send without both gates (chat approval + "go ahead" after Gmail eyeball).
- If prep drops so many funds that fewer than the cap remain, say so; don't pad with conflicted ones.
- If `send_queue.yaml`, `credentials.json`, or `config.sender.address` is missing, tell the founder
  what to set (see [scripts/outreach/README.md](../../../scripts/outreach/README.md)) rather than guessing.
