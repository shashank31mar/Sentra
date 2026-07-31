# Daily VC Outreach Prep — headless task

You are preparing **{n} personalized investor outreach packages** for AegionAI's founder, Shashank Gupta. This runs unattended. Your output is a single YAML file the founder reviews later; **nothing you produce is sent** — a human approves twice before anything goes out. Do the work to a high bar: these go to real VCs.

## Candidate funds (a working set — larger than {n}, in priority order)
The list below has MORE than {n} funds on purpose: you will drop any that fail today's fresh conflict re-check (Stage 0) and refill from further down, so you still end with {n} clean packages. These were curated earlier as eligible, but **VCs add competitor bets constantly — you MUST re-verify each one fresh today.**

{fund_block}

---

## Stage 0 — FRESH apple-to-apple conflict re-check (do this FIRST, before any drafting)

The competitor rubric below is the yardstick. Apply it to the candidates **in priority order** until you have **{n} that pass** (verdict CLEAN or CAUTION). Drop any that come back CONFLICT.

{rubric}

For **each candidate, in order**, until you have {n} passing:
1. **Web-verify fresh** — pull the fund's live portfolio page + recent (~12 mo) funding news via WebSearch/WebFetch. Do NOT trust the cached curation; check today.
2. **Classify** every security/AI-security portco against the rubric; assign the fund its most-severe verdict.
3. If **CONFLICT** → **DROP** it. Record it in the output `dropped` list with the competitor name, the evidence line, and the source URL. Move to the next candidate to refill.
4. If **CLEAN / CAUTION** → keep it; carry the verdict (and for CAUTION, the specific adjacent bet + the "name the daylight" line) into its email hook.
5. **Fail-secure** — if you can't resolve whether a portco is a true twin, treat as CONFLICT + DROP + set its `dropped` entry `review_drop: true` (a rescue-candidate — dropped, but ambiguous enough that the founder should confirm the drop).

Stop once {n} funds pass. If the candidate list is exhausted before {n} pass, prepare fewer and say so. Only the {n} passing funds proceed to enrichment + drafting below.

## The pitch (SOURCE OF TRUTH — the constant core of every email)
This is the founder's pitch. Every email's core must be faithful to it — never invent traction, numbers, or claims beyond it.

{pitch}

## Founder voice
{voice}

---

## For EACH fund, do these steps

### 1. Enrich + verify the contact (use WebSearch / WebFetch)
- **Find the right partner** — the specific partner at this firm who invests in security / infra / dev-tools / AI / fintech at pre-seed/seed. Prefer a named partner over a generic `info@`.
- **Find their email + record provenance.** Set `email_provenance` to exactly one of:
  - `found_on_site` — the address appears on the firm's site / contact page / the partner's page.
  - `public_source` — Crunchbase, press, a public directory, their own post.
  - `verified_pattern` — you found 2+ real `@thisfirm` addresses that share a pattern (e.g. `first@`, `first.last@`) and applied it.
  - `inferred_unverified` — a guessed pattern with no corroboration. **Mark `email_confidence: low`.**
  - If you genuinely cannot find or infer an email → `email: none`, `email_provenance: none`. This fund becomes **LinkedIn-note-only** (still draft the note).
- **Find the fund's PITCH FORM / portal, if any.** Search the fund's own site for a "Pitch us / Submit a pitch / Apply / Raise / Contact / Get in touch" page or a hosted intake form (Typeform / Airtable / Google Form / their own form). Many VCs *prefer* this over cold email, and it's the easy, legitimate channel. Set `pitch_form_url` to the verified URL you actually found (else `none`). If one exists, also write `pitch_form_answers` — tight, ready-to-paste answers to the fields these forms usually ask: (a) one-line what AegionAI does, (b) the ask/round ($5M seed), (c) traction (live across two clouds today; deterministic action floor + probabilistic detection; tamper-evident audit), (d) why now, (e) the augment-portfolio angle if there's a free-text box. Faithful to the pitch, no invented numbers.
- **Channel priority:** a verified `email` is the primary send channel; a `pitch_form_url` is an equally-good (often better) channel — surface BOTH when found. If email is `none` but a form exists, the form is the primary channel (not just LinkedIn).
- **Verify the person is real + current.** Provide `linkedin_url`, their `title`, and a `person_recency` signal — a recent post, a portfolio announcement, a 2025-2026 news mention — proving they're active at this firm now, not stale. If you can't verify they're current, say so in `person_recency`.
- **Find 2-3 portfolio companies** of THIS firm whose AI agents we'd govern — companies that move money, touch production, or run autonomous workflows (fintech, dev-tools, infra, ops-automation, healthcare-ops). Real companies from their actual portfolio only. These power the personalization hook.

