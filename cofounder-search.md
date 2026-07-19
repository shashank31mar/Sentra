# Security Co-Founder Search — Sourcing + Vetting Engine (India + US)

**For:** AegionAI / Sentra founder · **Role:** full-time technical co-founder, genuine security specialist
**Date:** 2026-07-01 · **Status:** working playbook (personal founder artifact — move/delete as you like)

> **Read this first — honest scope.** LinkedIn cannot be scraped (auth + anti-bot wall) and there is no LinkedIn tool wired up, so this is **not** a scraped list of private SDE3s/PEs to cold-DM. It is: (1) the exact target profile, (2) the talent pools where these people sit, (3) copy-paste search strings **you** run inside LinkedIn/GitHub yourself, (4) a hard credential-validation rubric, (5) a verified list of *genuinely public* security figures (with citations) as **references / advisors / archetypes**, and (6) outreach + equity/legal guardrails. Every named person below was adversarially re-verified against primary sources; verdicts and caveats are stated.

---

## 1. The ideal profile — what to actually look for

**Recommended blend (weighted for THIS product + stage):**
- **~45% detection / runtime security** — Sigma/EDR/CrowdStrike-pattern, behavioral & sequence detection, shadow→enforce graduation, FP/FN tuning against real telemetry.
- **~35% cloud / infra security + policy-as-code** — multi-cloud IAM (AWS + Azure/GCP), Cedar/OPA, in-VPC/air-gapped deployment.
- **~20% AI/ML security** — prompt injection, tool-abuse, agent attack surface (OWASP LLM Top-10 level). Best as an *attribute* of the detection hire, not the hire's identity.

**Why this blend (not pure AI/ML security):**
- **Detection is your thinnest layer AND your biggest moat.** The ML classifier is still shadow, the signature corpus is small, and the "redacted-content recall-delta" is unmeasured. A detection co-founder owns the corpus, the shadow→enforce graduation, continuous red-teaming, and turns Moat 1 (the flywheel) from a slide into a moat.
- **You can't self-assert security credibility to a bank CISO.** A solo ex-Amazon platform builder builds the plane; a co-founder with a real, public security track record (CVEs, talks, OSS, named roles) is the procurement de-risker. This is literally your STRATEGY §8 open question #3.
- **Cloud/infra is reinforcement, not the lead** — you already cover AWS/CDK/infra from Amazon. A pure cloud-IAM architect would *overlap* your strength and leave the detection + credibility gap open.
- **You compete on stateful action governance, not stateless prompt scoring** — so a pure adversarial-ML researcher is aimed at the layer you treat as table-stakes. AI/ML security is the smallest slice.

**One-line target:** a *detection/runtime security engineer who can talk to a bank CISO* — not a research scientist, not a pure cloud-IAM architect, not a compliance officer.

### Archetypes (best → situational)
1. **Detection engineer / threat researcher** from a modern EDR/D&R vendor (CrowdStrike, SentinelOne, Palo Alto Cortex, Elastic, Sysdig/Falco, Datadog; India: CrowdStrike Blr/Pune, Palo Alto India, Sophos, Uptycs Blr, Securonix, Gurucul). **Closest 1:1 fit.**
2. **Cloud/runtime security engineer w/ policy-as-code** from a CNAPP vendor (Wiz, Orca, Sysdig, Aqua, Snyk; India: Wiz Blr, Aqua India, Rapid7, Qualys Pune). Reinforces Moat 2; primary only if they also have detection instinct.
3. **Appsec/product-security lead from fintech/payments** (Stripe, Brex, Plaid, Adyen; India: Razorpay, PhonePe, CRED, Juspay, Zerodha). Best regulated-buyer credibility; pair with detection depth.
4. **AI/ML security researcher** (Robust Intelligence/Cisco, HiddenLayer, Lakera, Protect AI, frontier-lab red teams). Supporting strength, not sole co-founder.
5. **Ex-security-startup founder / founding security engineer** (acquired-startup alumni, YC/seed security alumni, detection-tooling maintainers). **Rare, best single fit** — covers build + 0→1 + credibility at once.

### Must-have · Anti-signal · Deal-breaker (screening filters)
**Must-have:** full-time co-founder appetite (not advisor); has personally shipped production detection content/pipeline that *enforced*; publicly-attestable security credibility a regulated buyer accepts; working fluency in policy-as-code + multi-cloud IAM; modern LLM/agent-security literacy; strong Python (the whole PDP is Python); fail-secure/deny-by-default instinct + discipline to graduate ML on *measured* evidence.

**Anti-signal (looks impressive, wrong fit):** pure GRC/compliance with no engineering; pure adversarial-ML researcher with no shipping/buyer experience; cloud-IAM architect who only duplicates your AWS strength; "AI security" resume that's really prompt-engineering; big-co security *manager* who hasn't shipped code in years; advisor/fractional mindset; anyone who leads with "we block inline" as the differentiator.

**Deal-breaker:** can't commit full-time; zero verifiable security credibility; won't write/review code; **fabricated or unverifiable credentials** (existential for a company selling trust to banks); rejects fail-secure / honest-staging posture.

