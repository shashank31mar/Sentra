# Security Co-Founder — India-Based Candidate Shortlist

**For:** AegionAI / Sentra founder · **Companion to:** [cofounder-search.md](../../cofounder-search.md), [cofounder-shortlist.md](cofounder-shortlist.md) (US pool)
**Date:** 2026-07-19 · **Status:** working shortlist — 19 India-based, confirmed-recruitable (is_founder=false) ICs.

> **Why this list exists.** Founder decision 2026-07-19: the CTO must be **India-based** (team is in India; a ~12h US offset breaks daily pairing). The first sourcing run found zero India names because its sources skewed Western; this run mined India-specific pools (India R&D centers of global vendors, India contributors to global security OSS, Nullcon/c0c0n speakers, India fintech appsec). Ranked for **portable / US-CISO-legible** credibility, since the economic buyer is still a US CISO.
>
> **Recovered from the workflow journal** — the final synthesis agent stalled, so tiers/scores below are reconstructed from the per-candidate verified records (all 19 CONFIRMED at a primary source: person real + proof clicks through + currently India-based + IC not founder). Fit scores are the verifier's.

> **STANDING RULE — re-verify before contact.** Several records carry stale/ambiguous employers (Shilpesh Trivedi: Qualys vs Menlo; Siddharth Sharma: Uptycs→Palo Alto Unit 42→?SentinelOne). Independently re-confirm current employer + city on a live primary source before reaching out. Expect LinkedIn/X to block automated checks.

---

## ⚠️ The honest mismatch you need to see first

**You just relaxed the profile to: "CTO who has worked at scale, knows runtime challenges, solves complex problems" — security depth a plus, not the gate.** This India pool does **not** cleanly satisfy that. It is a **detection-science / threat-research / appsec pool** — malware researchers, Sigma/nuclei rule authors, product-security engineers. They are strong on *what to detect*; they are **not, on this evidence, engineers who have operated high-throughput low-latency runtimes at scale** — which is the axis you just said matters most (and the axis that actually closes your ~500ms-p99 latency gap).

So the two runs bracket the problem awkwardly:
- **US run** surfaced the real scale-runtime-security people (the Falco/eBPF cluster — Stemm, Dellaluce) — but they're **not in India**.
- **India run** (this doc) surfaced **detection researchers** — India-based, but **not scale-runtime-systems builders**.

**The person you now describe — India-based + operated runtimes at scale + elite problem-solver — is a different search:** India distributed-systems / platform-infra engineers from high-scale shops (ex-Google/Meta/Uber/Flipkart/Razorpay-scale, or India R&D of infra companies), *ideally* with some security exposure. That run hasn't been done. **Recommend running it** — see the bottom. Meanwhile, this detection pool is still valuable as: (a) the *detection-science* half if you split the role, or (b) a security-credibility advisor.

---

## Tier A — strongest fit (detection depth + portable credibility + clean recruitability)

