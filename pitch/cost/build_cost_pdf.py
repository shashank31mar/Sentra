#!/usr/bin/env python3
"""Emit a print-ready markdown of the AegionAI $5M cost model with COMPUTED values.

The .xlsx stores formulas (Excel/Numbers recalc on open); this doc bakes in the
same values, computed in Python, so the PDF shows real numbers and tables render.
Kept in sync with build_cost_model.py — same inputs, same logic.

Every line carries a "How derived" note so each number is auditable.
Base scenario = India team + full GTM programs + 30% buffer, with the US enterprise
AE DEFERRED (founder-led sales first) to keep the base runway long.

Writes pitch/cost/AegionAI-Cost-Model.md  ->  render with scripts/md_to_pdf.py
"""
import os

FX = 90
RAISE = 5_000_000
LOAD = 0.15            # India employer statutory + benefits load
BUFFER = 0.30          # contingency buffer on recurring burn
TARGET = 40            # runway floor (months)

def usd(x):   return "$%s" % format(int(round(x)), ",")
def inr(x):   return "₹%s" % format(int(round(x)), ",")
def pct(x):   return "%.1f%%" % (x * 100)

# ---------------- Team ----------------
# (role, location, function, base_inr, base_usd, derivation, note, in_base_burn)
TEAM = [
    ("Founder / CEO", "India", "Leadership", 8_500_000, None, "₹85L ÷ 90", "Base only; equity-heavy", True),
    ("Security CTO", "India", "Leadership / Security", 8_500_000, None, "₹85L ÷ 90 (= CEO for now)", "Same base as CEO to conserve cash; equity-weighted; bank-facing hire", True),
    ("Sr Engineer (SDE3)", "India", "Backend + Security", 8_000_000, None, "₹80L ÷ 90", "Detection pipeline, policy engine, in-VPC", True),
    ("ML Engineer", "India", "ML / Detection", 6_000_000, None, "₹60L ÷ 90", "Distilled classifier, shadow→enforce", True),
    ("Engineer (SDE2)", "India", "Backend", 5_000_000, None, "₹50L ÷ 90", "Control-plane / connectors", True),
    ("Engineer (SDE2)", "India", "Frontend", 5_000_000, None, "₹50L ÷ 90", "Console / dashboard (React)", True),
    ("Engineer (SDE2)", "India", "Platform", 5_000_000, None, "₹50L ÷ 90", "SDK, infra, CDK", True),
    ("Product Manager", "India", "Product", 7_000_000, None, "₹70L ÷ 90", "Roadmap, design-partner delivery", True),
    ("Enterprise AE (DEFERRED)", "US", "Go-to-market", None, 300_000, "$140K base + $135K commission (OTE ~$275K) × 1.15 burden", "Hired ~mo 12–18; founder-led sales first. NOT in base burn.", False),
]
india_base = sum(r[3] / FX for r in TEAM if r[3] is not None and r[7])
india_loaded = india_base * (1 + LOAD)
ae = sum(r[4] for r in TEAM if r[4] is not None)   # deferred
base_payroll = india_loaded                         # base burn = India team only
headcount = len(TEAM)

