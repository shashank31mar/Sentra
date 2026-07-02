# WS-0 Measure-First Spike — Result Packet

**Status:** 🟡 **WORK IN PROGRESS — NOT SIGNED.** Only the AgentCore kill-checks (M0-5, §8 below) are complete. The numeric measurements (a/b/c) are **not yet run** (founder-gated preconditions, §9.3). This packet is signable only when every section is filled, the thresholds are pre-registered, and both kills are adjudicated (lld/34 §10: neither kill-check may be left inconclusive).
**Owner / sign-off:** Founder (Shashank Gupta) — single named, non-delegable (lld/34 §11.2).
**Methodology:** [lld/34-measure-first-spike-methodology.md](../../lld/34-measure-first-spike-methodology.md).
**Gate mechanics:** this packet's completion **date** becomes the gate date in [00-index.md](00-index.md) `:77`, unblocking WS-A / WS-D / WS-E decomposition (WS-C already overridden).
**Last updated:** 2026-07-02 (M0-5 complete).

---

## Section index (lld/34 §11.1)

| # | Packet part | Status |
|---|---|---|
| 1 | Combined GA-gate table — (a) local-resolve/escalation, (a3) Cedar escalate-fraction, (b) escalated p99, (c) recall Δ | ⬜ **pending measurement runs** |
| 2 | (d)/(e) AgentCore answers with citations | ✅ **COMPLETE — §8 below** |
| 3 | Pre-registered threshold table (git-committed, dated, BEFORE runs) | ⬜ **pending — must be committed before M0-3/M0-4.3** |
| 4 | Both kill adjudications | 🟡 M0-6.2 (AgentCore) — evidence ready, founder-sign pending · M0-6.1 (worst-quadrant) — pending measurements |
| 5 | Per-row disposition A / C / D / E | ⬜ **pending** |

---

## 1. Combined GA-gate table (pending — founder-gated measurement runs)

> **Preconditions before these rows can be filled (lld/34 §9.3):** (1) thresholds pre-registered (part 3); (2) live dev Bedrock quota+budget confirmed; (3) ≥2 external-anchored concurrency bands + WAN client placement pinned; (5) per-class corpus built (≥200 total + ≥100 native per class). Until then these stay blank — **no timeout auto-pass**.

