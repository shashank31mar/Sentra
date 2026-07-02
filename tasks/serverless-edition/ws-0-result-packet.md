# WS-0 Measure-First Spike — Result Packet

**Status:** 🟢 **ALL MEASUREMENTS COMPLETE — AWAITING FOUNDER SIGNATURE.** Both kill-checks resolved; a/b/c measured on real Bedrock + real WAN (never mocked); thresholds pre-registered BEFORE the runs. Only the founder signature + gate-date fill remain (lld/34 §11.2).
**Owner / sign-off:** Founder (Shashank Gupta) — single named, non-delegable (lld/34 §11.2).
**Methodology:** [lld/34-measure-first-spike-methodology.md](../../lld/34-measure-first-spike-methodology.md).
**Gate mechanics:** this packet's completion **date** becomes the gate date in [00-index.md](00-index.md) `:77`, unblocking WS-A / WS-D / WS-E decomposition (WS-C already overridden).
**Last updated:** 2026-07-02 (a/b/c measured; both kills adjudicated).
**Harness (throwaway, NOT product):** [harness/ws0/](../../harness/ws0/) — commits `28581a2` (pre-registration + a3 + corpus), `f0b0f56` (Test-2 p99 + Test-3 recall). Per-row results + corpus + probe private key gitignored.

---

## Section index (lld/34 §11.1)

| # | Packet part | Status |
|---|---|---|
| 1 | Combined GA-gate table — (a) local-resolve/escalation, (a3) Cedar escalate-fraction, (b) escalated p99, (c) recall Δ | ✅ **COMPLETE — §1 below** |
| 2 | (d)/(e) AgentCore answers with citations | ✅ **COMPLETE — §8 below** |
| 3 | Pre-registered threshold table (git-committed, dated, BEFORE runs) | ✅ **COMPLETE — commit `28581a2`, 2026-07-02, BEFORE the b/c runs in `f0b0f56`** |
| 4 | Both kill adjudications | ✅ M0-6.2 (AgentCore) — resolved, does-not-fire · ✅ M0-6.1 (worst-quadrant) — adjudicated §4 below |
| 5 | Per-row disposition A / C / D / E | ✅ **COMPLETE — §5 below** |

---

## 1. Combined GA-gate table ✅ COMPLETE

> Measured 2026-07-02 on the **real** hosted PDP (`sentra-mvp-api`, us-east-1) + **real** Bedrock `aegionai-ml-classifier` AIP (Haiku 4.5 → Sonnet 4.6), **never mocked** (lld/34 §6b/§6c). Test-3 masks with the **real production WS-E Tier-1 redactor** (SDK `aegion_guard.redaction.redact`), not a stub — a stronger, more faithful instrument than lld/34 §5's Stub B.

