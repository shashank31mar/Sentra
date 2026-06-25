# Letter of Intent — Design Partnership

**Template | Fill the `[bracketed]` fields before sending. Keep to 1–1.5 pages.**
**Companion to:** `pitch/design-partner-playbook.md` (terms) · `pitch/one-pager.md` (positioning)

---

**AegionAI, LLC**
[Street Address] · [City, State ZIP]

[Month DD, YYYY]

**To:** [Recipient Name], [Title]
**[Company Legal Name]**
[Address]

**Re: Letter of Intent — AegionAI AI-Agent Safety Design Partnership**

Dear [Name],

This letter sets out the mutual intent of **AegionAI, LLC** ("AegionAI") and **[Company Legal Name]** ("[Company]") to enter a design partnership under which AegionAI's runtime safety layer for AI agents will be deployed and evaluated in [Company]'s environment. Except where expressly stated in Sections 7, 8, and 10, **this letter is non-binding** and reflects intent only.

## 1. Purpose

The parties intend to collaborate as design partners to deploy, evaluate, and shape AegionAI's enforcement platform around [Company]'s production AI-agent infrastructure, with the goal of converting to a commercial agreement at the end of the partnership term.

## 2. Background

[Company] runs AI agents that [take real actions — e.g. issue refunds / move funds / update customer records] across [AWS and Azure / clouds]. Today these agents can act wrongly with real access, and [Company] requires (a) the ability to **stop a harmful action before it executes**, and (b) an **exportable audit trail** sufficient for [PCI-DSS / RBI / EU AI Act / SOC 2] obligations. AegionAI provides this enforcement layer across every cloud from one control plane.

## 3. Scope of the Pilot

| Item | Detail |
|---|---|
| **Deployment model** | [Multi-tenant cloud service / single-tenant in [Company]'s VPC / on-prem air-gapped] |
| **Agents & tools in scope** | [e.g. refund agent + payments API; transfer agent + ledger writes] |
| **Environment** | [Company] staging environment; no production traffic touched without written approval |
| **Integration** | One-line SDK wrapper per tool, instrumented jointly |
| **Success criteria** | The measurable outcomes [Company] cares about, agreed in writing at kickoff — e.g. [block ≥1 unauthorized action in staging; produce an exportable audit trail for a sample refund flow; <[X]ms added latency] |
| **Term & duration** | A **[6-week]** evaluation followed by a **[6-month]** design-partner period — approximately **[7 months]** total from the Effective Date — unless extended or ended earlier by mutual written agreement (see Section 7) |

## 4. Indicative Terms *(non-binding — for planning only)*

- **No license cost** for the design-partner period.
- **No design fee** during the design-partner period.
- **Permanent preferred pricing**: the commercial rate locked at the end of the term is [Company]'s indefinitely, never subject to standard increases.
- Any commercial terms that apply after the design-partner period will be set out in, and take effect only under, the definitive agreement (see Section 6).

## 5. Mutual Commitments *(intended, non-binding)*

**AegionAI will provide:** founder-led weekly sync (1 hr/week); [Company]'s priority use case scheduled and shipped within 3 weeks of agreement; early access to new capabilities 30 days before general availability.

**[Company] will provide:**

- An executive sponsor and ~2 hrs/week from a senior platform engineer (able to instrument the integration and give architectural feedback).
- Access to a staging environment with representative agent traffic.
- The **success metrics [Company] will use to judge the pilot**, agreed at kickoff, plus a joint review against them at the end of the term.
- Regular feedback on the product and roadmap during the weekly sync.
- A reference — a short joint case study and/or a reference call to a future AegionAI prospect — subject to [Company]'s approval of any public use of its name.

## 6. Path to a Definitive Agreement

The parties intend to negotiate and execute a **Design Partner Agreement** (incorporating security/data terms, intellectual-property terms, and the commitments above) by **[target date]**. That agreement, once signed, supersedes this letter and is the binding contract between the parties.

## 7. No Obligation to Continue

Neither party is obligated to continue beyond the evaluation or the design-partner term. At the end of the term, either party may decline to enter a commercial agreement for any reason and without penalty. On conclusion, each party will, on request, return or delete the other's confidential information, and AegionAI will remove its instrumentation from [Company]'s environment. The confidentiality and intellectual-property terms below survive.

## 8. Confidentiality & Intellectual Property *(binding)*

**Confidentiality.** Each party will treat the other's non-public information — including AegionAI's enforcement design and [Company]'s agent topology, configurations, and traffic — as confidential, used only to evaluate this partnership and not disclosed to third parties. [If a mutual NDA is already in place: "This section is governed by the mutual NDA dated [date], which controls in the event of any conflict."]

**Intellectual property.** Each party retains all right, title, and interest in its own pre-existing and independently developed intellectual property. AegionAI retains all rights in the AegionAI platform, software, and any improvements or derivatives developed during the partnership; [Company] retains all rights in its applications, agents, and data. No license is granted except the limited, non-exclusive right to use the other party's IP solely as needed to carry out the pilot. This section is **binding** and survives termination of discussions.

## 9. Non-Binding Effect

Except for Sections 7, 8, and 10, this letter creates **no binding obligation** on either party, imposes no exclusivity, and does not obligate either party to enter any further agreement. No purchase, payment, or commitment arises unless and until a definitive Design Partner Agreement is signed by both parties.

## 10. Governing Law *(binding)*

This letter is governed by the laws of the State of [Delaware / __], without regard to conflict-of-laws principles.

---

If this reflects [Company]'s intent, please countersign below. We're excited to build this with you.

Sincerely,

\
**Shashank Gupta**, Founder & CEO — AegionAI, LLC
Date: ____________________

\
**Sylvester Fernandez**, Co-Founder — AegionAI, LLC
Date: ____________________

**Acknowledged and agreed (intent only):**

\
**[Recipient Name]**, [Title] — [Company Legal Name]
Date: ____________________
