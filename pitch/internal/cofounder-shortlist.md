# Security Co-Founder — Reachable Candidate Shortlist

**For:** AegionAI / Sentra founder · **Companion to:** [cofounder-search.md](../../cofounder-search.md) (profile/pools/rubric), [cofounder-outreach-drafts.md](cofounder-outreach-drafts.md) (templates)
**Date:** 2026-07-19 · **Status:** working shortlist — 30 candidates, each verified is_founder=false (recruitable IC) at a primary source.

> **What this is (and what §5 of cofounder-search.md is NOT).** §5 of the search doc is a list of *already-founders* — advisors/intro-nodes, not recruits (its own header, line 176, crosses them off). **This** is the reachable pool: currently-employed senior/staff/principal ICs sourced by GitHub/CVE/CFP crosswalk — people with a real name + employer + a mergeable PR who *can* be pried loose from a job. Sourced by a 38-agent workflow: 64 candidates found → 56 unique non-founders → 30 adversarially confirmed at primary sources (person real + proof clicks through to them + IC not founder).

> **STANDING RULE — re-verify before contact.** Snapshots go stale fast; several employers here were *already* stale in the source cards (Habler→Cisco, Narajala→Cisco, Stemm/Di Pierro→Cisco via Isovalent, Huang possibly on a break). Before reaching out, independently re-confirm the person's CURRENT employer, title, and location on a live primary source (their own LinkedIn/site or employer page). A recent job change also materially changes recruitability. Expect LinkedIn/X to block automated checks — verify by hand.

