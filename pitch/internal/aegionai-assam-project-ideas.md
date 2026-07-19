# AegionAI × Government of Assam — Project Ideas Brief

**Prepared for:** the CM/IT-Department meeting (letterhead: [pitch/brand/AegionAI-Assam-introduction.html](../brand/AegionAI-Assam-introduction.html))
**Date:** 2026-07-18
**Purpose:** A ranked shortlist of concrete AI / AI-security projects AegionAI can propose to Assam, each mapped to a *stated, dated* Assam priority. Working doc — react to it, then we fold the winners into the letter.

> **Evidence discipline.** `[FACT]` = sourced (dated, see Sources). `[INFERENCE]` = concluded from facts. `[REC]` = recommendation. The landscape facts are strong; every "how it maps to AegionAI" line is `[INFERENCE]` / `[REC]`, not a claim that Assam has scoped or budgeted it.

---

## 1. The one-paragraph read

Assam has, in the last ~8 months, stood up a **real, top-down AI program with an institutional spine** — not a press release. There is a Chief-Secretary-chaired **Steering Committee on AI Adoption**, an inventory of **343 project ideas across 50+ departments in 11 clusters**, a proposed **five-layer AI architecture**, a Cabinet-approved **State Data Policy (ASDP 2026)** that builds a unified state data lake, a **Google Cloud MoU + AI Centre of Excellence**, a forthcoming **AI-IT Policy 2025**, and — most important for us — a **LIVE agentic-AI deployment on the Sewa Setu citizen portal (10,000+ applications/day) with a mandatory human-in-the-loop**. This sits under a hardening national regime (India AI Governance Guidelines; **DPDP Rules 2025** with data-localization powers and mandatory audits/DPIAs for AI). Assam also now has the physical **sovereign infrastructure** (Yotta National Data Center–North East, PM-inaugurated Feb 2026) to host it. **AegionAI's exact product — action-level governance + block-before-execute + tamper-evident audit, deployable in-VPC / air-gapped — is the enforcement-and-evidence layer this program is missing.** That is our lead. Everything else (sovereign LLM, flood/agri/health agents, semiconductor workforce) is a broader venture we can *layer on top of the trust relationship*, not lead with.

---

## 2. What Assam is actually doing (the landscape we're pitching into)