# ---------------- Operating buckets ----------------
# each: (item, annual_usd, one_time_bool, derivation, note)
BUCKETS = {
"2 · Physical Infrastructure & Facilities": [
    ("Office rent — Bangalore", 33_333, False, "₹2.5L/mo × 12 ÷ 90", "Base sheet"),
    ("Laptops — MacBook Pro × 10", 27_800, True, "₹25L ÷ 90", "3-yr refresh"),
    ("Mac Studio × 1 (ML/dev)", 4_400, True, "₹4L ÷ 90", "One-time"),
    ("Office deposit + setup", 11_100, True, "₹10L ÷ 90", "Refundable deposit + fit-out"),
],
"3 · AI Coding Tools (Claude Code)": [
    ("Claude Code — Team plan (8 × $150/seat)", 14_400, False, "8 seats × $150/seat/mo × 12", "Anthropic Team plan (premium seat, annual): Claude Code + org SSO / central billing / admin; cheaper than 8 individual Max subscriptions"),
],
"4 · Cloud / AWS Infrastructure": [
    ("Bedrock foundation-model inference", 30_000, False, "~$2.5K/mo × 12 (real run-rate)", "Dominant lever; declines as distilled sidecar absorbs ALLOWs"),
    ("Distilled classifier — CPU Fargate (HA)", 1_740, False, "~$145/mo × 12", "2 HA tasks; 5× cheaper than always-on GPU"),
    ("GPU retraining (amortized)", 1_440, False, "~$120/mo × 12", "Rent g5/p4 for periodic distillation runs only"),
    ("Platform (ECS+DynamoDB+S3+CW+API GW+ALB+NAT)", 14_520, False, "~$1,210/mo × 12 (real run-rate)", "Core production platform"),
    ("Legacy tail (OpenSearch/SageMaker/EC2) → $0", 18_000, False, "~$1.5K/mo × 12, decaying", "Winding down; not part of clean target"),
],
"5 · GTM Programs (non-payroll)": [
    ("Events & conferences (RSA + meetups)", 42_000, False, "RSA booth+passes + meetups, annual", "Excl. BLR→US travel (separate line)"),
    ("Founder US travel (sell-in-US)", 26_400, False, "5–6 trips/yr SF/NYC × ~$4.4K/trip", "GSA per-diem basis"),
    ("Content / website / demand-gen", 18_000, False, "~$1.5K/mo × 12", "Seed-stage light demand-gen"),
    ("CRM + sales tooling (HubSpot)", 8_400, False, "~$700/mo × 12", "HubSpot Sales + tooling"),
    ("HubSpot Pro onboarding", 1_500, True, "one-time fee", "One-time"),
    ("Design-partner program (mostly non-cash)", 6_000, False, "~$500/mo × 12", "Credits/support for observe-only partners"),
],
"6 · Operations & G&A (US C-corp + India Pvt Ltd)": [
    ("Legal — ongoing (MSAs/DPAs/IP)", 36_000, False, "~$3K/mo × 12", "Bank MSA/DPA load"),
    ("Accounting / bookkeeping (US + India)", 10_200, False, "~$850/mo × 12", "Kruze benchmark"),
    ("Payroll + tax filings (US + India)", 4_200, False, "~$350/mo × 12", "Amortized"),
    ("Insurance — D&O", 4_800, False, "~$400/mo × 12", "<$10M funding band"),
    ("Insurance — Tech E&O + Cyber + GL", 5_200, False, "~$430/mo × 12", "Banks demand $2–5M limits"),
    ("Business SaaS stack", 6_480, False, "~$60/head × 9 heads × 12", "Google WS, Slack, Notion, GitHub, 1Password, Zoom"),
    ("US C-corp + India Pvt Ltd ongoing compliance", 2_400, False, "~$200/mo × 12", "DE franchise/agent + India ROC/MCA/audit"),
    ("Banking / cross-border FX", 2_400, False, "~$200/mo × 12", "Wise/wires"),
    ("Entity formation (US + India)", 500, True, "one-time filings", "One-time"),
    ("Seed-financing legal + first patent", 27_000, True, "round docs ~$20–40K + patent ~$10–15K", "One-time Yr-1"),
],
"7 · Compliance & Certifications": [
    ("SOC 2 automation platform (Vanta/Drata)", 12_000, False, "~$1K/mo × 12", "Annual subscription"),
    ("SOC 2 Type II auditor (annual)", 18_000, False, "annual audit fee", "Recurring"),
    ("Third-party pen test (annual)", 12_000, False, "annual pen test", "Banks demand current report"),
    ("SOC 2 Type I auditor (interim)", 10_000, True, "one-time Yr-1 interim", "Unblocks early deals"),
    ("SOC 2 readiness / gap + policy dev", 8_000, True, "one-time Yr-1", "Gap assessment + policies"),
    ("GDPR — fractional DPO + tooling (conditional)", 32_400, False, "~$2.7K/mo × 12", "Gate until EU customers exist"),
],
}