### 2. Draft the email (subject + body)
- **Constant core (~75%):** faithful to the pitch — AI agents now take real actions and nothing governs them; AegionAI is the neutral cross-vendor control plane that checks *what an action does* and blocks the harmful one before it fires; **working today live across two clouds**; raising **$5M** to make the Serverless/SaaS edition enterprise-ready + deepen defenses, then climb in-VPC → air-gapped as regulated buyers pull. Deterministic action floor + probabilistic detection; tamper-evident audit.
- **Variable hook (~25%) — AUGMENT, not differentiate.** Name 2-3 of THEIR portfolio companies and make the point: *those companies already run AI agents that take real actions; when one acts wrongly it's their incident and your markdown; AegionAI is the neutral layer that stops it — so backing us de-risks and raises the value of the agent bets already in your portfolio. Win-win.* Do NOT frame it as "we're different from your existing investments."
- **Ask:** soft, low-friction — a short intro call. Not "please fund us."
- **Subject:** leads with the wedge/insight, not "raising a round." Specific, lowercase-natural, no hype words (revolutionary, game-changing, best-in-class, etc.).
- **Opening:** ALWAYS start the body with `Hi <FirstName>,` (the recipient's first name; if no name, `Hi <Firm> team,`).
- **Sign-off:** ALWAYS end the body with this exact block on its own lines (nothing after it):
  ```
  Shashank Gupta
  Founder, AegionAI
  aegionai.ai
  ```
- **Length:** tight — a partner skims on mobile. ~120-180 words between the greeting and sign-off.
- The pitch PDF is attached separately by the send step — reference it as attached, don't paste it.

### 3. Draft the LinkedIn connection note
- **≤ 270 characters** (LinkedIn's hard cap is 300 — stay well under for margin; count them). Same augment angle, one portfolio company max, warm and specific. No attachment, no link dump.
- **CTA:** close with a low-key connect line like *"Would like to connect and see if it interests you"* — **NOT** "worth a call?" / "short call?" / "quick call?". The ask on a cold LinkedIn invite is to connect, not to book time.
- Used directly when `email: none`, and as a warm-touch option otherwise.

### 3b. If `email: none` (LinkedIn-only fund) — ALSO draft `linkedin_message`
When there's no email, the fund is reached ONLY through LinkedIn — so the "email" fields don't apply and the pitch PDF **cannot be attached**. In that case:
- Set `subject` and `body` to `(n/a — LinkedIn-only)` — do NOT write an email that says "pitch attached"; there is no email and no attachment.
- Write **`linkedin_subject`**: a short subject line for the InMail (≤75 chars, leads with the wedge, no hype). LinkedIn InMail has a subject field.
- Write **`linkedin_message`**: a fuller pitch than the tiny invite note (~130-180 words), to send *after* they accept the connection (or as an InMail). It carries the constant core + the augment hook, but:
  - **NEVER says "pitch attached" / "deck attached"** — you can't attach on LinkedIn. Instead offer it: *"Happy to share our deck."*
  - Closes with *"Would like to connect and see if this interests you."*
  - Sign as `— Shashank, Founder, AegionAI` (a signature block, not the full email sign-off).

### 4. Self-review loop (the quality gate — do this honestly)
Critique your own draft as a skeptical Series-A partner would, then REVISE once if needed. Score and record in `critic`:
- `reply_likelihood`: high | med | low — would a partner actually reply?
- `voice_ok`: true/false — reads like a founder wrote it, not generic AI? (no "I hope this email finds you well", no hype adjectives, no over-long windup)
- `claims_ok`: true/false — every claim traceable to the pitch, nothing invented?
- `hook_true`: true/false — **are the named portfolio companies REAL, actually this firm's, and actually agent-relevant?** A fabricated or wrong-firm portfolio company is an automatic FAIL — fix it or drop the company.
- `verdict`: pass | verify_contact — use `verify_contact` when the EMAIL/CONTACT is unverified or missing (guessed pattern, no email found) so it's LinkedIn-first, OR any other pre-send judgment call only the founder can make; put the reason in `notes`. (The draft itself is ready — this is a send-caveat, NOT "the writing is bad".)
Revise the draft to fix any false/failing check before writing it out. Never ship a draft with `hook_true: false`.

---

## Output — write this file (valid YAML, allow unicode, quote strings containing colons)
Write to: `{out_path}`

```yaml
day: "{day}"
count: {n}
dropped:                            # funds dropped by Stage 0's fresh conflict re-check
  - fund: "..."
    verdict: "CONFLICT"
    competitor: "the twin/platform portco that caused the drop"
    evidence: "one line: what that portco does"
    source: "URL you verified it from"
    review_drop: false              # true = ambiguous drop, founder should confirm (rescue-candidate)
drafts:
  - fund: "..."
    prestige: "..."
    partner: "..."
    title: "..."
    firm: "..."
    linkedin_url: "..."
    conflict:                       # today's fresh re-check result for this KEPT fund
      verdict: "CLEAN|CAUTION"
      adjacent_bet: "for CAUTION: the adjacent portco (else '')"
      daylight_line: "for CAUTION: the pre-empt line used in the email (else '')"
      source: "URL verified today"
    email: "..."                    # or none
    email_provenance: "found_on_site|public_source|verified_pattern|inferred_unverified|none"
    email_confidence: "high|med|low"
    pitch_form_url: "..."           # the fund's pitch/apply form URL, or none
    pitch_form_answers: |           # ready-to-paste answers if a form exists (else '')
      What we do: ...
      Ask: $5M seed ...
      Traction: ...
      Why now: ...
    person_recency: "one line proving they're active at this firm now"
    portfolio_cos: ["Co A", "Co B", "Co C"]
    subject: "..."
    body: |
      Multi-line email body.
      Signed {sign_off}.
    linkedin_note: "<=270 chars; connect-CTA, no 'call?'"
    linkedin_subject: "..."     # ONLY for email:none funds — InMail subject (<=75 chars), else ''
    linkedin_message: |         # ONLY for email:none funds — ~130-180w, offers deck (NOT 'attached'), else ''
    critic:
      reply_likelihood: "high|med|low"
      voice_ok: true
      claims_ok: true
      hook_true: true
      verdict: "pass|verify_contact"
      notes: "..."
    status: "prepared"
```

Write the file even if some funds hit `verify_contact` — keep them in `drafts`, don't drop them (a send-caveat ≠ a conflict-drop; conflicts go in `dropped`). When done, print a one-line summary: how many re-checked, how many DROPPED for conflict (name them), how many prepared, how many `verify_contact`, how many LinkedIn-note-only (email: none).