| # | Initiative | Status / date | Why it matters to us |
|---|-----------|---------------|----------------------|
| A | **Steering Committee on AI Adoption** (CS Dr. Ravi Kota) — designing a **five-layer AI architecture**; **343 project ideas / 50+ depts / 11 clusters** | Deliberated 17–18 May 2026 `[FACT]` | The five-layer stack *has a data-governance layer* — the natural slot for our control plane. |
| B | **Agentic AI LIVE on Sewa Setu** — assists officials processing citizen applications; **"Human-in-the-Loop as a mandatory requirement"**; portal does **10,000+ applications/day** | Live, stated Mar–Apr 2026 `[FACT]` | This is a **running autonomous-agent deployment taking government actions.** It is exactly what we govern. **Our #1 wedge.** |
| C | **Assam State Data Policy (ASDP) 2026** — creates a **Centre for Data Management (CDM)** as nodal agency for a **unified, state-wide data repository for analytics and AI** | Cabinet-approved 21 May 2026 `[FACT]` | A sovereign state data lake that AI agents will read/write. Governing *what agents may do* against it = our #2 wedge. |
| D | **Google Cloud MoU** + **AI Centre of Excellence** (Google + Paradigm IT); IT Minister framed AI as "guardian of trust, privacy and equity"; goal to "**safeguard data sovereignty**" | MoU 11 Nov 2025 `[FACT]` | The CoE is the department-facing delivery vehicle — but it may be **Google-Cloud-anchored**. Our **cross-vendor neutrality** is the differentiator to lead with here. |
| E | **Assam AI-IT Policy 2025** — aim: "**AI hub of India in the northeast**," "ethical AI-driven governance" | Forthcoming `[FACT]` | Policy language explicitly invokes governance + sovereignty — our vocabulary. |
| F | **National regime**: India AI Governance Guidelines + IndiaAI Mission **"Safe & Trusted AI"** pillar; **DPDP Rules 2025** (data-localization powers, India-based consent managers, **mandatory independent audits + DPIAs for AI**) | Guidelines ~Nov 2025; DPDP Rules notified 14 Nov 2025 `[FACT]` | Demand signal for tamper-evident audit + in-country deployment. **Caveat:** guidelines are voluntary; DPDP's substantive AI obligations phase in **~mid-2027** — a forward-dated signal, not an in-force mandate today. |
| G | **Yotta National Data Center–North East** (Guwahati) — PM Modi-inaugurated; "sovereign environment for sensitive government data," "foundational pillar for e-Governance" | Inaugurated 14 Feb 2026 `[FACT]` | The physical **air-gapped host** for our self-managed edition. "Enforcement never leaves the sovereign boundary." |
| H | **IIT Guwahati** — **TIDF** (DST NM-ICPS Section-8 company registered in Assam) + **Mehta Family School of Data Science & AI** (2021, "gateway to NE India") + CoE for Robotics/AI/IoT | Ongoing; CoE 17 Mar 2025 `[FACT]` | Local academic partner → credibility anchor, testbed, and vehicle for an indigenous "Safe & Trusted AI" tool under the IndiaAI Mission. |
| I | **Disaster stack** — **NESAC FLEWS** (India's first operational GIS hydro-met flood warning, revenue-circle alerts) + **ASDMA Smart Axom** | Operational `[FACT]` | A life-safety domain; if agentic AI is layered on flood dispatch, governed autonomy is a high-visibility showcase. Candidate, not yet an agentic deployment. |
| J | **Tata Electronics OSAT semiconductor fab, Jagiroad** — ₹27,000 cr (~$3.2B), ~48M chips/day | Commissioning/qualifying mid-2026 `[FACT]` | Flagship, but a *speculative* target for us (industrial/OT agent governance + workforce). Future/optional, not lead. |

**Refuted / don't rely on:** the *IndiaAI Application Development Initiative is NOT the vendor entry channel* into state AI projects (verified false, 0-3). **The actual procurement route into Assam's program is unknown** — the biggest open question below.

---

## 3. Ranked shortlist — pitchable projects

Ordered by **strength of fit × groundedness in a stated Assam priority.** Tiers 1–2 use AegionAI's real product; Tier 3 are broader AI ventures (you asked to think broad).

### TIER 1 — lead with these (direct product fit, live priority)

**① Runtime action-governance + tamper-evident audit under agentic Sewa Setu** ⭐ *top pitch*
- **The pitch:** Assam already runs agentic AI on Sewa Setu with a *mandatory human-in-the-loop rule you set yourselves.* Today that rule is a policy; AegionAI **enforces it in code** — block-before-execute on every agent action (what it does, its parameters, the identity behind it, the sequence), so no agent action commits outside its authorized scope, and every automated decision lands in an **append-only, tamper-evident audit trail** for oversight.
- **Maps to:** landscape B (live agentic deployment + HITL), A (five-layer architecture's governance layer).
- **Why us:** point tools inspect the *prompt*; we govern the *action*. A human-in-loop pipeline needs an enforcement + evidence substrate — that's exactly our product.
- **Confidence:** medium (fit strongly evidenced; no procurement channel confirmed).

**② Data-sovereignty control plane (in-VPC / air-gapped) for the ASDP Centre-for-Data-Management data lake**
- **The pitch:** as the CDM builds one unified state data repository that AI agents will query and write to, AegionAI governs **what each agent is allowed to do** against that lake — deployed **in-VPC or fully air-gapped so data and enforcement never leave Assam's boundary** — and produces **DPDP-grade audit evidence** (independent-audit / DPIA ready).
- **Maps to:** landscape C (CDM data lake), F (DPDP audits + localization), G (sovereign host).
- **Confidence:** medium.

### TIER 2 — strong supporting pitches

**③ Air-gapped AI-security enclave co-located in the Yotta NDC-NER**
- Deploy our self-managed ("nothing leaves") edition *inside the sovereign data center* so enforcement + audit for AI workloads on sensitive citizen data stay within the facility's sovereignty mandate. Maps to G. Confidence medium (whether the DC hosts third-party tooling is unverified).

**④ DPDP / Significant-Data-Fiduciary compliance-and-audit layer**
- Position our tamper-evident audit + action governance as the **evidence substrate for the mandatory independent audits, DPIAs, and "stricter checks on new/sensitive technologies (AI)"** the DPDP Rules impose. Maps to F. Confidence medium (obligations phase in ~mid-2027 — sell as get-ahead-of-the-regime).

**⑤ Neutral cross-vendor guardrail for the AI Centre of Excellence**
- Embed AegionAI as the **vendor-neutral** governance layer across Google Cloud + any other cloud/on-prem the CoE serves. Maps to D, E. Confidence **low** — the CoE may be Google-locked; neutrality is either the wedge or the barrier. **Positioning bet, not a confirmed opening.**

### TIER 3 — broader AI ventures (beyond the current product; partner/build)

These ride Assam's stated priorities but need new build or partners. Pitch as *"here's the bigger arc once trust is established."*

**⑥ Sovereign Assamese / multilingual citizen-service assistant** — a low-resource NE-language (Assamese, Bodo, Bengali, tribal languages) assistant for Sewa Setu, trained/hosted **in-country**, with AegionAI governing its actions. Maps to B/E. *Big genuine gap; India-language coverage is weak.*
**⑦ Governed agentic flood-disaster decision-support** — layer AI on NESAC FLEWS / Smart Axom for resource dispatch, with our governed-autonomy + audit as the life-safety guardrail. Maps to I. High-visibility showcase.
**⑧ Indigenous "Safe & Trusted AI" toolkit with IIT Guwahati (TIDF / Mehta School)** — co-develop an India-origin AI-security tool under the IndiaAI Mission's Safe & Trusted pillar. Maps to F/H. Doubles as credibility + testbed anchor for Tier 1.
**⑨ Semiconductor-era AI-security & workforce program** — OT/industrial-agent governance for the Tata Jagiroad fab + an AI-security skilling track. Maps to J/H. Speculative, long-horizon.

---

## 4. What to put in the CM letter (recommendation)

`[REC]` Lead the letter with **Tier 1 (① + ②)** as the concrete offer — they map to Assam's own live deployment and Cabinet-approved policy, so we're proposing to *strengthen what they've already committed to*, not sell them a new idea. Mention **③ (Yotta enclave)** and **⑧ (IIT-G partnership)** as the sovereignty + local-partner proof points. Frame **neutrality** and **in-VPC/air-gapped sovereignty** as the two differentiators throughout (both are already in the letter's "About AegionAI" section). Keep Tier 3 for the meeting conversation, not the letter — the letter should be tight.

---

## 5. Caveats & open questions (raise or resolve before/at the meeting)

1. **Procurement route is unknown.** The one channel we tested (IndiaAI Application Development Initiative) is *not* it. Ask directly: RFP? Empanelment? Via the AI CoE? Via Google/Paradigm IT? Via a nodal agency? — this determines whether a pilot is even reachable.
2. **Which of the 343 project ideas involve autonomous agent *actions*** (writes/transactions/dispatch needing block-before-execute) vs. read-only analytics? The cluster breakdown wasn't obtained; only the action-taking ones are our market.
3. **Is the AI CoE architecturally open to a third-party neutral layer, or effectively Google-Cloud-locked?** Decides whether ⑤ is a wedge or a wall.
4. **Does the Yotta DC host third-party security tooling, and on what colocation terms?** Decides whether ③ is real.
5. **Time-sensitivity:** nearly all facts are Nov 2025–May 2026 and moving fast; DPDP's teeth are ~mid-2027. Re-verify before the meeting.
6. **Source quality:** national/institutional facts rest on primary govt sources (high confidence); Assam-*state* program facts rest on regional press (Assam Tribune, Sentinel Assam, ToI, elets) triangulated across 2+ outlets — solid but secondary.

---

## Sources (dated)

1. *AI-First Assam: Reimagining Governance for a Digital Decade* — Elets eGov, CS Dr. Ravi Kota interview, 24 Mar 2026. https://egov.eletsonline.com/2026/03/ai-first-assam-reimagining-governance-for-a-digital-decade/
2. NIC Assam — agentic-AI grievance framework on Sewa Setu, 22 Apr 2026. https://informatics.nic.in/news/1636
3. Assam Tribune / Sentinel Assam — Steering Committee, 343 ideas, five-layer architecture (17–18 May 2026); ASDP 2026 + Centre for Data Management (21 May 2026). https://www.assamtribune.com/ · https://www.sentinelassam.com/
4. *Assam signs MoU with Google to improve administration with AI* — Times of India, 11–12 Nov 2025. https://timesofindia.indiatimes.com/city/guwahati/assam-signs-mou-with-google-to-improve-administration-with-ai/articleshow/125265678.cms
5. cxodigitalpulse — Assam–Google AI-governance & data-sovereignty framing, Nov 2025. https://cxodigitalpulse.com/assam-government-partners-with-google-to-advance-ai-driven-governance-and-digital-transformation/
6. MeitY — *India AI Governance Guidelines under IndiaAI Mission*, ~Nov 2025. https://www.digitalindia.gov.in/press_release/meity-unveils-india-ai-governance-guidelines-under-indiaai-mission-to-ensure-safe-inclusive-and-responsible-adoption-of-artificial-intelligence-across-sectors/
7. PIB backgrounder — **DPDP Rules 2025** (notified 14 Nov 2025; localization, consent managers, SDF audits/DPIAs), 17 Nov 2025. https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/nov/doc20251117695301.pdf
8. IndiaAI Mission — "Safe & Trusted AI" pillar. https://indiaai.gov.in
9. Yotta / Communications Today — **National Data Center–North East** commissioned, PM-inaugurated 14 Feb 2026. https://www.communicationstoday.co.in/yotta-commissions-national-data-center-in-north-east/ · https://www.yotta.com/
10. IIT Guwahati — **TIDF** (NM-ICPS Section-8, Assam). https://www.iitgtidf.com/ · NM-ICPS https://nmicps.gov.in/hubViewpages/8
11. IIT Guwahati — **Mehta Family School of Data Science & AI** (2021). https://www.iitg.ac.in/dsai/home/
12. NESAC — **FLEWS** flood early-warning. https://nesac.gov.in/scientific-programmes/disaster-management-support/ · ASDMA / Smart Axom https://asdma.assam.gov.in/
13. domain-b — **Tata Electronics Jagiroad OSAT** fab (₹27,000 cr, ~48M chips/day), 22 Dec 2025. https://www.domain-b.com/industry/industry-general/tata-electronics-japan-s-rohm-partner-for-auto-chips-jagiroad-unit-preps-for-2026-market-launch