---

## 2. Talent pools — where the person actually is

### India (primary)
| Pool | Why | Where to find |
|---|---|---|
| EDR/D&R R&D centers — CrowdStrike (Blr/Pune), Palo Alto Cortex (Blr), Sophos (Ahmedabad/Blr), Securonix, Gurucul | Closest to the top archetype; ships enforcing detection at scale | LinkedIn title+company+metro; Nullcon/BSides speaker rosters; company GitHub orgs |
| India security-product startups w/ real detection/XDR IP — Sequretek, CloudSEK, Uptycs (Blr), SAFE Security | Founding engineers = 0→1 build + public identity + co-founder economics | LinkedIn "founding engineer"; Inc42/YourStory coverage; Blr alumni; Nullcon/c0c0n |
| CNAPP eng — Wiz India, Aqua India, Rapid7, Qualys (Pune), Traceable | Moat-2 reinforcement (multi-cloud IAM, Cedar/OPA) | LinkedIn cloud-sec + metro; OPA/Cedar GitHub contributors; Blr CNCF meetups |
| Fintech product-sec & fraud-risk — Razorpay, PhonePe, CRED, Juspay, Zerodha, Pine Labs | Regulated-buyer credibility + "enforcement above identity"; PCI/RBI/SOC 2 scars | LinkedIn "product security"/"fraud risk eng" + Blr; OWASP India |
| OWASP GenAI / LLM-security community (India chapters + Agentic Security Initiative) | Sources the LLM/agent-security literacy must-have; self-selected + public | OWASP Slack, genai.owasp.org/contributing, OWASP India events |
| Offensive/red-team community — Nullcon (Goa), c0c0n (Kerala), BSides, CTF/bug-bounty leaderboards | Red-team depth + verifiable public identity (CVEs, talks) | Nullcon/c0c0n archives; HackerOne/Bugcrowd India; NVD CVE authorship |

### US (secondary)
Same archetype sources at the source: **EDR/D&R vendors** (CrowdStrike, SentinelOne, PA Cortex, Elastic, Sysdig, Datadog, Expel, Red Canary) · **AI/agent-security startups** (Zenity, HiddenLayer, Lakera→Check Point, Protect AI→PANW, Robust Intelligence→Cisco, Invariant→Snyk, CalypsoAI→F5, Straiker) — *note competitor-hire conflict/non-compete* · **CNAPP + policy-as-code** (Wiz, Orca, Sysdig, Aqua, Snyk) · **fintech product-sec** (Stripe, Brex, Ramp, Plaid, Adyen, Block) · **OWASP GenAI leadership + AI Village/MLSec** · **frontier-lab safety/red-team** (Anthropic, OpenAI, Google DeepMind — advisor pool, hardest to poach).

### India-vs-US tradeoffs (the decision)
- **Buyer proximity is the biggest factor.** Your economic buyer (US/enterprise bank CISOs) is US-concentrated, and US-buyer credibility is exactly what you lack. A US co-founder shortens that distance.
- **Talent depth & cost:** India has deep detection/EDR IC benches at a fraction of US comp (matters less for equity than salary, but still). US has the densest AI/agent-security-startup alumni + frontier red-teamers at higher equity expectations.
- **Time zones:** India↔US is a hard ~12h offset that taxes daily pairing; India-India or US-US co-location is materially easier at pre-seed. If split, bias to senior, async-self-directed candidates.
- **Visa:** if you want them physically in the US, that's a real constraint for an India hire (H-1B lottery / O-1 for genuinely public researchers) — favors either an India candidate with existing US authorization, or remote-in-India + you fronting US meetings.
- **Credibility transfers across geography** (a verifiably public India researcher carries weight with a US CISO). **Prioritize publicly-attestable credibility over location** — it's the load-bearing must-have.

**Recommendation:** source detection depth from both geos (India = cost/depth efficient for the flywheel lane), but weight the *credibility-carrying* candidate toward whoever is closest to the US buyer OR carries a portable public security identity.

---

## 3. Sourcing engine — search strings you run yourself

**Golden rule:** DISCOVER on open web / GitHub / CFP archives (where credibility is *provable*), THEN qualify + contact on LinkedIn. Do not start on LinkedIn — you'll get title-matchers, not proven detection builders.

### LinkedIn boolean (paste into Sales Nav/Recruiter Keywords; move company names to the Company filter for cleaner results)