| Metric | Value | Conditions |
|---|---|---|
| (a1) local-resolve fraction | **0.45 (45%)** | acme- fleet money-movement mix (1000 calls, documented ratios); two numbers, never one "coverage". `[ESTIMATE]` — modelled action mix, not live traffic capture (none exists for these agents). |
| (a2) escalation rate | **0.55 (55%)** | complement of a1; reported separately. Escalation concentrated on money-movement WRITEs (cross-cloud `verify_identity` sequence the single-session edge cannot resolve). |
| (a3) Cedar escalate-fraction | **2 of 3 = 0.67 (67%)** | raw count; payments+telecom carry `cross_cloud_dependencies` (out-of-subset → whole-policy escalate); identity in-subset. Deterministic — the input-independent ceiling. |
| (b) escalated p50/p95/**p99** | band c=5: 1714/2809/**2992** · band c=20: 1828/2879/**3454** ms (e2e WAN) · server-side p50≈1415ms | full WAN + real never-mocked Bedrock; 2 concurrency bands (5/20); **WAN position = local dev host → public internet → PDP us-east-1 (NOT co-located)**; escalate-sample N=150/band, 100% reached ML. |
| (c) recall Δ — **EXFILTRATION** | unmasked **0.968** / masked **0.973** / **Δ −0.005** (Wilson 95% CI unmasked [0.952,0.978], masked [0.959,0.983] — **overlap**) | 741 rows / 586 native (~290 semantic units); obfuscated+non_us incl.; **detector version stamped in results**. Masking does NOT reduce recall. |
| (c) recall Δ — **INDIRECT-INJECTION** | unmasked **0.565** / masked **0.601** / **Δ −0.036** (Wilson 95% CI unmasked [0.531,0.599], masked [0.567,0.634] — **overlap**) | 809 rows / 711 native (~395 semantic units); obfuscated+non_us incl.; **detector version stamped**. Masking does NOT reduce recall; but absolute recall is LOW (~57–60%) — a detector-quality signal, not a masking effect. |

**The three-number honesty (T5 / §6a3 contradiction-visible rule):** a1 (45% resolve) + a3 (67% policy-escalate ceiling) are reported side-by-side, NOT averaged. The gap is expected — benign reads resolve locally while every money-movement WRITE escalates on the cross-cloud sequence. The security-relevant traffic is exactly what escalates (§3 #3).

---

## 3. Pre-registered threshold table ✅ COMPLETE (committed BEFORE the runs, lld/34 §9.1)

> **Pre-registered in commit `28581a2` (2026-07-02), BEFORE the (b)/(c) measurement runs landed in `f0b0f56`.** Full detail: [harness/ws0/PRE_REGISTERED_THRESHOLDS.md](../../harness/ws0/PRE_REGISTERED_THRESHOLDS.md). Commit order verified: pre-registration precedes measurement — packet is signable on this axis.

| Threshold | Pre-registered value | Pre-reg commit | Rationale |
|---|---|---|---|
| HIGH escalation | ≥ **60%** | `28581a2` 2026-07-02 | above ~⅔ of security-relevant traffic crossing the WAN → local floor closes little of NFR-1; anchored to a3=0.67 ceiling. |
| LOW masked-recall (per class) | ≤ **0.70** on a class **OR** Δ ≥ **0.15** (CI-gated) | `28581a2` 2026-07-02 | a deep tier catching ≤70% post-mask (or losing ≥15 pts to masking) is materially blinded. CI-gated so a thin-corpus fluke can't trip it. |
| Concurrency bands (≥2) | **5** (steady) / **20** (burst) | `28581a2` 2026-07-02 | single financial-action agent steady rate + ~4× burst; `[ESTIMATE]`, re-measure on first real customer volume. |

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

### M0-6.1 — Worst-quadrant numeric kill ✅ ADJUDICATED (does NOT fire)

**§9.1 rule:** the kill fires only when **escalation is HIGH _and_ masked-recall is LOW** — slow *and* blind on the requests that matter. Both must hold.

Against the pre-registered thresholds (`28581a2`):

| Axis | Threshold | Measured | Meets kill condition? |
|---|---|---|---|
| **HIGH escalation** | ≥60% | a2=55% (traffic) · a3=67% (policy ceiling) | **Borderline-HIGH.** Traffic 55% is just under; the input-independent ceiling 67% is over. Treat as effectively HIGH for money-movement. |
| **LOW masked-recall** | ≤0.70 OR Δ≥0.15 (CI-gated) | exfil masked 0.973 (Δ−0.005); indirect masked 0.601 (Δ−0.036) | **NOT low-by-masking on either class.** Masking Δ is ≈0 (CIs overlap) — masking does not blind. |

**⇒ The worst-quadrant kill does NOT fire.** The quadrant is "slow BUT NOT blind": escalation is high and the escalated p99 (~3s) is heavy, but **masking does not degrade detection** — so the *redaction-vs-deep-tier* pull that this kill exists to catch is empirically absent. **The unconditional "leave-it-on-synchronously + deep" claim is NOT killed by masking.**

**BUT two measured facts reshape the GA claim (recorded, not hidden):**
1. **`[CRITICAL for the latency claim]` Escalated p99 ≈ 3.0–3.5s BLOWS NFR-2** (≤900 ms fast-ML; ≤2.5 s deep). The synchronous escalated Serverless path is ~3s p99 for money-movement — and 55–67% of money-movement traffic escalates. So "fast enough to leave on synchronously" is **false for the escalated majority** on Serverless today. This is the falsifiability number lld/34 §1 said the thesis could not do without — and it lands against the claim. **Fallback (ii) — route money-movement to in-VPC (local floor sees unmasked content in-boundary, no WAN+Bedrock round-trip) — is INDICATED by the latency result**, independent of the masking result. escalate-async (iii) remains **UNAVAILABLE for money-movement** (irreversible/financial — §9.1 FOOTGUN); money-movement stays synchronous fail-closed.
2. **`[detector-quality, separate axis]` Indirect-injection recall ~57–60% (masked or not)** — the deep tier misses ~40% of indirect-injection regardless of redaction. This is not a masking effect (Δ≈0); it is a detector-coverage gap that WS-L (D1–D7 depth) must close. It does not fire *this* kill (which is about masking) but is a flagged GA risk.

**Net:** masking is safe (the redaction GA gate FR-3.13/NFR-7 is unblocked by the recall result); the *latency* of the synchronous escalated path is the real problem, pointing money-movement toward the in-VPC edition rather than killing the deep claim outright.

---

## 5. Per-row disposition A / C / D / E ✅ COMPLETE

Both kills resolved → the four gated rows can be dispositioned. **This is the founder's call to ratify on signature; the evidence-based disposition is:**

| WS | What it is | Disposition | Rationale from the measured gate |
|---|---|---|---|
| **WS-A** | FR-1.7 local floor / signed bundle | **COMMIT** | AgentCore kill does NOT fire (both §9.2 conditions fail — (d) Gateway-bound, (e) majority not-behind-Gateway) → WS-A committable. **STRENGTHENED by the latency result:** the ~3s escalated p99 makes the local floor's whole value (resolve locally, skip the WAN+Bedrock round-trip) concrete — a1=45% of money-movement traffic could resolve at the edge *if* the cross-cloud sequence became edge-resolvable. Note a3=0.67 ceiling: the local floor CANNOT resolve the cross-cloud money-movement sequence as-is — WS-A's design must either raise in-subset coverage or pair with fallback (ii). |
| **WS-C** | FR-2.8 DAG scheduler | **COMMIT** (already founder-overridden 2026-07-01; built + deployed) | Not gated by this packet (override). Measured facts don't change it. |
| **WS-D** | decision-trail | **COMMIT** (was spike-gated) | Rides WS-C; no measured fact blocks it. Unblocked by this signed packet. |
| **WS-E** | FR-3.13 redaction / deep tier | **COMMIT — redaction GA gate UNBLOCKED** | The masked-recall result (Δ≈0 on both classes, CIs overlap) is the precondition lld/34 §6.2(e) required: **masking does not blind the deep tier**, so FR-3.13/NFR-7 can lock. Caveat carried: valid only for the stamped detector version; re-measure on ML shadow→enforce graduation / prompt-signature rebuild. |
| **(WS-L)** | D1–D7 detection depth | **PRIORITIZE** | Not a spike-gated row, but the measured **indirect-injection recall ~57–60%** makes WS-L's coverage work load-bearing: the deep tier misses ~40% of indirect-injection today. |

**The one GA-shaping decision the founder owns (from M0-6.1):** the ~3s escalated p99 means the unconditional "leave-it-on-synchronously + deep for money-movement on Serverless" latency promise does **not** hold. The evidence points to **fallback (ii): route money-movement to the in-VPC edition** (deep tier sees unmasked content in-boundary, no WAN+Bedrock round-trip) while Serverless keeps the deterministic floor + deep-tier for non-money-movement or latency-tolerant flows. This is a positioning call, not a build-kill.

---

## Provenance

**M0-5 (AgentCore kill-checks)** executed 2026-07-02 via a 5-agent research+adversarial-verification workflow (2 research → 2 adversarial verify → 1 synthesis). (d) adversarial verdict: **CONFIRMED**. (e) adversarial verdict: **OVERSTATED** on the TRIANGULATED label → carried as **SINGLE_SOURCE**. All source URLs dated and retrieved 2026-07-02.

**M0-1..M0-4 (a/b/c numeric measurements)** executed 2026-07-02 via the throwaway harness in [harness/ws0/](../../harness/ws0/):
- **a3** ([cedar_escalate_fraction.py](../../harness/ws0/cedar_escalate_fraction.py)) — deterministic classification of the real `policies.demo.yaml` acme fleet against the closed subset. = 2/3.
- **a1/a2** ([local_resolve_fraction.py](../../harness/ws0/local_resolve_fraction.py)) — Stub A over a documented 1000-call money-movement action mix. `[ESTIMATE]` (modelled mix, not live capture — flagged).
- **(b) escalated p99** ([latency_p99.py](../../harness/ws0/latency_p99.py)) — 300 real WAN POSTs (150/band × 2 bands) to the deployed `sentra-mvp-api` → pipeline → real Bedrock; required provisioning a throwaway `acme-payments-agent` kid (identity=enforce). 100% reached the ML tier. The 3 real acme keys were untouched; the probe private key is gitignored.
- **(c) recall Δ** ([recall_scorer.py](../../harness/ws0/recall_scorer.py)) — 1550 rows (741 exfil + 809 indirect) each scored unmasked vs **real WS-E Tier-1 redactor**-masked against Sigma + the real Bedrock ML classifier. Corpus ([build_corpus.py](../../harness/ws0/build_corpus.py)) from InjecAgent + AgentDojo + BIPIA (all MIT/permitted), per-class + native-floor honest. Detector version stamped in the results JSON.

**Threshold pre-registration** ([PRE_REGISTERED_THRESHOLDS.md](../../harness/ws0/PRE_REGISTERED_THRESHOLDS.md)) committed at `28581a2` **before** the (b)/(c) runs landed at `f0b0f56` — commit order verified.

**Cost/safety note:** the harness is throwaway (NOT checked into CDK/product per founder direction); it read-only-consumed the existing Bedrock setup (did not modify it); real Bedrock spend was incurred on ~6,500 inference calls (Test-3) + 300 (Test-2). Cleanup owed post-signature: delete the throwaway probe DDB credential row + `rm harness/ws0/.probe_identity.json` (see [provision_probe.py](../../harness/ws0/provision_probe.py) output).