| Name | Role / employer (re-verify) | City | Fit | Portable proof | Channel |
|---|---|---|---|---|---|
| **Mathanraj TK** | Threat Researcher III, **CrowdStrike** Malware Research Center (prev Trellix/FireEye ARC) | Bengaluru | 72 | Named Trellix/FireEye ARC blog research (Handala Wiper, co-authored w/ Max Kersten) | GitHub / vendor blog byline |
| **Akshay Gaikwad** | Sr Security Research Eng / Malware Analyst, **Securonix** Threat Labs | Bengaluru | 71 | Named in The Hacker News / SecurityWeek / Dark Reading on 9+ Securonix advisories (VEIL#DROP, SHEET#CREEP) | LinkedIn / Securonix byline |
| **Tejaswini Sandapolla** | Sr Malware Detection Researcher, **SentinelOne** (ex-Uptycs, ex-Quick Heal) | Pune | 71 | BSides Prague 2026 talk "Blind The Kernel" (YouTube) + named APT-36/Transparent Tribe research | conf talk / vendor byline |
| **Dhiyaneshwaran** (DhiyaneshGeek) | Security Eng, **ProjectDiscovery** (nuclei-templates) | TN (Coimbatore area) | 70 | **4 NVD CVEs** (CVE-2026-33992 pyLoad SSRF Critical +3 High) + **#1 human contributor to nuclei-templates** (9,119) | GitHub [@DhiyaneshGeek](https://github.com/DhiyaneshGeek) |

## Tier B — strong, one gap (detection-solid; probe the scale/runtime + AI-agent axes)

| Name | Role / employer (re-verify) | City | Fit | Portable proof |
|---|---|---|---|---|
| **Vishal Sangolekar** | Staff/Sr Threat Researcher, **Zscaler** ThreatLabz (IPS/YARA/Snort sigs) | Bengaluru | 64 | Zscaler ThreatLabz byline (global threat-vendor) |
| **Nischay Hegde** | Malware Detection Researcher, **SentinelOne** (ex-Uptycs; Linux/eBPF/YARA/EDR) | Bengaluru | 64 | Named Uptycs threat-research byline + accepted speaker |
| **Adithya Chandra** | Research Scientist, **Trellix** ARC (Detection Eng — NTDS.dit theft, AS-REP-roasting detections in Helix) | Bengaluru | 63 | Trellix ARC published detection research |
| **Shikha Sangwan** | Sr Security Researcher, **Securonix** Threat Labs | Bengaluru | 62 | Named-byline detection research at Securonix |
| **Ritik Chaddha** (ritikchaddha) | AppSec Researcher, **ProjectDiscovery** | Noida | 60 | **#5 all-time nuclei-templates** contributor; 88 CVE-detection templates (git-blameable global OSS) |
| **Akhil Mahendra** | Security Eng Leader, **Scapia** (ex-founding member CRED security team) | Bengaluru | 60 | Black Hat Arsenal demos (US/EU/Asia 2022-26) + Nullcon Goa 2025 — *IC-status flag: "leader," player-coach; probe* |
| **Subhash Popuri** | Sr Threat Analyst, **Microsoft** MSTIC | Maharashtra (Pune/Hyd) | 60 | **11 git-blameable SigmaHQ rules** + BlueHat India talk |
| **Siddharth Sharma** | Malware/threat researcher — was Uptycs → **Palo Alto Unit 42** → ?SentinelOne (STALE, verify) | Bengaluru/Delhi | 60 | Palo Alto Unit 42 byline (2023 LaZagne/D-Bus) + Uptycs Black Basta research |
| **Brajesh Kumar** | Sr Staff Data Scientist (ML/AI for malware detection), **Trellix** | Bengaluru | 58 | IEEE DSN-DSML 2019 paper on malware-detector evasion + McAfee/Trellix EDR patents |
| **Shilpesh Trivedi** | Lead/Staff Security Researcher, **Qualys** vs **Menlo** (ambiguous, verify) | Ahmedabad/Pune | 58 | The Hacker News (Murdoc Botnet, Jan 2025) + MacStealer (Uptycs 2023) — original research |

## Tier C — situational / single-lane / advisor-first

- **Yadhu Krishna M** — Security Eng, **CRED** (supply-chain security). Fit 56. Strong portable proof: **CVE-2023-30589 (Node.js) + CVE-2024-1135 (Gunicorn)** both NVD 7.5 HIGH; n8n RCE CVE-2026-25053; SupplyShield @ Black Hat Asia Arsenal. GitHub-reachable. *Supply-chain focus, not runtime detection.*
- **Aman Rawat** (theamanrawat) — AppSec Researcher / nuclei-templates maintainer, **ProjectDiscovery**. Fit 55. #10 maintainer (924 contribs) + 88 CVE templates. *Detection-template author, not systems builder.*
- **Vishnu Prasad K** — Principal DevSecOps Solutions Eng, **we45/AppSecEngineer**. Fit 55. Black Hat trainer (Asia 2024, USA 2023) + DEF CON/RSA — OPA+Cosign policy-as-code pipelines. *Strong on policy-as-code (your existing strength); training-heavy — probe production shipping.*
- **Nalinikanth Meesala** — Cyber Security Practitioner, **Thoughtworks** (Hyderabad). Fit 44. Co-built AIGoat (OWASP LLM Top-10 playground OSS). *AI-security exposure but modest; manager-ish.*
- **Dheeraj Kadri** — Tech Lead, cloud-native/container security, **Aqua Security** (Bengaluru). Fit 36. 2 merged PRs in Aqua OSS (Trivy misconfig engine). *Thin evidence; duplicates your cloud strength.*

---

## The read + recommended next step

1. **If you want a security-first CTO and split the role:** the top 4 (Mathanraj, Akshay Gaikwad, Tejaswini, Dhiyaneshwaran) are genuine detection-science ICs with proof a US CISO recognizes — exactly the "detection corpus + shadow→enforce" half your search doc was built to fill. Dhiyaneshwaran's 4 NVD CVEs + #1 nuclei-templates rank is the single most *verifiable, portable* profile here.

2. **But given your relaxed bar (scale + runtime + complex-problem-solver):** none of these clearly clears it. That profile needs a **separate India run** targeting distributed-systems / platform-infra engineers from high-scale shops (with security a plus). I recommend running it — it's the pool that matches what you actually described and closes your real latency constraint.

3. **Trust / "will they stay"** is unchanged and not screenable — absorbed by trial-before-equity + 4yr/1yr-cliff vest + reverse-vesting ([cofounder-search.md §6](../../cofounder-search.md#L252)).

**Caveats:** names recovered from journal (synthesis agent stalled); LinkedIn/X blocked many live checks; Scapia's Akhil Mahendra reads "leader/player-coach" — confirm IC appetite; Shilpesh Trivedi + Siddharth Sharma have ambiguous current employers. Re-verify all before contact. NDA + IP-assignment before any architecture deep-dive.