def bucket_recurring(name): return sum(v for _, v, ot, _, _ in BUCKETS[name] if not ot)
def bucket_onetime(name):   return sum(v for _, v, ot, _, _ in BUCKETS[name] if ot)

phys = bucket_recurring("2 · Physical Infrastructure & Facilities")
claude = bucket_recurring("3 · AI Coding Tools (Claude Code)")
aws = bucket_recurring("4 · Cloud / AWS Infrastructure")
gtm = bucket_recurring("5 · GTM Programs (non-payroll)")
ops = bucket_recurring("6 · Operations & G&A (US C-corp + India Pvt Ltd)")
comp = bucket_recurring("7 · Compliance & Certifications")

buckets_subtotal = base_payroll + phys + claude + aws + gtm + ops + comp
buffer_amt = buckets_subtotal * BUFFER
recurring_total = buckets_subtotal + buffer_amt
onetime_total = sum(bucket_onetime(b) for b in BUCKETS)
runway = (RAISE - onetime_total) / recurring_total * 12

# scenarios (all carry the buffer)
ae_scn = recurring_total + ae * (1 + BUFFER)                       # + US AE full year
lean = (buckets_subtotal - 40_000 - 24_000) * (1 + BUFFER)         # trim cloud legacy + GTM
high = recurring_total + (ae + 120_000) * (1 + BUFFER)             # AE + fractional VP
ae_rw = (RAISE - onetime_total) / ae_scn * 12
lean_rw = (RAISE - onetime_total) / lean * 12
high_rw = (RAISE - onetime_total) / high * 12

# --- Phased hiring scenario ---
# Start team = CEO + Security CTO + SDE3 + 2×SDE2 + ML (6 India heads, 6 Claude seats).
# "Rest later" = 3rd SDE2 + PM (India), plus the US AE (deferred further).
SDE2_loaded = 5_000_000 / FX * (1 + LOAD)
PM_loaded = 7_000_000 / FX * (1 + LOAD)
start_india = india_loaded - SDE2_loaded - PM_loaded              # drop 3rd SDE2 + PM to start
start_claude = 6 * 150 * 12                                       # 6 Team seats instead of 8
start_sub = buckets_subtotal - (india_loaded - start_india) - (claude - start_claude)
start_burn_mo = start_sub * (1 + BUFFER) / 12
full_burn_mo = recurring_total / 12
LEAN_MONTHS = 9                                                   # months on the starting team
cash = RAISE - onetime_total
phased_runway = LEAN_MONTHS + (cash - start_burn_mo * LEAN_MONTHS) / full_burn_mo
start_hold_runway = cash / (start_sub * (1 + BUFFER)) * 12        # if never scaled up

# use of funds over base runway (base = no AE)
def over(annual): return annual * runway / 12
uof = [
    ("Team — eng + product + leadership (India)", india_loaded),
    ("GTM — programs only, founder-led sales (AE deferred)", gtm),
    ("Cloud / AWS + AI coding tools", aws + claude),
    ("Physical infra & facilities", phys),
    ("Operations & G&A", ops),
    ("Compliance & certifications", comp),
]

# ---------------- emit markdown ----------------
L = []
def w(s=""): L.append(s)

w("# AegionAI — Seed Cost Model & Runway")
w()
w("### *$5M raise · build-in-India / sell-in-US*")
w()
w("> **All figures are planning estimates and assumptions — speculative, not commitments.** They are "
  "built from sourced benchmarks and this account's real AWS run-rate, but actual costs will change with "
  "hiring pace, FX, AWS usage, deal activity, and market rates. Treat this as a directional model to be "
  "revised as reality lands, not a fixed budget.")
w()
w("*Assumptions: FX ₹%d/USD · India employer load %d%% · %d%% contingency buffer on recurring burn · "
  "US enterprise Account Executive (AE) deferred in the base case (founder-led sales first ~12–18 months).*" % (FX, int(LOAD*100), int(BUFFER*100)))