> **The three verification / trust gates before spending a real conversation** (per [cofounder-search.md §4](../../cofounder-search.md)): (1) proof clicks through to *them* at a primary source (done below); (2) integrity — backchannel references to managers + every public claim checks out exactly; (3) "will they stay" is NOT screenable — it is absorbed by *trial-before-equity + 4yr/1yr-cliff vest + reverse-vesting + double-trigger* ([§6](../../cofounder-search.md#L252)). Trust is the *output* of that pipeline, not a prerequisite.

---

## The one strategic finding

**Not one candidate in this pool covers all three axes + CISO credibility + US geo.** The realistic read is a **two-person split** (a detection-science lead + a policy/cloud complement) **or accept one gap**. Two recurring soft-fails:

- **"Strong Python" is often a re-tooling ask.** The richest vein — the Falco/eBPF cluster (Stemm, Dellaluce, Terzolo, Susini, Guerra, Di Pierro, Altgelt) and the Cedar cluster (Kastner, Disselkoen) — ships C++/Go/Rust. The detection *instinct* transfers; the language doesn't. Confirm in conversation.
- **The ~35% cloud/policy-as-code axis is thin across almost everyone** except the two AWS Cedar scientists (wrong overall fit — they duplicate *your* strength) and partially Kaizhe Huang (OPA/PSP). This is the axis you already cover, so a gap here matters least.
- **Geography: NOT ONE India-based candidate surfaced** — the search doc's India fallback is unused. Every non-US name is "Other" (Israel / EU / Brazil / Japan / Nepal / Egypt), which is friction beyond even the stated fallback. US-primary confirmed: Stemm, Harang, Dellaluce, Huang, Ross, Narajala, Guagenti, Kastner, Disselkoen, Arora, Hamiel, Hinojosa. The Israel cluster (Habler/Bitton/Nehorai/Peles/Lumelsky) carries strong *portable* US-CISO-credible proof but needs relocation or remote-across-timezones.

---

## Tier A — top 1:1 fit (detection-science core + CISO-credible + US + clean recruitability)

| # | Name | Current role (re-verify) | Geo | Fit | Best channel |
|---|---|---|---|---|---|
| 1 | **Mark Stemm** | SW Eng Tech Leader, Cisco (via Isovalent); **original author of Falco**; now on cilium/tetragon eBPF *enforcement* | US–SF Bay | 84 | GitHub [@mstemm](https://github.com/mstemm) · [LinkedIn](https://linkedin.com/in/markstemm) |
| 2 | **Rich Harang** | Principal AI/ML Security Architect, **NVIDIA AI Red Team**; OWASP GenAI; ex-Sophos ML-malware detection | US–VA/CA | 82 | [LinkedIn](https://www.linkedin.com/in/richharang) · Bluesky rich.harang.org · GH [@rharang](https://github.com/rharang) |
| 3 | **Roberto Rodriguez** (Cyb3rWard0g) | AI Security Researcher, NVIDIA; **creator of Threat Hunter Playbook, OSSEM, HELK, Security-Datasets** | US* (residence unconfirmed) | 80 | GitHub [@Cyb3rWard0g](https://github.com/Cyb3rWard0g) · blog.openthreatresearch.com |
| 4 | **Kaizhe Huang** | Cloud Security Architect, Aurora Innovation; **Falco maintainer**; co-author *Learn Kubernetes Security*; ex-StackRox (ML detection) | US–Austin/Bay | 80 | GitHub [@Kaizhe](https://github.com/Kaizhe) · X @kaizhe · [LinkedIn](https://linkedin.com/in/kaizhe-huang) |
| 5 | **Jason Dellaluce** | Member of Technical Staff, Replit; **Falco Core Maintainer** (508 commits); ex-Sysdig threat detection | US–SF | 80 | GitHub [@jasondellaluce](https://github.com/jasondellaluce) · X @jasondellaluce |

**Notes on A:** Stemm and Dellaluce are the purest "shipped runtime detection + enforcement at CNCF scale, US-based" fits — both have an *unproven* AI/agent-security axis (learnable). Harang and Rodriguez pair the detection core with a real AI-security axis (rare) but are marquee names → recruitability is a stretch; Rodriguez additionally has personal-OSS-brand flight-risk-to-own-startup. Huang is the best two-axis fit (detection + OPA/cloud) but AI/agent is unproven and one snippet reads "taking a break" — confirm status (which may *help* availability).

## Tier B — strong, one material gap (worth a real conversation; frame around the gap)

| Name | Current role (re-verify) | Geo | Gap | Channel |
|---|---|---|---|---|
| **Jason Ross** | Product Security Principal (ExploitAI), Salesforce; **co-lead OWASP GenAI Red Teaming**, co-authored the Red Teaming Guide | US–NY | offense-weighted; lighter on defensive detection-build + policy-as-code | [jasonross.info](https://jasonross.info) · [LinkedIn](https://linkedin.com/in/algorythm) · GH rossja |
| **Andrea Terzolo** | Staff SWE, SUSE; Falco emeritus; building runtime/network *enforcers* (Learn/Monitor/Protect ≈ shadow→enforce) | Italy (EU) | geo + no Python/AI-agent proof | GH [@Andreagit97](https://github.com/Andreagit97) |
| **Vineeth Sai Narajala** | Sr Tech Lead AI Security, **Cisco** (not AWS — stale); OWASP GenAI Co-Lead; ETDI zero-trust tool-registry | US–NY | detection-tuning (~45%) least proven; hot IC, "why leave" | GH [@vineethsai](https://github.com/vineethsai) · vineethsai.com |
| **Lorenzo Susini** | Threat Detection eng, Datadog; **Falco Core Maintainer** (rule-matching engine) | Spain (EU) | C++/Go not Python; no AI-agent; geo | GH [@loresuso](https://github.com/loresuso) · loresuso.github.io |
| **Idan Habler** | AI Security Researcher, **Cisco** (not Intuit — stale); **co-lead OWASP Securing Agentic Apps**; PhD; 16+ papers | Israel | blend inverted (~70% AI-sec, light on detection FP/FN + cloud); geo | [LinkedIn](https://il.linkedin.com/in/idan-habler) · blogs.cisco.com/author/ihabler |
| **Jonhnathan Ribeiro** (w0rk3r) | Sr Security Research Eng, **Elastic TRaDE**; 484 SigmaHQ commits + elastic/detection-rules | Brazil | no cloud/policy or AI-agent proof; no CISO-name gravitas; geo | GH [@w0rk3r](https://github.com/w0rk3r) · X @_w0rk3r |
| **Ron Bitton** | Principal AI Security Researcher, Intuit; adversarial ML + guardrail-adherence benchmarks (VeganRibs); ex-Palo Alto; PhD | Israel | research/measurement > production eng; no cloud/policy; geo | [LinkedIn](https://il.linkedin.com/in/ron-bitton-phd-258096105) |
| **Thomas Patzke** | Cyber Security Analyst, Evonik; **co-creator of Sigma + author of pySigma** | Germany | no cloud/AI-agent proof; anchored to a job + beloved OSS; geo | thomas@patzke.org · GH [@thomaspatzke](https://github.com/thomaspatzke) |
| **Avi Lumelsky** | Security Researcher, Oligo; **MCP Inspector RCE (CVE-2025-49596)**, ShadowRay; secimport eBPF sandbox | Israel | offensive, not defensive detection-build; no policy; geo | [ports.sh](https://ports.sh) · X @avi_lum · GH avilum |
| **Luca Guerra** | Sr OSS Engineer, Sysdig; **Falco core maintainer** (approver) | EU (likely Italy) | no AI-agent; C++/Go not Python; co-maintainer not solo-shipper; geo | GH [@LucaGuerra](https://github.com/LucaGuerra) |
| **Nasreddine Bencherchali** | Sr Threat Researcher, **Splunk** (Cisco); **SigmaHQ Editor, ~1,800+ commits** (top-2 all-time) | EMEA (unconfirmed) | no cloud/AI-agent; community- not CISO-facing; US-first friction | X @nas_bench · Bluesky · GH [@nasbench](https://github.com/nasbench) |
| **Ads Dawson** | Staff AI Security Researcher, Dreadnode; **OWASP LLM Top-10 founding member + GenAI board**; AIRTBench | US/Canada | offense-weighted; no cloud/policy; expensive pull, mission-aligned to current employer | GH [@GangGreenTemperTatum](https://github.com/GangGreenTemperTatum) · [LinkedIn](https://linkedin.com/in/adamdawson0) |

## Tier C — situational (hire for one lane / advisor-first / probe before investing)

Natan Nehorai (JFrog, MCP CVEs — offensive) · Or Peles (JFrog, mcp-remote RCE — offensive) · Fukusuke Takahashi (NTT-CERT, Hayabusa engine — Japan) · **Nathan Hamiel** (Kudelski Sr Director — *manager-altitude flag*, advisor-first) · Mohamed Ashraf / X-Junior (Nextron SigmaHQ — Egypt) · Max Altgelt (Nextron, detection-engine builder — Germany) · Swachchhanda Poudel (Nextron detection eng — Nepal) · Federico Di Pierro (Cisco/Falco — Italy) · Nate Guagenti (Zeek/NSM — **current employer UNKNOWN, confirm first**) · **John Kastner** (AWS Cedar scientist — maxes policy-as-code but duplicates your strength + **AWS AgentCore non-compete/IP conflict flag**) · Ken Arora (F5 Distinguished Eng — credibility hire, detection unproven) · Craig Disselkoen (AWS Cedar scientist — duplicates strength, no detection) · **Gisela Hinojosa** (Cobalt — *IC drifting to manager*, red-team hire not CTO).

---

## Opening lines (copy-ready, line-1 hooks — each references their real proof)

- **Stemm:** "You wrote the detection engine that started life as 'Digwatch' and became Falco, and I see you've moved to eBPF enforcement on Tetragon — I'm building a neutral cross-vendor control plane that governs what AI agents are allowed to DO at runtime (block-before-execute + Cedar + deterministic signatures live today), and detection-science + shadow→enforce graduation is exactly the seat I need a co-founder for."
- **Harang:** "Your AI Kill Chain framework and the NVIDIA AI Red Team's LLM-security guidance are exactly the lens we're building around — AegionAI governs what an agent is allowed to DO at runtime, block-before-execute across any cloud. Our enforcement floor is live but the ML classifier is still in shadow; graduating shadow→enforce with disciplined FP/FN tuning is precisely the detection-science problem I'd want a founding security lead to own."
- **Rodriguez:** "Threat Hunter Playbook and OSSEM shaped how a generation writes detections — and your recent OTR work on LLM agents lands right on the seam I'm building: a cross-vendor runtime control plane that governs what AI agents are allowed to DO. I'm looking for a founding security engineer to own the detection science, and I'd value 20 minutes of your read on it."
- **Huang:** "I found you through your Falco rule work (the C2-outbound and setuid rules, and the whitelist tuning to keep FPs down); I'm building a cross-vendor runtime control plane that governs what AI agents are allowed to DO, and I need a detection lead who's actually shipped and tuned a signature corpus — which is exactly the shadow→enforce graduation problem I'm stuck on."
- **Dellaluce:** "Your Falco engine work (the exception-transformer and field-to-field-check refactors, not just rule authoring) is exactly the detection-science instinct I'm trying to build a runtime action-governance layer around; I'd value 20 minutes on where CNCF-grade runtime detection meets AI-agent action control."

(Tier-B/C hooks live in the workflow output at `tasks/wp4vbcpyf.output` if you want them verbatim.)

---

## Method + caveats
- **What "CONFIRMED" means here:** the person is real AND the proof_url credits *them* at a primary source AND they are an employed IC (not a founder). It does NOT re-confirm current employment (see standing rule) or fit_score (those are the dossier's, tiered not re-derived).
- **Sources blocked during research** (not read at a live primary source): LinkedIn HTTP 999 for many; X/Twitter HTTP 402 paywall for several; Di Pierro's LinkedIn 429; Bitton's OWASP "(core)" credit couldn't be clicked through (rests on self-description); **Dellaluce's AI-agent claim (T3MP3ST) was DISPROVEN — a GitHub star, not a contribution; do NOT repeat it to him**; Guerra's listed email domain guerra.sh does not resolve.
- **Do NOT deep-dive architecture with anyone until a mutual NDA + IP-assignment is in place** ([cofounder-search.md §6 disclosure ladder](../../cofounder-search.md#L227)). First call = problem + category only.