**Detection/threat-research — India:**
```
("detection engineer" OR "detection engineering" OR "threat detection" OR "threat research" OR "security researcher" OR "EDR") AND ("detection rules" OR "behavioral detection" OR "anomaly detection" OR Sigma OR YARA OR "detection content") AND (CrowdStrike OR SentinelOne OR "Palo Alto" OR Cortex OR Elastic OR Sysdig OR Falco OR Uptycs OR Securonix OR Gurucul OR Sophos OR "Arctic Wolf") AND (India OR Bengaluru OR Bangalore OR Pune OR Hyderabad OR Gurgaon OR Noida)
```
**Detection/threat-research — US:**
```
("detection engineer" OR "detection engineering" OR "threat researcher" OR "threat detection" OR "security research engineer") AND ("detection rules" OR "behavioral detection" OR "detection content" OR Sigma OR "shadow mode" OR "false positive") AND (CrowdStrike OR SentinelOne OR "Palo Alto Networks" OR Cortex OR "Elastic Security" OR Sysdig OR Datadog OR Expel OR "Red Canary") AND ("United States" OR Austin OR "San Francisco" OR "New York" OR Boston OR Denver OR Seattle OR remote)
```
**Cloud/runtime + policy-as-code — India:**
```
("cloud security" OR CNAPP OR "runtime security" OR "workload protection" OR "Kubernetes security") AND ("policy as code" OR OPA OR Rego OR Cedar OR authorization OR IAM) AND (Wiz OR Orca OR Sysdig OR Aqua OR Lacework OR Snyk OR Rapid7 OR Qualys OR Traceable OR Uptycs) AND (India OR Bengaluru OR Bangalore OR Pune OR Hyderabad)
```
**Fintech appsec / regulated-buyer credibility — India:**
```
("application security" OR "product security" OR appsec OR "security engineering" OR fraud OR "risk engineering") AND ("money movement" OR payments OR fintech OR PCI OR "SOC 2" OR RBI) AND (Razorpay OR PhonePe OR CRED OR Juspay OR Zerodha OR "Pine Labs" OR Stripe OR Plaid) AND (India OR Bengaluru OR Bangalore OR Mumbai OR Hyderabad)
```
**AI/LLM security (supporting strength):**
```
("AI security" OR "LLM security" OR "ML security" OR "prompt injection" OR adversarial OR "AI red team" OR "agent security") AND (OWASP OR jailbreak OR guardrails OR "red teaming") AND (HiddenLayer OR Lakera OR "Protect AI" OR "Robust Intelligence" OR Microsoft OR Google OR AWS) AND (India OR Bengaluru OR Bangalore OR Hyderabad OR remote)
```
**Ex-founder / founding security engineer (both geos; add Sales Nav "Years in current company" ≤3):**
```
("founding engineer" OR "founding security engineer" OR co-founder OR founder OR "first security hire") AND (detection OR threat OR "security research" OR appsec OR CVE OR OSS) AND (security OR cybersecurity) NOT (marketing OR sales OR recruiter)
```
**Credibility-first cut (surface people whose profile names public proof):**
```
("CVE-" OR "assigned CVE" OR "Black Hat speaker" OR "DEF CON" OR Nullcon OR c0c0n OR BSides OR "open source maintainer" OR "detection rules author") AND (security OR detection OR threat OR appsec)
```

### GitHub queries (prove they *ship*, then crosswalk to LinkedIn)
- **Sigma authors:** `github.com/SigmaHQ/sigma/graphs/contributors` — then git-blame the `rules/` tree.
- **Own-repo Sigma rules:** `github.com/search?q=%22logsource%22+%22detection%22+%22condition%22+language%3AYAML&type=code`
- **Falco (CNCF runtime) rules:** `github.com/falcosecurity/falco/graphs/contributors`
- **Cedar policy authors (your exact engine):** `github.com/cedar-policy/cedar/graphs/contributors` + code search for `permit(` + `principal`/`action`/`resource`.
- **OPA/Rego authors:** `github.com/search?q=%22package+%22+%22default+allow%22+extension%3Arego&type=code`
- **LLM/agent-security tooling:** `github.com/search?q=%22prompt+injection%22+OR+%22llm+security%22+OR+jailbreak+security&type=repositories&s=stars`
- **OWASP GenAI contributors:** `github.com/orgs/genai-security-project/people`
- **Nuclei templates (big India OSS-sec community):** `github.com/projectdiscovery/nuclei-templates/graphs/contributors`
- **India-located contributors:** `github.com/search?q=location%3AIndia+security+detection&type=users` (+ `location:Bengaluru` / `Pune` / `Hyderabad`).

### Conferences (mine speaker/CFP archives; a talk title is a free credibility artifact for outreach)
- **India:** Nullcon (Goa; site bot-blocks, browse manually) · c0c0n (Kochi; 2026: Oct 6–13, CFP closes 10 May 2026, accepted list ~Aug 2026) · Seasides (Goa; Feb 19–21 2026, free) · BSides Bangalore/Delhi/Ahmedabad.
- **US:** DEF CON (villages: AI/Red Team/Cloud/Adversary — exactly your stack) · Black Hat USA (enterprise-credibility Briefings) · BSides (100+ chapters) · SANS instructor roster (curated senior detection specialists).
- **Both:** OWASP Global AppSec + local chapters.

### Communities (warm-intro engines, not just lists)
OWASP GenAI Security Project (Agentic App Security + AI Red Teaming WGs — closest to your thesis) · SigmaHQ + Detection Engineering Weekly community · Falco/CNCF Slack · Cedar policy GitHub · **null** + OWASP India chapters (best in-person India channel) · MITRE ATT&CK / Center for Threat-Informed Defense.