w()
w("---")
w()
w("## Headline (Base scenario)")
w()
w("| Metric | Value | How derived |")
w("|---|---:|---|")
w("| Total raise | **%s** | Seed round |" % usd(RAISE))
w("| Recurring burn / year | **%s** | buckets subtotal %s + %d%% buffer %s |" % (usd(recurring_total), usd(buckets_subtotal), int(BUFFER*100), usd(buffer_amt)))
w("| Recurring burn / month | **%s** | annual ÷ 12 |" % usd(recurring_total/12))
w("| One-time costs | **%s** | laptops + deposits + SOC2 T1 + seed legal/patent + formation |" % usd(onetime_total))
w("| **Base runway (months)** | **%.1f** | (%s − %s one-time) ÷ %s/yr × 12 |" % (runway, usd(RAISE), usd(onetime_total), usd(recurring_total)))
w("| Headcount (India base) | %d | + US AE when hired = %d |" % (headcount-1, headcount))
w()
w("## Use of Funds — where the $5M goes")
w()
w("Share of the raise over the %.0f-month base runway (US AE deferred)." % runway)
w()
w("| Bucket | Annual | Over runway | % of $5M |")
w("|---|---:|---:|---:|")
tot_over = 0
for name, annual in uof:
    o = over(annual); tot_over += o
    w("| %s | %s | %s | **%s** |" % (name, usd(annual), usd(o), pct(o/RAISE)))
o_buf = over(buffer_amt); tot_over += o_buf
w("| Contingency buffer (%d%%) | %s | %s | **%s** |" % (int(BUFFER*100), usd(buffer_amt), usd(o_buf), pct(o_buf/RAISE)))
w("| **Total** | | **%s** | **%s** |" % (usd(tot_over), pct(tot_over/RAISE)))
w()
gtm_incl_ae_annual = gtm + ae * (1 + BUFFER)
gtm_incl_ae_over = gtm_incl_ae_annual * ae_rw / 12
w("*Memo (not summed into Total above): if the US enterprise AE is hired full-year, GTM (programs + AE, loaded) "
  "≈ **%s** of $5M and runway drops to **%.1f months** — see the \"+ US AE\" scenario below.*" % (pct(gtm_incl_ae_over/RAISE), ae_rw))
w()
w("> **Note:** **Team ≈ %s of spend**; real **cloud/infra is only ~%s** (not a "
  "red flag — the distilled model self-hosts on CPU, so no ~$1M GPU line is needed). **GTM here (%s) is "
  "programs-only** — founder-led sales, AE deferred; see the memo above for the ~%s figure once the AE is hired." %
  (pct(over(india_loaded)/RAISE), pct(over(aws+claude)/RAISE), pct(over(gtm)/RAISE), pct(gtm_incl_ae_over/RAISE)))
w()
w("## Team & Compensation")
w()
w("Per-role salaries. India comp shown INR→USD at ₹%d, then + %d%% employer load. The US enterprise seller "
  "is priced in USD (cannot be India-priced) and is **deferred** in the base case." % (FX, int(LOAD*100)))
w()
w("Hiring phase: **Start** = day one · **Scale** ≈ mo %d · **Sell** ≈ mo 12–18." % LEAN_MONTHS)
w()
w("| Role | Hire | Loc | Base (INR/yr) | Base (USD/yr) | How derived |")
w("|---|---|---|---:|---:|---|")
PHASE = {  # role index -> phase label
    0: "Start", 1: "Start", 2: "Start", 3: "Start", 4: "Start", 5: "Start",
    6: "Scale", 7: "Scale", 8: "Sell",
}
# roles: 0 CEO,1 CTO,2 SDE3,3 ML,4 SDE2,5 SDE2,6 SDE2(3rd),7 PM,8 AE
for i, (role, loc, func, bi, bu, deriv, note, in_base) in enumerate(TEAM):
    ph = PHASE.get(i, "Start")
    if bi is not None:
        w("| %s | %s | %s | %s | %s | %s |" % (role, ph, loc, inr(bi), usd(bi/FX), deriv))
    else:
        w("| *%s* | %s | %s | — | *%s* | %s |" % (role, ph, loc, usd(bu), deriv))
