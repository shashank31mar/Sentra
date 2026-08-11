# Briefing — Healthcare AI-Agent Adoption, Governance Scope, and the Action-Governance Gap
**Prepared for:** AegionAI founder · **Conversation target:** Parminder ("Parry") Bhatia, SVP of AI, Edwards Lifesciences · **Date:** 2026-08-01 · **Freshness:** sources dated 2023–2026; time-sensitive figures dated inline.

---

## 1. TL;DR

- **Adoption is real but assistive.** Healthcare AI software spend hit ~$1.4B in 2025 (~3x 2024) and 22% of orgs run domain-specific AI [1]; but the mature category — ambient scribing (~$600M, 2025) — *drafts* notes a clinician signs, i.e. answering, not acting [1]. `[FACT]`
- **Genuine autonomous *action* is concentrated in the back office.** Prior auth, claims, revenue-cycle/coding, and patient outreach are where agents actually execute — 61% of large health orgs are building/budgeting agentic AI (Deloitte survey, Sept 2025) [2], and Epic is repositioning copilots (Art/Penny/Emmie) as action-takers [5]. `[FACT]`
- **Governance is a deep stack — but model-and-data-centric.** FDA SaMD/PCCP [10], HIPAA/BAA [15], ONC HTI-1 transparency [17], EU AI Act [18], NIST/WHO/CHAI/Joint Commission [22][23][24][25] all govern the model and its data *pre-deployment*. **None squarely governs what an autonomous agent is permitted to DO at runtime.** `[INFERENCE]`
- **The action-gap verdict: REAL and structurally uncovered, urgency emerging (not yet crisis-proven).** The marquee harms to date (UnitedHealth/nH Predict [29], Cigna PXDX [34], Epic Sepsis [36]) are *decision-model outputs acted on* — proof that injury happens at the action and that human-in-the-loop (HITL) fails at scale — but a dated *autonomous-agent* action disaster hasn't landed yet. `[INFERENCE]`
- **The honest risk:** you're selling *ahead of* the incident curve. A skeptic can argue the fix is better model validation + real human review, and that pre-deployment validation + HITL is "sufficient for now." Lead with the foreseeable, cite the hard numbers, don't invent an agent body count. `[REC]`

---

## 2. How healthcare is adopting AI agents

**Scale and pace.** US healthcare AI software spend ≈ **$1.4B in 2025, ~3x 2024**; 22% of orgs have deployed domain-specific AI (health systems 27%, payers 14%) — ~2.2x the broader-economy rate (Menlo/Morning Consult, ~700 execs, survey Aug–Sept 2025) [1]. **66% of US physicians used some health AI in 2024**, up from ~38% in 2023 (AMA, Nov-2024 survey) [4] — but mostly for documentation/admin, not clinical action. AI-enabled startups took **62% of H1-2025 US digital-health VC** ($6.4B/245 deals) at an 83% per-round premium (Rock Health) [3]. `[FACT]`

