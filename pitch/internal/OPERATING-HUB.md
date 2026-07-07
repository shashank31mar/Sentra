# AegionAI — Operating Hub

**The ONE live doc. Update this weekly; everything else is reference.**
**Last updated:** 2026-07-07 · **Owner:** Shashank (founder)

> Why this exists: there are ~29 pitch docs and they drift. This is the single place that answers "what stage am I in, what am I doing this week, and where does the real info live." If a fact here disagrees with a reference doc, **fix the reference doc.** Canonical facts live in [../share/STRATEGY.md](../share/STRATEGY.md) + [../share/AegionAI-pitch.md](../share/AegionAI-pitch.md) — never restate numbers here, link to them.

---

## 0. What stage am I actually in? (the honest read)

**Idea-stage company with a Launch-stage product.** Per Anthropic's Founder's Playbook, the gate you must pass next is **problem-solution fit from real customer conversations** — and you are at **zero completed design-partner conversations** ([outreach-tracker.md](outreach-tracker.md)). The product is real and deployed (~26K LOC, 20 validators, live demo) but it validates that *the code works*, not that *the market wants it*.

**Therefore the prime directive is: buy validation, not code.** Freeze net-new product features. Every founder-hour goes to conversations (CTO + design partners) until real signal tells you what to build next.