### Workflow tips
- **Sales Nav setup (cheaper than Recruiter):** boolean in Keywords → hard-filter Geography + Current Company (paste vendor list) + Seniority (Senior/Staff/Principal/Founder) + Years-in-company ≤3 → save each archetype as a Saved Search with weekly alerts.
- **GitHub→LinkedIn crosswalk (highest-signal move):** find a proven detection-content author via a contributor graph → their GitHub profile gives real name + company + site/Twitter → search "Name + Company" on LinkedIn → reference a *specific PR of theirs* in line 1 of outreach.
- **Score before contacting** against the must-haves; screen out anti-signals hard.
- **Verify before you invest a conversation:** confirm every credential at its primary source (CVE on NVD, talk on the conference archive, commits on the contributor graph). For a company selling trust to banks, unverifiable credibility is a disqualifier, not a maybe.
- **Single tracking sheet keyed by person:** name · archetype · proof-URL(s) · employer · geo · full-time-likelihood · channel · status. Derive the pipeline from **proof-URLs, not resumes**.

---

## 4. Credential-validation rubric — hard vetting

Score each dimension **0–5 on VERIFIED evidence only** (unverifiable claim = 0, not benefit-of-the-doubt). Weighted /100.

| # | Dimension | Weight | How to verify (primary artifact) |
|---|---|---|---|
| 1 | Detection/exploit/offensive depth | 20% | CVE credited to *them* on NVD/MITRE (read the advisory credit line); HackerOne/Bugcrowd public profile; CTFtime standing; GitHub-published PoCs / Sigma/YARA rules git-blamed to them; can whiteboard a real injection/param-abuse chain |
| 2 | Cloud + IAM/authorization depth | 20% | Merged PRs to Cedar/OPA/cloud scanners; can articulate deny-overrides vs permit-overrides, confused-deputy, IMDSv1 SSRF, wide OIDC audiences; real >1-cloud production stories (not just certs); hand them a broken IAM/Cedar policy to find the fail-open |
| 3 | OSS/CVE/patent/publication trail | 10% | Papers on arXiv/DBLP (named author, real venue); **granted** patent by number on Google Patents (named inventor); sustained git-blameable merged PRs — down-weight anything you can't click through |
| 4 | Systems/engineering ability (co-owns the PDP) | 20% | Read their public code for tests + fail-secure defaults; **paid trial**: Cedar policy + its fail-secure test, or a Sigma rule + corpus — do they write the test that *proves* the control, or just assert it? |
| 5 | Enterprise/regulated-buyer credibility | 15% | Actually stood up/audited SOC 2 Type II / ISO 27001 / HIPAA (specific controls + auditor interactions); verifiable senior role; ask them to threat-model *your* architecture and name the right controls |
| 6 | Co-founder soft skills, integrity & commitment | 15% | Backchannel references (managers, not just friends); every public claim checks out exactly; disagrees well; genuinely bought into the thesis |

**Interpretation:** ≥80 = strong, proceed to paid trial + references · 65–79 = promising with a gap (engineering is coachable, integrity is not) · <65 = pass or role is advisor/hire.