w("| **India base payroll** | | | | **%s** | sum of 8 India roles |" % usd(india_base))
w("| + India employer load (%d%%) | | | | **%s** | %s × %.2f |" % (int(LOAD*100), india_base*LOAD, usd(india_base), LOAD))
w("| **BASE PAYROLL (loaded, India)** | | | | **%s** | flows to runway; %s/mo |" % (usd(base_payroll), usd(base_payroll/12)))
w("| *US seller (deferred, loaded)* | | | | *%s* | added when hired (see scenarios) |" % usd(ae))
w()
w("## Operating Costs — by bucket (annual)")
w()
w("Bucket 1 is payroll (above). Buckets 2–7 below; *(one-time)* rows are excluded from the recurring subtotal and sit in one-time costs instead.")
w()
w("**1 · Team & Compensation** — recurring **%s/yr** (%s/mo). India team; see table above." % (usd(base_payroll), usd(base_payroll/12)))
w()
for name in BUCKETS:
    rec = bucket_recurring(name); ot = bucket_onetime(name)
    w("**%s** — recurring **%s/yr**%s" % (name, usd(rec), ("  ·  one-time %s" % usd(ot)) if ot else ""))
    w()
    w("| Line item | Annual | Type | How derived | Note |")
    w("|---|---:|:--:|---|---|")
    for item, val, is_ot, deriv, note in BUCKETS[name]:
        w("| %s | %s | %s | %s | %s |" % (item, usd(val), "one-time" if is_ot else "recurring", deriv, note))
    w()
w("## Runway & Scenarios")
w()
w("Runway = (Raise − one-time) ÷ annual recurring burn × 12. All scenarios include the %d%% buffer." % int(BUFFER*100))
w()
w("| Scenario | Annual burn | Runway (mo) | How derived |")
w("|---|---:|---:|---|")
w("| **Phased hiring** (recommended) | ramps | **%.1f** | start 6 heads %s/mo for %d mo, then full team |" % (phased_runway, usd(start_burn_mo), LEAN_MONTHS))
w("| Base (full India team day 1, founder-led sales) | %s | %.1f | buckets + buffer, US AE deferred |" % (usd(recurring_total), runway))
w("| + US enterprise AE (full year) | %s | %.1f | base + AE %s × 1.30 |" % (usd(ae_scn), ae_rw, usd(ae)))
w("| Lean (trim AWS legacy + GTM) | %s | %.1f | base − ~$64K, + buffer |" % (usd(lean), lean_rw))
w("| High (AE + fractional VP + high cloud) | %s | %.1f | base + (AE + $120K VP) × 1.30 |" % (usd(high), high_rw))
w()
w("**Phased hiring plan (recommended):**")
w()
w("| Phase | When | Team | Adds |")
w("|---|---|---|---|")
w("| Start | mo 0 | CEO + **Security CTO** + SDE3 + 2× SDE2 + ML (6 India) | Founder owns product & sales |")
w("| Scale | ~mo %d | + 3rd SDE2 + **Product Manager** | PM once design-partner delivery outgrows founder |" % LEAN_MONTHS)
w("| Sell | ~mo 12–18 | + US enterprise AE | Once founder-led sales prove a repeatable motion |")
w()
w("*The starting 6-head team burns only ~%s/mo — if never scaled it would run %.0f months. Phasing the last "
  "India hires in at ~mo %d lands ~%.0f months total. Adding the US AE full-time from day one is what drops "
  "the plan to %.0f months, so that hire waits for traction.*" % (
  usd(start_burn_mo), start_hold_runway, LEAN_MONTHS, phased_runway, ae_rw))
w()
w("## Sources")
w()
w("Every external unit cost traces to a source (accessed 2026-07-23). AWS figures are grounded in this "
  "account's real run-rate (~$6–14K/mo, Apr–Jun 2026). **These remain estimates and will change.**")