**The two-person split (correct, keep it):**
- **You (Shashank):** security CTO / co-founder hunt. This unblocks the *regulated/bank* segment — your biggest checks ([AegionAI-pitch.md:71](../share/AegionAI-pitch.md#L71): "this round funds that hire as the first priority").
- **Partner:** investors + design partners.

**The three numbers that define the next 90 days** (nothing else is progress):
1. **# real design-partner conversations** (target: 15–20 to find 3 partners)
2. **# CTO candidates in a live paid-trial or serious conversation** (target: 1 signed trial)
3. **# investor conversations that produced a next step or a warm intro** (partner-owned)

---

## 1. This week's plan — week-on-week

> Fill the top block every Monday. Keep the last ~4 weeks below it as a log. **3 goals max per person per week** — if everything is a priority, nothing is.

### Week of 2026-07-07  ← CURRENT

**Founder (Shashank) — CTO hunt:**
- [ ] Source 10 named detection/appsec candidates via the GitHub→LinkedIn crosswalk ([cofounder-search.md §3](../../cofounder-search.md)). Log each in the CTO tracker (§3 below) with a **proof-URL**, not a resume.
- [ ] Verify credentials at primary source (NVD/contributor-graph/CFP) for the top 5.
- [ ] Send 5 personalized cold emails using [cofounder-outreach-drafts.md](cofounder-outreach-drafts.md) — line 1 references a specific PR/CVE/talk of theirs.

**Partner — investors + design partners:**
- [ ] Move the 6 design-partner prospects off "Sent (LinkedIn)": chase warm intros (IIT / Rutvik / Randy networks), aim for 2 calls booked.
- [ ] Lock Zafar's 3rd-week-July date + respond to his marketing-team intro (clarify: diligence or GTM help?).
- [ ] Randy — schedule the call; come with a forwardable blurb + ask for 3 named investor intros.

**Shared / async:**
- [ ] Add the "few updates not yet added" into the trackers (§2, §3) — 20 min, don't let them rot.

**Blockers / decisions needed:** _[none logged]_

---

### Week log (most recent first)

**Week of 2026-06-30** — _backfill if useful._
**Week of 2026-06-23** — first design-partner outbound sent (6 LinkedIn InMails); Swiggy replied then went cold; Rutvik intro call scheduled.

---

## 2. Design-partner + investor tracker → [outreach-tracker.md](outreach-tracker.md)

**Single source for the DP/investor pipeline.** Keep the state legend it already has (`Not contacted → Sent → Responded → Call scheduled → Call done → Pilot`). **This week's numbers** (update Mondays):
- Design partners: **6 contacted · 0 calls done · 0 pilots**
- Investors: 3 warm/engaged (Rutvik, Randy, Zafar) · Jyoti (Harness/Unusual) not yet contacted

- Investors/connectors: **Randy (bought in, now delivering intros) → Jeff (met, liked it, back in ~1wk) + Paul (call done — proposed a GPCN compute+channel deal: ~$1k/mo, he intros us to customers across ~30K agents on his platform + funding connects)** — one Charlotte/GPCN/COO-Forum operator cluster, treat as angels/connectors not VCs. Plus Rutvik, Zafar; Jyoti not yet contacted.
  - ⚠️ **Paul/GPCN deal — before signing:** confirm the 30K agents take real actions + are introducible; deploy PARALLEL (don't re-platform off AWS); check for finder's-fee/equity/exclusivity (esp. "funding help"); clean no-auto-renew exit; get intro+funding commitment in writing. Reframe spend as dogfooding the in-VPC edition. (Detail in [outreach-tracker.md](outreach-tracker.md) #12.)
- Design partners: **Parminder (GE HealthCare, warm) responded — connecting this week.**

**Rule:** a prospect that's been "Sent (LinkedIn)" >10 days with no reply gets a warm-intro attempt or a break-up note — no silent stalls. **When a connector delivers (Randy did), immediately ask for the *next* 2–3 names — a warm network compounds only if you keep pulling.**

---

## 3. Co-founder & CTO tracker (security background)  ← NEW, keep it here

Derive the pipeline from **proof-URLs, not resumes** ([cofounder-search.md §3](../../cofounder-search.md)). One row per person.

| # | Name | Archetype | Proof-URL (CVE/PR/talk) | Geo | FT-likely? | Channel | State | Next step |
|---|------|-----------|-------------------------|-----|-----------|---------|-------|-----------|
| _e.g._ | _—_ | detection eng | _github.com/.../pull/123_ | India | ? | warm intro | Not contacted | verify creds |

State legend: `Sourced → Verified → Contacted → Replied → Call done → Paid trial → Offer → Signed` · `No response` · `Passed`

**Vetting gate before you spend a conversation:** credential verified at primary source; scores on the [rubric](../../cofounder-search.md#4-credential-validation-rubric); no anti-signals (leads with "we block inline" = pass). **Trial before equity, always.**

**Security ADVISOR on board (2026-07-07):** **Shikhar Jain** — Engineering Lead @ LinkedIn; led security posture for $6B-revenue AWS services (OpenSearch, CloudWatch). Consent given to be named in investor materials (asked him to update LinkedIn to match). **Advisor only at this stage** — comp in discussion, kept OUT of investor docs. Does NOT replace the co-founder search; keep distinct from Randy (investor/connector). Founder's private aim = convert to co-founder over time, but never framed that way externally.

---

## 4. Where everything lives (so you stop hunting)

**🟢 CANONICAL — source of truth, keep current:**
| Doc | What it owns |
|---|---|
| [../share/STRATEGY.md](../share/STRATEGY.md) | Market, beachhead, moat, GTM ladder, the $5M ask |
| [../share/AegionAI-pitch.md](../share/AegionAI-pitch.md) | The investor one-pager (share this, not any other) |
| [../share/architecture-brief.md](../share/architecture-brief.md) | Live-vs-roadmap capability table |
| [../../PRD.md](../../PRD.md) · [../../vision.md](../../vision.md) | Requirements · vision |
| [OPERATING-HUB.md](OPERATING-HUB.md) | ← this doc: stage, weekly plan, trackers |

**🟡 ACTIVE WORKING DOCS:**
| Doc | Use for |
|---|---|
| [outreach-tracker.md](outreach-tracker.md) | DP + investor pipeline |
| [cofounder-search.md](../../cofounder-search.md) + [cofounder-outreach-drafts.md](cofounder-outreach-drafts.md) | CTO hunt: profile/pools/search-strings + email drafts |
| [design-partner-playbook.md](design-partner-playbook.md) | How to run a DP conversation + the $5K offer |
| [pitch-narrative.md](pitch-narrative.md) · [pitches-by-audience.md](pitches-by-audience.md) | Spoken pitch scripts (rollback = roadmap; use share one-pager) |
| [investor-qa-objection-handling.md](investor-qa-objection-handling.md) | Objection backups |
| [prospect-list.md](prospect-list.md) · [vc-list.md](vc-list.md) · [angel-list.md](angel-list.md) | Target research |
| [rutvik-call-prep.md](rutvik-call-prep.md) | Per-meeting prep (make one per important call) |
| [pricing-model.md](pricing-model.md) | Per-agent tiers |

**🔴 STALE / ARCHIVE — do not source from these:**
| Doc | Why | Action |
|---|---|---|
| [../customer/5-year-roadmap.md](../customer/5-year-roadmap.md) (Mar '26) | Contradicts STRATEGY on beachhead/tech/raise/name | **Delete or fully rewrite — never send** |
| [pitches-by-audience.md §4](pitches-by-audience.md) | Old inline one-pager — now a pointer to share doc ✅ fixed | done |
| [../archive/*](../archive/) | Prior pitch/synopsis versions | leave archived |
| [b2c-target-customers.md](b2c-target-customers.md) (Jan '26) | B2C refund-fraud beachhead — retired direction | archive mentally; don't cite |

---

## 5. Weekly ritual (10 minutes, every Monday)
1. Move last week's plan (§1) into the Week Log; write this week's ≤3 goals per person.
2. Update the pipeline numbers in §2 and the CTO tracker in §3.
3. Add any "updates not yet added" — don't let signal rot in your head.
4. Check: did I ship more *code* than *conversations* last week? If yes, correct course.
5. One-line honest note: are we closer to problem-solution fit than 7 days ago?