**Hard gates (any one fails = automatic pass):** (a) any *verified* resume misrepresentation; (b) dimension 4 <2 (can't ship tested code — this is a builder role); (c) both dimension 1 AND 2 <2 (no verifiable security depth). Require at least one of dims 1/2/3 to score ≥4 on primary-sourced evidence. **Tests/trial-PR outrank interview impressions and the resume.**

### Catching fake/inflated creds
- **Title inflation:** "CISO/Head of Security" at a 5-person startup managed no one — check headcount + tenure vs founding date; a 6-month "Head of Security" is a flag.
- **"Contributed to a CVE":** demand the ID, open NVD, read the credit line. Patching/scanning/triaging ≠ discovering. Not named as reporter = inflated.
- **Cert-collector:** wall of CISSP/CEH/OSCP/AWS-Security with zero public code/CVEs/talks. Certs prove exam-passing, not novel-bug-finding. (OSCP is the most hands-on — still ask for a write-up.)
- **Ghost GitHub:** green graph that's mostly forks, README edits, dep bumps, stars. `git log --author` / click into PRs — real work is merged, substantive, git-blameable.
- **Buzzword resume:** "zero-trust, AI-native, ATT&CK, XDR, SOAR" with no mechanism. Make them name real field/rule/bug-class names; vague framework-speak dissolves under one "how exactly?"
- **Unverifiable body of work:** papers not on DBLP/arXiv, "patent pending" with no number, employers/customers with no footprint → zero weight.
- **AI-security theater:** claims "prompt-injection expertise" but can't name garak/PyRIT/Rebuff/LLM-guard, the OWASP LLM Top-10 items, or why a deterministic param-bound check beats a prompt classifier for a money-moving action.
- **Borrowed credibility:** name-drops famous employers/cons but every probe returns "confidential." Real practitioners discuss bug classes/controls/architecture without breaching NDA.

### Reference-check questions
- "Did they *personally* discover the CVEs on their resume, or was the team responding? Which were theirs?"
- "Would you have trusted them to design a fail-secure authorization control a bank's security team would sign off on? Seen them do it?"
- "When a code review or failing test proved them wrong, how did they react?"
- "Have they shipped and *operated* a security-critical service — on-call, incidents, postmortems — or hand off to engineers?"
- "Was their title reflective of actual scope/team, or a small-company title?"
- "Did they ever round up a credential, customer name, or result — even a little?" (for a co-founder, one yes is disqualifying)
- "Genuinely full-time available, no competing venture / conflicting non-compete?"
- To candidate: "Walk me through the single hardest bug you personally found — target, bug class, write-up. Send me the public advisory/CVE link." (a real one has a URL; a fake one has a story)
- To candidate: "Design the deterministic control that stops an agent wiring \$2M when policy allows \$50k — where does it fail open?" (tests fail-secure action-governance thinking vs prompt filtering)

---

## 5. Verified public experts — references / advisors / archetypes (NOT a cold-DM co-founder list)

**How to read this:** every person was adversarially re-verified against primary sources. **CONFIRMED** = real public person, load-bearing creds independently verified. **PARTIAL** = real person but ≥1 claim couldn't be independently confirmed or was misstated (noted). Most are founders/execs/famous researchers → treat as **learn-from / warm-intro / advisor** targets, not recruits. Your actual co-founder comes from §3 search strings run against §2 pools.

### India-based (primary geography)

> **❌ CROSSED OFF as co-founder candidates (2026-07-07).** Every named person below is **already a founder / CEO / CTO / employed exec** — none is recruitable as a full-time co-founder. Keep them ONLY as **advisors, references, and warm-intro nodes into their networks.** Do not spend a co-founder ask here.
>
> **~~DECISION (2026-07-07): drop India as a co-founder geography — weight US.~~ SUPERSEDED 2026-07-19 — see below.** Original rationale: the economic buyer (US/enterprise bank CISOs) is US-concentrated, US-buyer credibility is exactly the gap the co-founder must close, and the ~12h time-zone offset taxes daily pairing at pre-seed. Source the co-founder from the **US pools in §2** via the §3 US search strings. India names here remain **advisors / warm-intro nodes only.**
>
> **DECISION (2026-07-19, supersedes the 2026-07-07 call): the CTO co-founder MUST be India-based.** Founder rationale: the engineering team is in India, and a CTO in a ~12h-offset US timezone would make the team's daily connection/pairing a standing challenge — co-location beats buyer-proximity at pre-seed. US-CISO credibility is de-risked separately (a GTM partner carries the funding/design-partner front; a US credibility-advisor can be added). **The one requirement that survives from the 2026-07-07 call:** the India CTO's public proof must be **portable / US-CISO-legible** (CVEs on NVD, Nullcon/Black Hat/DEF CON talks, git-blameable OSS in globally-known projects, published research) — per line 61, credibility transfers across geography. Source from the **India pools in §2** via the §3 India search strings; reachable-candidate shortlist in [pitch/internal/cofounder-shortlist.md](pitch/internal/cofounder-shortlist.md) (US pool) + the India shortlist run 2026-07-19.

| Name | Role | Specialty | Verdict | Use as | Key caveat |
|---|---|---|---|---|---|
| **Anant Shrivastava** | Founder, Cyfinoid Research | Supply-chain + multi-cloud (AWS/Azure/GCP) + CI/CD security; Black Hat/DEF CON/Nullcon trainer & CFP reviewer | **CONFIRMED** | Advisor / archetype / network node | Black Hat-specific billing self-reported (DEF CON 2026 training independently confirmed) |
| **Akash Mahajan** | Founder & CEO, Kloudle; founder Appsecco | "Sovereign CSPM that runs in your own network" (AWS/GCP/Azure/K8s) + now building AI agents | **CONFIRMED** | Advisor — his in-VPC/cross-vendor thesis mirrors yours | Former (2012–17) OWASP Bangalore leader, not current; already a founder |
| **Abhay Bhargav** | Founder/CEO we45 & AppSecEngineer | Appsec, DevSecOps, threat modeling, **agentic/MCP/RAG AI-pentesting** | **CONFIRMED** | Advisor — closest to your AI-agent threat surface | Already a founder; RSA-trainer claim self-reported; OSS repos modest |
| **Ananda Krishna** | Co-Founder & CTO, Astra Security | Product-sec eng — WAF/DAST/scanner built end-to-end; OWASP GenAI contributor | **CONFIRMED** | **Best India co-founder archetype**; benchmark / reference (already a founder) | "CTO/15+ yrs" self-reported; co-founder status confirmed via Inc42 |
| **Harsh Bothra** | Independent offensive-sec; ex-Cobalt Core | Web/API/mobile/cloud pentest; **claims** agentic/LLM testing | **PARTIAL** | Red-team / detection-hardening counterpart | The AI/ML-pentester cert + agentic claim is self-asserted only — the most load-bearing item is unproven |
| **Vandana Verma Sehgal** | Security Relations Leader, Snyk | AppSec + agentic-AI security; OWASP GenAI contributor; huge community reach | **PARTIAL** | Amplification / referral node | "Vice Chair, OWASP Global Board" is **stale/incorrect** — not a current board member per board.owasp.org |

### US-based (secondary) — detection engineering
| Name | Role | Specialty | Verdict | Use as |
|---|---|---|---|---|
| **Jared Atkinson** | CTO/Chief Strategist, SpecterOps | **Functional/behavioral detection** — decomposing what an action DOES (the "On Detection" series, Funnel of Fidelity) | **CONFIRMED** | Top advisor/archetype — his thesis ≈ your action-level governance |
| **Roberto Rodriguez** (Cyb3rWard0g) | Researcher, NVIDIA (ex-Microsoft MSTIC); founder OTRF | Data-driven detection, reproducible attack datasets (HELK, ThreatHunter-Playbook, OSSEM, Security-Datasets) | **CONFIRMED** | Advisor — exactly the discipline for building/validating your detection corpus |
| **Zack Allen** | Sr Director Security Research, Datadog | Detection-engineering leadership, detection-as-code; runs Detection Engineering Weekly | **CONFIRMED** | Distribution/awareness node + program credibility |
| **Josh Liburdi** (jshlbrd) | Detection eng; creator of Substation | **Detection eng + high-throughput data pipelines/distributed systems** | **CONFIRMED** | **Strong technical co-founder archetype** — rare detection+pipeline mix for your inline path |
| **Anton Chuvakin** | Security strategy, Google Cloud (ex-Gartner Distinguished Analyst) | SIEM/SecOps/detection-&-response strategy; how enterprise buyers evaluate detection | **CONFIRMED** | Advisor — buyer-evaluation authority |

### US-based — AI / agent / ML security
| Name | Role | Specialty | Verdict | Use as |
|---|---|---|---|---|
| **Steve Wilson** | CPO, Exabeam; founder OWASP GenAI/LLM Top 10 | The reference framework enterprise buyers map controls to; O'Reilly author | **CONFIRMED** | Top warm-intro/advisor; network hub (400+ contributors) |
| **Simon Willison** | Independent; co-creator Django, creator Datasette | **Coined/popularized "prompt injection"; "lethal trifecta"** framing | **CONFIRMED** | Thought-partner/advisor — maps onto your deny-overrides/fail-secure design |
| **Johann Rehberger** (wunderwuzzi) | AI red teamer; Embrace The Red | Practical breaker of coding/action agents (Cursor, Amazon Q, Claude Code, Copilot; Gemini memory; ZombAI/SpAIware) | **CONFIRMED** | **Co-founder-caliber offensive AI specialist**; red-team credibility |
| **Ads Dawson** (Adam Dawson) | AI-sec researcher, Dreadnode; OWASP GenAI Board/Tech Lead | Autonomous AI red-teaming (AIRTBench), model sandboxing; standards leadership | **CONFIRMED** | **Rare build + standards combo** — closest to a hire-able AI-sec co-founder profile |
| **Nicholas Carlini** | Research Scientist, Anthropic | Adversarial ML, training-data extraction, poisoning, model stealing | **CONFIRMED** | Advisor/validation reference (unlikely to move) |
| **Andy Zou** | PhD, CMU; CTO/co-founder Gray Swan AI | Transferable adversarial attacks (lead author GCG); jailbreak/robustness | **PARTIAL** | Advisor; his student-tier is the hireable pool | "Lead author of HarmBench" is **wrong** (4th of 12; Mazeika is lead) |
| **Zico Kolter** | Professor/Director ML Dept, CMU | Robust/safe deep learning; senior author GCG | **CONFIRMED** | Top-tier advisor + PhD-talent pipeline (too senior to recruit) |

### Policy-as-code (Cedar/OPA — your engine layer)
| Name | Role | Specialty | Verdict | Use as |
|---|---|---|---|---|
| **Tim Hinrichs** | Apple (via Styra acquihire); co-creator OPA, ex-CTO Styra | Policy-language semantics, declarative policy design | **CONFIRMED** | Advisor on policy-engine architecture + Cedar-vs-Rego (AD-2) |
| **Torin Sandall** | Engineering, Apple; co-creator OPA | OPA/Rego engine internals, enforcement, shadow→enforce rollout | **PARTIAL** | Advisor on policy-engine depth | "Co-founder of Styra" overstated — he was **VP Eng/Open Source**; co-creator of the OPA *project* |

### Cross-geo AI-agent-governance founder (region uncertain)
| Name | Role | Specialty | Verdict | Use as |
|---|---|---|---|---|
| **Madhu Akula** | Founder (madhuakula.com); ex-Product Security Miro | Cloud-native/K8s/container security, policy-as-code (OPA/Rego); creator Kubernetes Goat | **CONFIRMED** | Advisor/archetype — now Netherlands-based (region Other), not primary |
| **Vishwas Manral** | Founder & CEO, Precize (AI/agent governance); ex-McAfee; IETF RFC author | Cloud-native + AI/agent security; standards | **PARTIAL** | Network node into AI-sec founder/OWASP community | Region uncertain; McAfee role + IETF-author↔Precize-CEO identity link are inferences |

**Reality check on this list:** the India names are mostly *already founders* (Anant, Akash, Abhay, Ananda) or independent/employed (Harsh, Vandana) — high-value as **advisors, references, and warm-intro nodes into their networks**, not as people who'll drop everything to co-found. The US names are references/advisors/archetypes. **Do not** cold-DM this list "be my co-founder." Do use them to: (a) learn what "real" looks like, (b) get warm intros to *their* movable colleagues, (c) recruit an advisor who lends immediate credibility. Your actual co-founder hunt runs through §3 search strings on §2 pools.

---

## 6. Outreach + equity + legal

### Disclosure ladder + when to NDA (protecting the idea without strangling the search)

> **Governing principle:** the cost of *over-guarding* (never finding a co-founder → can't sell to regulated buyers → company stalls) is **existential**; the cost of a leaked idea (someone gets a head start on a category where you hold a ~12-month build lead + a patent priority date) is **survivable and unlikely.** More founders die from secrecy than from a stolen pitch. **Talk. Stage what you reveal.**

**What actually protects you (strongest → weakest):**
1. **Patent-pending priority date** — the filing already protects the *invention*; a later copier can't jump your priority date. *(Confirm with counsel whether it's provisional or non-provisional + the exact date; if provisional, the 12-month conversion deadline is a hard diary item.)*
2. **Execution, not the idea** — ~26K LOC of working system + deterministic Cedar/Sigma floor + the data flywheel. Nobody clones 12 months of build from a conversation. The patent is *explicitly not the moat* (per STRATEGY / investor-Q&A); execution is.
3. **Staged disclosure** (you control depth):
   - **First call:** problem + category only ("we govern agent *actions* across clouds"). Already public in the one-pager/deck/LinkedIn → zero incremental risk.
   - **Getting serious:** architecture at a high level. Still not enough to clone.
   - **Before a paid trial / deep technical dive:** *now* paper it (NDA + IP-assignment — see below).
   - **Genuinely proprietary internals** (exact detection corpus, sequence-integrity mechanism, flywheel specifics): only after a real working relationship exists.
4. **NDA at the right moment** — [pitch/legal/AegionAI-NDA.pdf](pitch/legal/AegionAI-NDA.pdf).

**When to NDA (the nuance that matters):**
- **Investors / angels / connectors (Randy, Paul, Jeff, VCs): NEVER ask for an NDA before a pitch.** It's a red flag and most refuse — they see hundreds of adjacent ideas. Rely on staged disclosure instead.
- **Co-founder candidate entering a technical trial: YES — always.** Mutual NDA **+ an IP-assignment / work-for-hire clause in the consulting/trial agreement**, before any deep architecture dive or code access. This is the real protection point — not the first call. (Cross-border caveat if the person is in India but the co is US: FEMA / IP-assignment quirks — see the Legal subsections below; get coordinated counsel.)

**Who NOT to pitch deeply:** never walk a *fellow founder/CEO in an adjacent space* through your architecture — they have the means, motive, and freedom to fold it into their roadmap. This is exactly why the co-founder search sources **employed ICs**, not other founders (an employed detection engineer has far less freedom to run off and clone you), and why the §5 named founders are advisors/intro-nodes only.

**Not legal advice** — a 30-min startup-attorney consult before your first trial (NDA + IP-assignment + provisional-conversion deadline) is cheap insurance.

### Outreach (drafts — never auto-send; personalize line 1 with a *specific* proof point)
Six templates live in the workflow output: cold email to a **detection engineer**, cold email to a **fintech appsec lead**, a **warm-intro request** (with a forwardable blurb), **follow-up #1** (one new proof point, softer), **follow-up #2** (graceful close), and **post-first-call → propose a paid trial before equity**. Core pattern in every one: proof over hype, name the specific gap they'd own (detection science + flywheel + buyer credibility), sign **"Founder, AegionAI"**, soft 25-min ask, easy out. (Full text in the appendix file if you want them verbatim — say the word and I'll drop them into a `outreach-drafts.md`.)

### Equity (recommendation — not legal/tax advice)
- **Framing:** a co-founder joining *after* you built the working product is **not** a 50/50 default — you've retired the idea, ~12+ months of build, and product risk. But they're a genuine co-founder (full-time, co-owning a moat + the credibility that unblocks regulated buyers), so the number must read "co-founder," not "senior hire."
- **Range: 15–35%, with 20–30% the defensible band** for a strong full-time security co-founder at de-risked pre-seed. Push to **30–35%** if they bring named buyer credibility that directly unblocks bank procurement, take real cash-comp risk, and own a whole moat. Push to **15–20%** if they need meaningful salary, join later, or overlap your existing strengths.
- **Vesting for BOTH of you:** standard 4-year vest / 1-year cliff / monthly. Negotiate **vesting credit** for your already-served time (e.g. 12–18 months treated as vested at close) — normal and investor-accepted. Add **double-trigger** acceleration (not single), a reverse-vesting/repurchase right, written roles + tie-break decision rights, and do **not** hand over a large instantly-vesting chunk.
- **Sequence:** trial project FIRST → agree number + roles SECOND → paper it (grant + vesting + IP assignment) THIRD. Never verbally promise "30%" before the trial.

### Legal — India (general orientation, NOT legal advice; engage an Indian startup lawyer + CA)
- **Entity:** Private Limited Company (Companies Act 2013) is the fundable vehicle; LLP is unsuitable for equity/ESOP raising. If you'll raise from US/global VCs, a "flip" to a Delaware C-corp parent + Indian subsidiary is common but has RBI/FEMA + tax consequences — **decide top-co jurisdiction before issuing co-founder equity** or you re-paper it.
- **IP assignment (most important):** written IP-assignment agreement covering everything you've already built AND everything the co-founder creates; during any pre-incorporation trial use a consulting/contractor agreement that assigns work-product IP (Copyright Act 1957 s.17–19 — non-employment IP vests in the author unless assigned in writing).
- **Equity vs ESOP:** a true co-founder holds **actual equity shares**, not ESOP options. Founder-share vesting in India is typically implemented via reverse-vesting / share-repurchase in the founders'/shareholders' agreement (no exact US "restricted stock" construct) — counsel structures the mechanism.
- **Founders' Agreement:** equity split, vesting/reverse-vesting, roles, IP, confidentiality, non-solicit (broad post-termination non-competes are often unenforceable — Contract Act s.27, so lean on IP + confidentiality + non-solicit), good/bad-leaver, dispute resolution.
- **Tax flag (get a CA):** share issuance can trigger sweat-equity / s.56(2) angel-tax-type valuation concerns — not automatically tax-free. Check DPIIT/Startup India eligibility for relief.

### Legal — US (general orientation, NOT legal advice; use a startup lawyer + tax advisor)
- **Entity:** Delaware C-corp is the venture default.
- **Instrument:** co-founder equity = **restricted stock** with a repurchase right lapsing on the vesting schedule.
- **⚠️ 83(b) election:** file with the IRS **within 30 days** of grant — the single most common costly miss. Taxes value at grant (~zero for early founder stock) instead of as it vests; the deadline is strict and unfixable. Both founders file; each confirms with a personal tax advisor.
- **IP assignment:** every founder signs a CIIAA/PIIA; explicitly assign the already-built product into the company; consulting agreement w/ work-for-hire + IP clause during any trial.
- **Docs packet:** Restricted Stock Purchase Agreement, board/stockholder consents, 83(b) filing, CIIAA. Double-trigger acceleration is market-standard. Clerky/Atlas/Carta templates + a lawyer for co-founder-specific terms.
- **⚠️ Cross-border:** if the co-founder is in India but the company is a US C-corp, equity to a non-US person raises FEMA/withholding/permanent-establishment questions on both sides — get coordinated US + India counsel, not routine.

### The co-founder "dating" process (before any equity)
1. **Screen the two non-negotiables:** full-time co-founder appetite + verifiable credibility (quietly confirm CVEs/talks/OSS at primary sources).
2. **2–3 unstructured thesis/values conversations:** do they lead with "we block inline" (anti-signal) or with detection science + measurement? Do they share the fail-secure / honest shadow→enforce posture?
3. **Scoped PAID trial (2–4 weeks, part-time) on a REAL slice:** e.g. design + run a shadow→enforce graduation with a real recall/FP readout; or expand the signature corpus vs a held-out set and report numbers; or red-team the current pipeline and write up what gets through. **Deliverable must be a number + a judgment, not a doc.**
4. **Evaluate on four pre-written axes:** technical depth (moved the detection frontier?), judgment under ambiguity (measured honestly, incl. bad news?), collaboration (how they disagree), buyer-credibility signal (could you put them in front of a CISO?). Check they *close* your gap, not duplicate your AWS/infra strength.
5. **Pressure-test the partnership:** hard scenarios (quit in year 2, down round, enforce-vs-shadow disagreement, decision rights). Reference calls on integrity + behavior under stress. Agree tentative roles + tie-breaker before any number.
6. **Only after a successful trial:** agree number + vesting → paper everything together with a lawyer. First-call-to-signed ≈ **6–10 weeks**.
7. **Have an honest "no" path:** a wrong co-founder with 25% + a cliff is far more expensive to unwind than a great contractor. Pay for the trial, keep it warm (referrals), move on.

---

## Sources & method
Built by a multi-agent research workflow (38 agents): profile → parallel research (pools/search-strings/rubric/outreach) → 5 region×specialty expert finders → **adversarial per-person verification** against primary sources (GitHub API, NVD, arXiv/DBLP, OWASP, conference pages, company/institution pages). 28 candidates found; those that survived refutation are in §5 with verdicts + caveats. Company-specific India-office/acquisition facts labeled [INFERENCE] in the raw output must be re-verified on each candidate's LinkedIn before outreach (several careers pages were JS-rendered / 403 / 429 during research).