w()
w("| Bucket | Figure | Source |")
w("|---|---|---|")
SOURCES = [
 ("Claude Code","Max 20x $200 / Max 5x $100; blend $150/seat","[claude.com/pricing](https://claude.com/pricing)"),
 ("Claude Code","PAYG ~$13/dev/active-day; $150–250/dev/mo","[Anthropic Claude Code costs](https://code.claude.com/docs/en/costs)"),
 ("AWS — Bedrock","Haiku $1/$5, Sonnet $3/$15 per MTok","[Anthropic/Bedrock pricing](https://platform.claude.com/docs/en/about-claude/pricing)"),
 ("AWS — Fargate","CPU serving ~$145/mo","[AWS Fargate pricing](https://aws.amazon.com/fargate/pricing/)"),
 ("AWS — GPU","g5.xlarge $1.006/hr; retraining ~$120/mo","[Vantage EC2](https://instances.vantage.sh/aws/ec2/g5.xlarge)"),
 ("AWS — real run-rate","~$6–14K/mo actual (Apr–Jun 2026)","AWS Cost Explorer, acct 531109575379"),
 ("GTM — US AE","base ~$140K / OTE ~$275K; loaded ~$312K","[RepVue enterprise-AE](https://www.repvue.com/salaries/enterprise-account-executive)"),
 ("GTM — events","RSA passes/booth","[Lensmor RSAC 2026](https://www.lensmor.com/event-guides/rsa-conference-2026-attendee-guide)"),
 ("GTM — travel","GSA per-diem; SF/NYC lodging","[GSA per-diem](https://www.gsa.gov/travel/plan-book/per-diem-rates)"),
 ("GTM — CRM","HubSpot Starter/Pro + onboarding","[HubSpot pricing](https://www.hubspot.com/pricing/sales)"),
 ("Compliance — SOC 2","Type I ~$10K, Type II ~$18K/yr, readiness ~$8K","[Drata SOC 2 cost](https://drata.com/learn/soc-2/cost)"),
 ("Compliance — platform","Vanta/Drata ~$12K/yr","[RiskPublishing SOC 2](https://riskpublishing.com/soc-2-audit-cost-complete-pricing-breakdown/)"),
 ("Compliance — GDPR DPO","fractional DPO ~$2.2K/mo","[EngageCompliance](https://engagecompliance.co/fractional-dpo-pricing-benchmark-2026)"),
 ("Ops — legal","seed ~$3K/mo; round+patent ~$27K one-time","[Arceus startup legal](https://arceus.legal/blog/how-much-should-legal-cost-startup-by-stage)"),
 ("Ops — accounting","~$850/mo bookkeeping","[Kruze pricing](https://kruzeconsulting.com/pricing/)"),
 ("Ops — insurance","D&O $3.5–6K/yr; E&O+cyber+GL","[Embroker D&O](https://www.embroker.com/blog/directors-and-officers-insurance-cost/)"),
 ("Ops — India entity","Pvt Ltd ROC/MCA ₹40K–1.5L/yr","[Incorpx](https://incorpx.io/blog/annual-compliance-cost-startups-2026)"),
 ("Ops — US entity","DE franchise/agent + CA $800","[Delaware Div. of Corp.](https://corp.delaware.gov/paytaxes/)"),
 ("Ops — SaaS","~$60/head","[Google Workspace](https://workspace.google.com/pricing)"),
 ("Team — India salaries","SDE2 ₹50L, SDE3 ₹80L, ML ₹60L, CEO/CTO ₹85L","Founder base sheet (internal, 2026-02)"),
]
for b, f, s in SOURCES:
    w("| %s | %s | %s |" % (b, f, s))
w()
w("<sub>© 2026 AegionAI. Confidential — internal planning model, all figures estimated/speculative. "
  "Editable source: AegionAI-Cost-Model.xlsx (formulas recalc on open).</sub>")
w()

OUT = os.path.join(os.path.dirname(__file__), "AegionAI-Cost-Model.md")
with open(OUT, "w") as fh:
    fh.write("\n".join(L))
print("wrote", OUT)
print("base runway %.1f mo | recurring(incl buffer) %s/yr (%s/mo) | one-time %s" % (
    runway, usd(recurring_total), usd(recurring_total/12), usd(onetime_total)))
print("  +AE %.1f mo | lean %.1f mo | high %.1f mo" % (ae_rw, lean_rw, high_rw))