**Where agents actually run (most→least mature):**
1. **Ambient documentation** — most mature, ~$600M in 2025 (DAX Copilot 33% / Abridge 30% share; Abridge at 100+ systems incl. Kaiser's ~40-hospital rollout) — **assistive: a note the clinician signs** [1][3]. `[FACT]`
2. **Prior authorization** — the clearest genuine-action wedge: **MUSC reports agents completing 40% of prior auths with no human**; 70% of plans prioritize UM/PA/claims (Deloitte) [2]. `[FACT]` *(MUSC 40% is single-Deloitte-sourced — flag.)*
3. **Revenue-cycle/coding** — ~$450M AI market in 2025 (Epic "Penny") [1][5].
4. **Patient outreach (voice)** — Hippocratic AI runs discharge/pharmacy calls at UHS and University Hospitals [6]. *(Its "180M interactions" is vendor self-report — flag.)*
5. **Care coordination / virtual nursing** — Epic "Emmie," Stanford ChatEHR [5][2].

**Trajectory (copilot→agent, 12–24 mo).** Vendors/analysts explicitly forecast the shift: Deloitte projects payer workflows moving to *"proactive, zero-touch adjudication"* [2]; Epic (UGM Aug 2025) named agents and set the goal to *"make the EHR agentic-AI-enabled"* [5]. Near-term expansion is **administrative autonomy, gated by governance/liability** — diagnosis/treatment stay human-owned. `[INFERENCE]`

**Downside (do not oversell).** (a) Pilot-to-production gap: MIT NANDA (2025) — **~95% of enterprise gen-AI pilots deliver no measurable ROI** (cross-industry, methodology debated) [8]; a widely-repeated but **single-source, unverified** Deloitte/Microsoft figure claims only ~3% of healthcare agents run in live clinical workflows [9]. (b) Thin efficacy: first RCT of ambient scribes (NEJM AI, UCLA, Nov 2025) found **only Nabla cut documentation time (−9.5%); DAX not significant**, both with "occasional inaccuracies" [7]. `[FACT]`

---

## 3. The scope of AI governance in healthcare

"Governance" is a multi-layer obligation stack a Chief AI Officer must satisfy:

- **FDA (devices).** Draft guidance *"AI-Enabled Device Software Functions: Lifecycle Management"* (Jan-7-2025) applies Total-Product-Life-Cycle principles and leans on **Predetermined Change Control Plans (PCCPs)** so models update without re-filing [10][11]; asks for bias/transparency documentation but **sets no numeric thresholds** [12]. ~1,250–1,450 AI/ML devices authorized (76% radiology, ~97% via 510(k)); **essentially zero cleared LLM/GenAI clinical devices**, and no finalized GenAI framework (first DHAC pass Nov-2024) [13][14]. `[FACT]`
- **HIPAA.** Any AI vendor touching PHI is a **business associate needing a BAA**; using PHI to train a vendor's *own* model generally isn't authorized by a standard BAA — a live exposure surface [15]. OCR proposed the first Security Rule overhaul in ~20 years (Jan-6-2025) [16]. `[FACT]`
- **ONC/ASTP HTI-1.** Certified EHRs must disclose ~31 "source attributes" for **predictive Decision Support Interventions** (DSI compliance ~Jan-1-2025); certified health IT covers 96% of hospitals [17]. `[FACT]`
- **EU AI Act** (in force Aug-1-2024). Most AI medical devices are **high-risk**; fines up to €35M / 7% of turnover [18]. High-risk phase-in dates are **in flux** — a "Digital Omnibus" would defer to Dec-2027/Aug-2028, but this is **provisional, not adopted**; treat the original Aug-2026/2027 dates as legally operative [19]. `[INFERENCE]`
- **State patchwork.** CA AB 3030 (GenAI patient-comms disclaimer, Jan-1-2025) + SB 1120 (physician oversight of AI utilization review) [20]; CO AI Act (delayed to Jun-30-2026); TX TRAIGA/HB 149 (Jan-1-2026, up to $200K penalties); UT AI Policy Act + mental-health-chatbot amendment [21]. `[FACT]`
- **Voluntary frameworks** filling the operational gap: **NIST AI RMF + GenAI Profile** [22], **WHO LMM guidance** (40+ recs, Jan-2024) [23], **CHAI** assurance/model-card registry [24], and **Joint Commission + CHAI "Responsible Use of AI" (RUAIH, Sep-17-2025)** — voluntary, 7 elements incl. board-level oversight and data security beyond HIPAA, with a **voluntary certification coming** [25]. `[FACT]`

**Operationally**, governance now means: a multidisciplinary governance committee, an **AI inventory/registry**, pre-deployment model validation, bias/fairness audits, and continuous **post-deployment monitoring** (the Epic Sepsis failure anchors this mandate) [26]. **Ownership is consolidating under a Chief AI Officer** — CAIO prevalence reportedly grew ~11%→26% of health systems (2023→2025) [27]. `[FACT]/[INFERENCE]`

---

## 4. The gap AegionAI addresses — model/data governance vs. runtime action governance

**The distinction is true and citable.** The entire stack above governs the *model and its data pre-deployment* and by design **stops at the runtime action**: FDA/PCCP govern the device lifecycle [10]; HTI-1 mandates *transparency* about a scored prediction, not control over what a deployed agent does [17][38]; CHAI's scope is **pre-deployment assurance** (test labs, model cards) with **no runtime action-enforcement** [39]. `[FACT]`

**HITL is empirically a weak control at scale — with real incidents:**
- **UnitedHealth / nH Predict** (Lokken, D. Minn.): AI output used to deny/terminate post-acute care over treating physicians; core claims proceed, court ordered algorithm disclosure (~Mar 2026) [29][30]. Only **~0.2% of patients appeal** [31]. `[FACT]` *(the "90% wrong" figure is a litigation **allegation** — mark as alleged [31].)*
- **HHS OIG (hard number):** Medicare Advantage plans **overturned ~95% of appealed SNF prior-auth denials** when actually reviewed [32]; Senate PSI "Refusal of Recovery" confirmed algorithm-driven denials [33]. `[FACT]`
- **Cigna PXDX:** physicians rejecting claims at **~1.2 seconds each** — the cleanest proof HITL collapses into rubber-stamping [34]. `[FACT]`
- **Automation bias (Dratsch, Radiology):** a wrong AI suggestion dropped expert radiologist accuracy from **~82% to 45.5%** — humans don't reliably catch a wrong AI action [35]. `[FACT]`
- **Epic Sepsis Model:** external AUC 0.63 (vs claimed 0.76–0.83), missed ~67% of cases, alerts on ~1-in-5 patients — runtime behavior diverging from validation claims [36]. `[FACT]`
- **Closest to an agent write:** OpenAI Whisper via Nabla **fabricated text** in clinical transcripts across ~7M visits [37]. `[FACT]`

**Honest verdict.** The gap is **real and structurally uncovered**; analysts now name it (Gartner's "decision governance gap," Jun-2026 [40]; "HITL does not mean safe" [41]; OWASP Agentic Top-10, Dec-2025 — Excessive Agency, Tool Misuse, PHI disclosure [42]). **But nearly all cited *harm* is decision-models-acted-on, not tool-using agents autonomously executing writes/orders/exports** — that incident class is thin. **You're selling "prevent the foreseeable," not "clean up the ongoing crisis."** The missing keystone that would flip it: a dated production incident of an agent autonomously executing a wrong EHR write / order / PHI export. `[INFERENCE]`

**Contrarian objections to expect:** (1) *"Fix the model / do real human review"* — a runtime PEP wouldn't stop a human rubber-stamping a bad denial. (2) The autonomous-agent incident set is still mostly hallucinated-note (an output-quality problem the model vendor owns). (3) *"Pre-deployment validation + HITL is sufficient for now"* is a live buyer posture. The action-governance field itself is **thin/early** — OrdoAgents (healthcare-specific) and general tools (Lakera, Credo, Galileo) leave room, but that also means the category isn't yet buyer-obvious [42][43]. `[FACT]/[INFERENCE]`

---

## 5. Medtech & Edwards lens

**Medtech is now a live "agents taking real actions" market.** FDA itself deployed **agency-wide agentic AI on Dec-1-2025** across pre-market reviews, post-market surveillance, inspections and compliance — *"with strict data protections and human oversight"* [48]; its earlier GenAI tool **Elsa** (Jun-2-2025, >70% staff use) [49] was reported by staff to **hallucinate studies and fabricate citations** (CNN, Jul-2025) [50] — the clearest proof the failure mode is real and that the regulator's own answer is *govern the action* (human oversight + data protections), not just the model. Vendors are already selling agents into device workflows: **i-GENTIC** context-aware 510(k)-review agents (Feb-2026) [54]; BCG documents medtech deploying AI inside **QMS and regulatory affairs** [55]. `[FACT]`

**Why the action surface is high-stakes in a device co.** Agent actions land on FDA-regulated records — 510(k)/PMA submissions, QMS/CAPA, complaint files, **MDR/adverse-event filings (21 CFR Part 803, hard 5/30-day clocks)** [56], post-market surveillance. A misclassified reportable event or an out-of-bounds write to a Design History File is a **data-integrity/compliance/patient-safety event** under the QMSR (21 CFR 820 ↔ ISO 13485, **effective Feb-2-2026**) [53], **21 CFR Part 11 / ALCOA+** (records must be attributable + tamper-evident + audit-trailed) [57], and HIPAA. The FDA credibility framework (Jan-2025) already reaches a company's **own** internal AI use in submissions [51][52]. `[FACT]/[INFERENCE]`

**Why in-VPC / PHI-boundary matters.** Recommended architecture for regulated AI is that **PHI never leaves the covered entity's control** — private/open-weight models in the customer's VPC/on-prem/air-gapped under BAAs, RBAC, audit logs [58]. Data security is a leading enterprise-AI adoption barrier (Gartner; BigID Jun-2025) [59]. This is the concrete rationale for governing the action inline, in-boundary, with a tamper-evident audit trail. `[FACT]`

**Parminder's mandate (mark inference).** Bhatia is **SVP of AI at Edwards** (reported Jul-2026), leading enterprise AI to "improve patient outcomes and drive competitive advantage" [44]; prior **CAIO at GE HealthCare** and GenAI science lead at Amazon (CodeWhisperer/Bedrock) [45]; repeatedly branded around **"responsible AI deployment across regulated healthcare environments"** [45]. Edwards = structural-heart leader (TAVR/SAPIEN), **$6.07B FY2025 revenue, ~16,000 employees**, divested Critical Care to BD (2024) [46]. **CAVEAT — no public disclosure of Edwards' own AI-agent programs exists**; everything about Edwards' specific deployments below the role/mandate is **inference, not a cited Edwards source** [47]. `[FACT]` for the person; `[INFERENCE]` for the internal programs.

**Edwards contrarian (don't overreach):** Bhatia's early wins may be low-risk (R&D copilots, imaging on the device side), not autonomous writes to regulated records; FDA's Elsa answer was *procedural* HITL a big device maker can implement without a third-party plane; **submission/QMS text may be low-PHI** (HIPAA bites hardest in complaint/adverse-event and clinical workflows); and Veeva/MasterControl embed their own AI governance — a neutral cross-vendor plane must prove it beats controls bundled into the systems of record. `[INFERENCE]`

---

## 6. Talking points for the Parminder conversation

Useful-to-him, non-salesy:

1. **Frame the field's real state:** production autonomy today is administrative (prior auth, claims, RCM, outreach), not clinical — and vendors (Epic Penny/Emmie, Deloitte "zero-touch adjudication") are pushing copilots into action-takers over the next 12–24 mo [2][5]. `[FACT]`
2. **The governance stack governs the model, not the action.** FDA/PCCP, HTI-1, CHAI all stop at pre-deployment/transparency; no framework governs what a deployed agent is *permitted to do* at runtime [10][17][24]. This is the emerging "decision governance gap" Gartner and OWASP now name [40][42]. `[INFERENCE]`
3. **HITL is a documented weak control at scale** — Cigna's 1.2s/claim [34], radiologist accuracy 82%→45.5% under a wrong AI [35], OIG's 95% denial-overturn [32]. Useful for *his* internal risk framing regardless of vendor choice. `[FACT]`
4. **The regulator is living your risk model:** FDA's own Elsa hallucinated citations, and its Dec-2025 agentic rollout answer was "human oversight + data protections" [48][50] — external validation that action-level control + audit is the response, not more model tuning.
5. **Medtech-specific stakes:** an agent touching MDR/CAPA/510(k) records operates inside QMSR (eff. Feb-2026) + Part 11 tamper-evident-audit obligations [53][57][56] — a governance failure there is an inspection/enforcement event, not a UX bug.
6. **The in-boundary architecture:** governing the action inline, in-VPC, so PHI/submission content never crosses to a third party, with a Part-11-grade audit trail — makes "responsible AI in a regulated environment" an *inspectable control*, not a policy statement [57][58].
7. **Be honest on maturity:** the autonomous-agent-disaster wave hasn't hit; this is "prevent the foreseeable." That candor builds credibility with a responsible-AI leader.

**Three questions to ask him (informed, elicit validation):**
- *"Where do you draw the line today between an agent that drafts versus one allowed to write to a regulated record (QMS, MDR, a submission)? What has to be true before that line moves?"*
- *"As you scale AI, is your control model still validate-the-model-plus-human-sign-off — and where do you see human review breaking down at volume?"* (invites the HITL-at-scale insight without pitching)
- *"For regulated data and IP, how are you thinking about the deployment boundary — in-VPC/on-prem vs. vendor cloud — and does neutrality across AWS/Azure/on-prem matter for how you standardize?"*

---

## 7. What this sharpens for AegionAI (healthcare beachhead)

- **[REC] Lead with decision-model harms as proof, position agent-action governance as the next-order gap.** nH Predict, Cigna PXDX, Epic Sepsis are dated, independently corroborated, and prove *injury happens when a wrong AI output is acted on* and *HITL is weak at scale* [29][34][36]. Do **not** overclaim an autonomous-agent disaster wave — cite OIG 95% / Senate PSI / JAMA / Radiology as the hard numbers and mark litigation figures (nH Predict "90%") as **alleged** [32][33][31]. This is the single most credibility-preserving refinement.
- **[REC] Anchor the healthcare wedge to Part 11 / QMSR / MDR + in-VPC, not to "block a bad prompt."** In regulated medtech the value is a **tamper-evident, attributable audit of the agent action** that satisfies Part 11/QMSR *by construction* [53][57], plus keeping PHI/submission content in-boundary [58] — reframing audit as a *compliance requirement*, not a feature.
- **[REC] Concede the "sufficient-for-now" objection explicitly and sell foreseeability.** Buyers today accept pre-deployment validation + HITL; the evidence that HITL fails at scale *is* the wedge, but frame it as governing the action *before* agents are already making the calls (Gartner's "govern early") [40] — and win the neutrality argument only where the buyer spans AWS/Azure/on-prem, since a single-stack shop weakens it. `[INFERENCE]`

---

## 8. Sources

1. Menlo Ventures — *2025: The State of AI in Healthcare* — https://menlovc.com/perspective/2025-the-state-of-ai-in-healthcare/
2. Deloitte Insights — *Health care leans into agentic AI* (survey Sept 2025) — https://www.deloitte.com/us/en/insights/industry/health-care/agentic-ai-health-care-operating-model-change.html
3. Rock Health — *H1-2025 Market Overview* — https://rockhealth.com/insights/h1-2025-market-overview-proof-in-the-pudding/
4. AMA — *Physician AI Sentiment Report* — https://www.ama-assn.org/practice-management/digital-health/2-3-physicians-are-using-health-ai-78-2023
5. Healthcare IT News — *Epic unveils AI agents (UGM 2025)* — https://www.healthcareitnews.com/news/epic-unveils-ai-agents-showcases-new-foundational-models
6. UHS / Hippocratic AI — https://www.uhs.com/
7. NEJM AI — Lukac et al., *RCT of ambient AI scribes* — https://ai.nejm.org/doi/full/10.1056/AIoa2501000
8. Healthcare IT News — *MIT: 95% of enterprise AI pilots fail* — https://www.healthcareitnews.com/news/mit-95-enterprise-ai-pilots-fail-deliver-measurable-roi
9. agentmarketcap.ai (weak aggregator; ~3% figure UNVERIFIED) — https://agentmarketcap.ai/blog/2026/04/23/healthcare-ai-agents-pilot-production-gap
10. Federal Register / FDA — *AI-Enabled Device Software Functions* (FDA-2024-D-4488) — https://www.federalregister.gov/documents/2025/01/07/2024-31543/artificial-intelligence-enabled-device-software-functions-lifecycle-management-and-marketing
11. CenterWatch — FDA AI device guidance / PCCP analysis — https://www.centerwatch.com/insights/fda-guidance-on-ai-enabled-devices-transparency-bias-lifecycle-oversight/
12. DLA Piper — FDA AI device guidance (bias/transparency) — https://www.dlapiper.com/en-us/insights/publications/2025/01/fda-issues-artificial-intelligence-enabled-device-software-functions-guidance
13. IntuitionLabs — FDA AI/ML device tracker (secondary) — https://www.intuitionlabs.ai/articles/fda-ai-medical-device-tracker
14. FDA — Digital Health Advisory Committee (Nov-2024, GenAI) — https://www.fda.gov/advisory-committees/advisory-committee-calendar/november-20-21-2024-digital-health-advisory-committee-meeting-announcement-11202024
15. Foley & Lardner — HIPAA compliance for AI — https://www.foley.com/insights/publications/2025/05/hipaa-compliance-ai-digital-health-privacy-officers-need-know/
16. HIPAA Journal — OCR Security Rule NPRM — https://www.hipaajournal.com/when-ai-technology-and-hipaa-collide/
17. ONC/ASTP HealthIT.gov — HTI-1 / DSI transparency — https://www.healthit.gov/topic/laws-regulation-and-policy/health-data-technology-and-interoperability-certification-program
18. DQS Global — EU AI Act & medical devices — https://www.dqsglobal.com/en/explore/blog/ai-act-ai-enabled-medical-devices
19. Gibson Dunn — EU AI Act "Digital Omnibus" (provisional) — https://www.gibsondunn.com/eu-ai-act-omnibus-agreement
20. Duane Morris — CA AB 3030 / SB 1120 — https://www.duanemorris.com/alerts/california_passes_novel_law_governing_generative_ai_healthcare_1224.html
21. Akin Gump — AI law tracker (CO/TX/UT) — https://www.akingump.com/en/insights/ai-law-and-regulation-tracker/colorado-postpones-implementation-of-colorado-ai-act-sb-24-205
22. NIST — AI RMF + Generative AI Profile (AI 600-1) — https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence
23. WHO — LMM ethics & governance guidance — https://www.who.int/news/item/18-01-2024-who-releases-ai-ethics-and-governance-guidance-for-large-multi-modal-models
24. CHAI — Responsible Health AI framework (draft) — https://www.chai.org/blog/chai-releases-draft-responsible-health-ai-framework-for-public-comment
25. Hooper Lundy — Joint Commission + CHAI RUAIH — https://hooperlundy.com/joint-commission-and-the-coalition-for-health-ai-chai-release-governance-frameworks/
26. AMA STEPS Forward — augmented-intelligence governance toolkit — https://edhub.ama-assn.org/steps-forward/module/2833560
27. Mosaic Life Tech — AI governance committee / CAIO — https://mosaiclifetech.com/governance/how-to-build-an-ai-governance-committee
28. MedicalXpress — *Autonomous AI agents outpace medical device regulations* — https://medicalxpress.com/news/2025-07-autonomous-ai-agents-outpace-medical.html
29. Healthcare Finance News — UnitedHealth AI-denial suit advances — https://www.healthcarefinancenews.com/news/class-action-lawsuit-against-unitedhealths-ai-claim-denials-advances
30. STAT News — Medicare Advantage AI denials (nH Predict) — https://www.statnews.com/2023/03/13/medicare-advantage-plans-denial-artificial-intelligence/
31. Altair Health — nH Predict disclosure order (90% ALLEGED) — https://altair-health.com/news/2026-03-27/court-orders-unitedhealth-disclose-ai-denial-algorithm-90-error-rate-alleged
32. Healthcare Finance News — HHS OIG SNF-denial overturn (~95%) — https://www.healthcarefinancenews.com/news/medicare-advantage-organizations-overturned-most-snf-denials-oig-finds
33. US Senate PSI — *Refusal of Recovery* — https://www.hsgac.senate.gov/subcommittees/investigations/
34. ProPublica — Cigna PXDX (1.2s/claim) — https://www.propublica.org/article/cigna-pxdx-medical-health-insurance-rejection-claims
35. Dratsch et al., *Radiology* (RSNA) — automation bias — https://pubs.rsna.org/doi/10.1148/radiol.222176
36. Wong et al., *JAMA Internal Medicine* — Epic Sepsis Model — https://jamanetwork.com/journals/jamainternalmedicine/fullarticle/2781307
37. The Verge (AP) — Whisper/Nabla hallucinations — https://www.theverge.com/2024/10/27/24281170/open-ai-whisper-hospitals-transcription-hallucinations-studies
38. HealthIT.gov — HTI-1 Final Rule — https://www.healthit.gov/regulations/hti-rules/hti-1-final-rule/
39. CHAI — assurance-lab certification + model "nutrition label" — https://www.chai.org/blog/chai-advances-assurance-lab-certification-and-nutrition-label-for-health-ai
40. healthsystemCIO (Gartner) — *AI decision governance gap* — https://healthsystemcio.com/2026/06/17/ai-decision-governance-gap/
41. Healthcare IT Today — *HITL does not mean safe* — https://www.healthcareittoday.com/2026/07/29/human-in-the-loop-does-not-mean-safe-the-hidden-risks-of-agentic-ai/
42. OrdoAgents (citing OWASP Agentic Top-10, Dec-2025) — https://www.ordoagents.com/insights/securing-agentic-ai-healthcare
43. FutureAGI — AI agent governance tools roundup (directional) — https://futureagi.com/blog/best-ai-agent-governance-tools-2026/
44. CDO Magazine — Edwards taps Parminder Bhatia SVP AI — https://www.cdomagazine.tech/leadership-moves/edwards-lifesciences-taps-parminder-bhatia-senior-vice-president-ai
45. PRNewswire — Bhatia joins Helio Genomics board (profile) — https://www.prnewswire.com/news-releases/healthcare-ai-leader-parminder-bhatia-joins-helio-genomics-board-of-directors-302827558.html
46. Wikipedia — Edwards Lifesciences (SEC/10-K aggregation) — https://en.wikipedia.org/wiki/Edwards_Lifesciences
47. Edwards Lifesciences corporate/IR (no AI-agent program disclosed) — https://www.edwards.com
48. FDA — agency-wide agentic AI deployment (Dec-2025) — https://www.fda.gov/news-events/press-announcements/fda-expands-artificial-intelligence-capabilities-agentic-ai-deployment
49. FDA — Elsa agency-wide launch (Jun-2025) — https://www.fda.gov/news-events/press-announcements/fda-launches-agency-wide-ai-tool-optimize-performance-american-people
50. CNN — *FDA's AI is hallucinating studies* — https://www.cnn.com/2025/07/23/politics/fda-ai-elsa-drug-regulation-makary
51. Sterne Kessler — FDA Jan-2025 AI draft guidances — https://www.sternekessler.com/news-insights/client-alerts/fda-issues-draft-guidance-documents-on-artificial-intelligence-for-medical-devices-drugs-and-biological-products/
52. FDA — *AI to Support Regulatory Decision-Making* (draft) — https://www.fda.gov/regulatory-information/search-fda-guidance-documents/considerations-use-artificial-intelligence-support-regulatory-decision-making-drug-and-biological
53. FDA — Quality Management System Regulation (QMSR, eff. Feb-2-2026) — https://www.fda.gov/medical-devices/postmarket-requirements-devices/quality-management-system-regulation-qmsr
54. AdvaMed — i-GENTIC AI context-aware MedTech agents (self-reported) — https://www.advamed.org/industry-updates/news/i-gentic-ai-launches-context-aware-medtech-agents-to-strengthen-fda-510k-submission-consistency/
55. BCG — *MedTech Can Improve Quality & Regulatory Processes with GenAI* — https://www.bcg.com/publications/2025/medtech-can-improve-quality-regulatory-processes-gen-ai
56. eCFR — 21 CFR Part 803 (Medical Device Reporting) — https://www.ecfr.gov/current/title-21/chapter-I/subchapter-H/part-803
57. SG Systems Global — 21 CFR Part 11 / ALCOA+ audit-trail hub — https://sgsystemsglobal.com/guides/data-integrity-part-11-annex-11-audit-trails-hub/
58. Codility Solutions — HIPAA LLM deployment (PHI-in-VPC) — https://www.codilitysolutions.com/blog/posts/blog-5.html
59. PRNewswire (BigID; incl. Gartner AI-mandates) — enterprise AI vs. security-readiness gap — https://www.prnewswire.com/news-releases/new-study-reveals-major-gap-between-enterprise-ai-adoption-and-security-readiness-302469214.html