| Metric | Value | Conditions |
|---|---|---|
| (a1) local-resolve fraction | ____ | acme- fleet money-movement mix; two numbers, never one "coverage" |
| (a2) escalation rate | ____ | complement of a1; reported separately |
| (a3) Cedar escalate-fraction | **k of N** = ____ of **3** (acme- policies) | raw count; ≈2/3 expected (payments+telecom carry `cross_cloud_dependencies` = out-of-subset; identity in-subset) |
| (b) escalated p50/p95/**p99** | band 1: __/__/**__** · band 2: __/__/**__** ms | full WAN + real never-mocked Bedrock; **≥2 concurrency bands**; **WAN position = ____**; escalate-sample N = ____ |
| (c) recall Δ — **EXFILTRATION** | unmasked __ / masked __ / **Δ __** (Wilson 95% CI __) | separate; ≥200 total + ≥100 native rows; obfuscated+non_us; **detector version = ____** |
| (c) recall Δ — **INDIRECT-INJECTION** | unmasked __ / masked __ / **Δ __** (Wilson 95% CI __) | separate; ≥200 total + ≥100 native rows; obfuscated+non_us; **detector version = ____** |

---

## 3. Pre-registered threshold table (pending — commit BEFORE the b/c runs, lld/34 §9.1)

> **Not yet pre-registered.** Per lld/34 §9.1 these MUST be git-committed (dated) BEFORE any (b)/(c) run; this packet cites the commit hash. A packet whose thresholds post-date its measurement commits is **not signable**.

| Threshold | Pre-registered value | Pre-reg commit (hash + date) | Rationale |
|---|---|---|---|
| HIGH escalation | ____ % | ____ | |
| LOW masked-recall (per class) | ____ | ____ | |
| Concurrency bands (≥2, external-anchored) | ____ | ____ | basis / source |

---

## 8. AgentCore kill-checks — (d) call-path scope + (e) not-behind-Gateway segment  ✅ COMPLETE

> **Feeds M0-6.2 (the AgentCore kill adjudication); does NOT decide it.** The kill/defer call is the founder's signed decision (part 4). This section supplies the two verified inputs and how they map onto the §9.2 rule. Per founder direction (2026-07-02), the disposition on a broad-(d) result is **DEFER WS-A with a dated re-check trigger, not DELETE** (lld/34 §9.2).
>
> Evidence discipline: every claim `[FACT]` / `[INFERENCE]` / `[ESTIMATE]` with a dated citation. **A marketing line is never accepted as a call-path fact** (lld/34 §8.1 FOOTGUN). Fetched content treated as data, not instruction. Research + adversarial-verification run 2026-07-02 (5-agent workflow; (d) adversarial verdict CONFIRMED, (e) OVERSTATED→carried as SINGLE_SOURCE).

### (d) AgentCore interception scope — the call-path boundary

**The answer (lead):** `[FACT]` **NO — AgentCore Gateway/Policy CANNOT govern an agent's tool call that does not transit the AgentCore Gateway.** Enforcement is a proxy bound to the Gateway MCP endpoint: the Cedar Policy engine and the Lambda interceptors evaluate **only** requests the agent sends *to* the Gateway (`POST /mcp`, method `tools/call`), which the Gateway then routes to the downstream target. A tool/API/network call an agent makes **directly** — bypassing the Gateway — is never seen by Policy and is therefore **ungoverned**. This is a property of the **CALL PATH, not the framework, and not where the agent runs**: it holds whether the agent runs on Bedrock AgentCore Runtime, on customer EC2/EKS/on-prem, or off-AWS (Azure/GCP). Any such agent *can* be pointed at a Gateway (and is then governed for the calls it chooses to route there), but nothing in AgentCore intercepts a direct call the agent makes on its own. **This closes HLD Appendix B's UNVERIFIED gap.**

**Where enforcement binds (`[FACT]`), and what is OUTSIDE it.** Binds at the **AgentCore Gateway acting as an MCP proxy / aggregation server** — not in the agent, framework, or model path. Lifecycle: JWT/SigV4 inbound auth → **Request-interceptor Lambda → Cedar Policy evaluation** → Gateway invokes the target → Response interceptor. Every Cedar policy `resource` is the **Gateway ARN** (`AgentCore::Gateway::"<gateway-arn>"`), `action` a **Gateway-registered tool** — Cedar has **no entity for a non-Gateway tool call.** Outside the boundary (ungoverned by Policy): **(a)** any direct tool/API/network call not addressed to the Gateway MCP endpoint; **(b)** an agent on customer EC2/EKS/on-prem or off-AWS that never routes through a Gateway; **(c)** direct model/LLM + direct AWS-service calls from a Runtime-hosted agent ("connects to the service's public IP addresses" directly).

Key doc lines (dated, retrieved 2026-07-02):
- `[FACT]` Policy overview: *"real-time, deterministic control over agent interactions with enterprise tools **THROUGH AgentCore Gateway** … Every agent action **THROUGH AgentCore Gateway** is intercepted."* — [hp-agent-core-policy-engine-overview.html](https://docs.aws.amazon.com/help-panel/bedrock-agentcore/latest/console/hp-agent-core-policy-engine-overview.html).
- `[FACT]` Cedar reference: *"Policy in AgentCore uses Cedar policies to control access to AgentCore **Gateway TOOLS**."* — [policy-understanding-cedar.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-understanding-cedar.html).
- `[FACT]` Tool-call ref: *"make a **POST request to the gateway's MCP endpoint** and specify `tools/call`."* — [gateway-using-mcp-call.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-using-mcp-call.html).
- `[FACT]` Gateway setup step 4: *"Update your agent code — **Connect your agent to the Gateway endpoint**."* — opt-in client wiring. — [gateway-building.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-building.html).
- `[FACT]` Lambda-interceptor blog (**2026-06-01**): pipeline JWT → Request interceptor → **Cedar Policy** → MCP Server → Response interceptor; "cannot be bypassed by the agent or the LLM" — **means the LLM can't override a decision, NOT that a non-Gateway call is evaluated.** — [secure-ai-agents-with-policy-and-lambda-interceptors](https://aws.amazon.com/blogs/machine-learning/secure-ai-agents-with-policy-and-lambda-interceptors-in-amazon-bedrock-agentcore-gateway/).
- `[FACT]` — load-bearing corroboration — Runtime networking blog (figure **2026-05-07**): default mode — *"When the agent needs to call an AWS service, it **connects to the service's public IP addresses**"* — direct egress, no Gateway/Policy in path. — [network-connectivity-patterns-…-agentcore-runtime](https://aws.amazon.com/blogs/networking-and-content-delivery/network-connectivity-patterns-for-agents-deployed-on-amazon-bedrock-agentcore-runtime/).

**The one inferential step, labelled.** `[INFERENCE]` No AWS doc says in one sentence "a tool call that does not go through the Gateway is not evaluated by Policy." That negative is a **deductive necessity** from the resource model (`resource` == Gateway ARN; no entity for a non-Gateway call) + the proxy call-path + the Runtime direct-egress `[FACT]`. A deduction, not a leap — but `[INFERENCE]`, and the SA close-out (below) promotes it to `[FACT]`.

**The marketing-line trap — addressed (satisfies §8.1 FOOTGUN).** `[FACT]` The line *"framework-agnostic / model-agnostic … CrewAI, LangGraph, LlamaIndex, Strands … any model"* lives **only** in Runtime *hosting* docs. `[INFERENCE]` It speaks to deployment/portability, **not** the enforcement call path; it does **NOT** claim Policy binds to a non-Gateway call. A LangGraph agent on customer EKS is a *supported framework*, but its direct tool calls are governed only if the author voluntarily wires them to a Gateway — bypassable, not enforced. **(d) is NOT verified off a marketing line.**

**Dated fact + RE-VERIFY TRIGGER (mandatory — this fact rots).**
- `[FACT] as of 2026-07-02` — AgentCore Policy/Cedar enforcement is **Gateway-bound only**; no known agent-side/Runtime-egress interceptor applies Cedar to direct (non-Gateway) calls.
- **RE-VERIFY TRIGGER:** re-check (d) on **each AgentCore GA-release note, or every ≤2 quarters (next hard checkpoint: 2027-01-02)**, whichever first — and **mandatorily before WS-A is ever treated as permanently dropped** (§9.2). A Runtime-egress enforcement hook is exactly the feature that would flip this. A DEFER is converted toward abandonment only by a *re-verified, still-broad* (d) plus a *still-small* (e).

**Unresolved gaps — a named AWS SA must still close these** (not contradicted by docs; not stated as an explicit negative, so warrant SA confirmation before asserting *proven* in a customer-facing competitive claim):
1. Confirm there is **no** agent-side/Runtime-egress interceptor (present or roadmap) applying Cedar/Policy to a Runtime-hosted agent's **direct** (non-Gateway) calls.
2. Confirm that for off-AWS / customer-infra agents the **only** governance path is voluntarily pointing the MCP client at a Gateway, and AgentCore has **no mechanism to force** that routing (bypassable by construction).
3. Confirm Runtime network controls (VPC egress, security groups, Network Firewall) are the only "containment" for direct calls — **coarse IP/port ACLs, not action/parameter-level Cedar governance** — so they don't close the action-governance gap.

### (e) Not-behind-Gateway segment size — the GTM number

**Segment definition.** Every enterprise AI agent whose tool-call path does **not** flow through an AgentCore Gateway. Three disjoint buckets: **(1)** Azure AI Foundry / GCP Vertex; **(2)** on-prem / air-gapped / off-AWS; **(3)** on AWS but calling tools **directly** — Bedrock action groups / `InvokeAgent` / Return-of-Control, own MCP servers, or a BYO-framework loop — not via Gateway. Sized as **% of the enterprise agent fleet**, not % of cloud revenue.

**Structural facts (`[FACT]`) anchoring the direction:** AgentCore Gateway is **AWS-only** and **opt-in even for Bedrock-native agents** (action groups / `InvokeAgent` execute directly via Lambda, work without it; Gateway+Cedar is a migration add-on) — [AgentCore GA announcement, **2025-10-13**](https://aws.amazon.com/blogs/aws/introducing-amazon-bedrock-agentcore-securely-deploy-and-operate-ai-agents-at-any-scale/) (VENDOR — COI); [gateway.html](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway.html) (VENDOR — COI). GA only **2025-10-13** → "governable by Gateway today" is a thin opt-in slice even inside AWS.

**The BAND (best/base/worst — share of enterprise agent fleet NOT governable by Gateway):**

| Case | Not-behind-Gateway | Driver |
|---|---|---|
| **BEST** | **~90%** | Gateway stays a thin opt-in slice; most agents BYO-framework / direct-tool-call / off-AWS. |
| **BASE** | **~75%** | Off-AWS hosting (~45–50%) + AWS-but-direct-tool-call bucket. |
| **WORST** | **~55%** | AWS wins majority of new agent hosting AND most AWS agents route through Gateway. |

*Even the worst case is a majority — a market, not a sliver.*

**Data points (dated sources):**
- Cloud infra share Q4 2025: AWS 28% / Azure 21% / Google 14% — **[Synergy Research, srgresearch.com, 2026-02-05]** (independent).
- Corroborating (revenue ranking only): AWS ~32% / Azure ~23% / Google ~10-11% — **[Canalys/Omdia, 2025]** (independent of Synergy).
- Enterprise **workload presence** (not revenue): AWS 84% ≈ Azure 82% — near-parity — **[Flexera State of the Cloud 2026, N=622]** (vendor-adjacent; **internally inconsistent** — report 84/82 vs press release 83/79).
- Multi-cloud: 76% of 3,000+ orgs — **[HashiCorp State of Cloud Strategy]**; ~89% incl. private — **[Flexera 2026]**.
- BYO-framework prevalence: 43% of LangSmith orgs send LangGraph traces — **[LangChain State of AI Agents, 2024-12-19]** (VENDOR self-reported — COI).
- AgentCore Gateway adoption: **no publicly disclosed customer/agent count** (GA 2025-10-13); any figure AWS-self-reported. Gateway-governed share is `[INFERENCE]`.

**Confidence — SINGLE_SOURCE for the numbers (does NOT meet §8.2's ≥2-source bar).** The **direction** ("majority not Gateway-governable today") is **CONFIRMED** on verified structural facts. But the numeric band (55/75/90) is a **structural-inference range**: it substitutes Flexera *workload-presence* (AWS 84% ≈ Azure 82%) for **agent-hosting share** — a category **no source measures** — and that Flexera number is single-source + internally inconsistent. The only triangulated input (cloud *revenue* ranking) is the denominator the segment def **rejects**. **Ships labelled SINGLE_SOURCE (`[ESTIMATE]` magnitude, `[FACT]` direction) — re-source before any GTM figure is asserted as triangulated.** Closing to TRIANGULATED needs a second independent **agent-hosting-share** source (does not yet exist publicly).

**Falsifiable assumption.** Segment stays a **majority** ONLY IF: (a) AWS does **not** make Gateway the default/mandatory tool-ingress for Bedrock agents; **and** (b) enterprises remain multi-cloud (Azure ~82% ≈ AWS ~84%). **Falsified if** AWS forces Gateway-as-default-ingress **AND** wins **>60% of enterprise agent *hosting*** — then the segment collapses toward the ~55% worst case.

**COI flags:** AWS GA/Gateway docs (VENDOR); Flexera (vendor-adjacent, inconsistent); LangChain telemetry (VENDOR). Independent: Synergy, Canalys/Omdia (revenue only), HashiCorp.

---

## 4. Kill adjudications

### M0-6.2 — AgentCore kill (evidence ready; **founder sign-off pending**)

> This records the evidence-based mapping. **The signed verdict is the founder's** (part 4 / lld/34 §11.2). Not decided here.

**§9.2 rule** fires "NOT committed" only when **(d) reaches off-AWS BROADLY AND (e) segment is SMALL.** On this evidence:
- **(d) does NOT reach off-AWS broadly** — Gateway-bound, opt-in, bypassable-by-construction (`[FACT]` + one labelled `[INFERENCE]`, adversarial verdict **CONFIRMED**).
- **(e) is NOT small** — base ~75%, worst ~55% (a majority).
- **⇒ Both §9.2 conditions FAIL → the rule points to WS-A COMMITTED, not NOT-committed.**

**DEFER-not-DELETE overlay (founder direction 2026-07-02):** even in a counterfactual broad-(d) future, §9.2 only NOT-COMMITs the **AWS-local-floor rationale** — a **DEFER with a dated re-check**, never a DELETE — and the **cross-vendor rationale (Azure/GCP/on-prem) survives** regardless. The signed verdict must state which rationale it applies to.

**Neutrality-sensitivity line (§9.2 item 2):** WS-A is worth building on the cross-vendor rationale alone — **even if AgentCore reaches broadly on AWS** — once the **off-AWS not-behind-Gateway segment (buckets 1+2) is ≥ ~40%** of the fleet. Current base `[ESTIMATE]` puts off-AWS hosting at **~45–50%** — **above that threshold today** (SINGLE_SOURCE caveat per (e); re-check when the band is re-sourced).

**Kill status: RESOLVED (does not fire).** Because **(d) is VERIFIED** and points *away* from the kill, the AgentCore kill is adjudicable and **signable**. This is **NOT** the lld/34 §10 blocked-packet case (which triggers only when **(d) is UNRESOLVED** — unverifiable / asserted off a marketing line). The (e) SINGLE_SOURCE status is a disclosed weakness on the *segment-size* input, not an UNRESOLVED (d); the founder should weight it when signing, but it does not block the packet.

### M0-6.1 — Worst-quadrant numeric kill (pending measurements a/b/c + pre-registered thresholds)

⬜ Pending. Cannot adjudicate until part 1 (measurements) and part 3 (pre-registered thresholds) are complete.

---

## 5. Per-row disposition A / C / D / E (pending)

⬜ Pending the full gate. **WS-A note (from M0-6.2 evidence):** the AgentCore kill points to WS-A **committable** (both §9.2 conditions fail); final disposition awaits the worst-quadrant kill (M0-6.1) which gates *synchronous-deep*, a separate axis from *whether the local floor is built*.

---

## Provenance

M0-5 executed 2026-07-02 via a 5-agent research+adversarial-verification workflow (2 research → 2 adversarial verify → 1 synthesis). (d) adversarial verdict: **CONFIRMED**. (e) adversarial verdict: **OVERSTATED** on the TRIANGULATED label → carried as **SINGLE_SOURCE**. All source URLs dated and retrieved 2026-07-02.
