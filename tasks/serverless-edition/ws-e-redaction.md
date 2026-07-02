# WS-E — Two-tier redaction + the PHI-NER model-serving container + opt-in redacted feedback store

**Workstream:** WS-E (Serverless edition) — two-tier redaction. *(This is the single canonical workstream doc: scope + granular buildable tasks; the design lives in the LLD below.)*
**Derived from:** [lld/29-redaction.md](../../lld/29-redaction.md) (APPROVED, 17 sections). **The LLD is the SOURCE OF TRUTH** — when this breakdown and the LLD disagree, the LLD wins; fix this file.
**Status:** ✅ **CODE-DONE + DEPLOYED to prod (2026-07-02)** — WS-0 gate **founder-overridden 2026-07-01**. Tier-1 edge redactor live in all 3 acme connectors; Tier-2 server barrier + no-raw audit guard (strict fail-secure, milestone-97) + persist-gate + image-router + feedback-store logic + F7 frame-local control live. **HELD (built+synth-verified, NOT deployed — GA-gated on WS-0 recall + counsel BAA):** the `phi-ner` Fargate service + feedback-store DDB table. Remaining = GA-gated / dependency items only (see acceptance checklist). FR-3.13 = **DONE**; FR-3.14 retrain batch job = P2 gap (unchanged). *(Spike-gating map below is historical — retained for the WS-0-dependency rationale.)*
**Owner:** TBD.

## Dependencies

- **Depends on:**
  - **WS-0 (measure-first spike) — HARD gate.** WS-0 produces the masked-vs-unmasked recall-delta (residual #5) that is the precondition for *locking* the redaction GA gate (LLD §15.5), and the Tier-2 NER **recall NUMBER + latency benchmark** (LLD §4.1, §9). No signed WS-0 packet → this WS does not start. The kill/pivot branch (worst quadrant: high masking-cost AND low masked-recall) is decided in WS-0, not here.
  - **WS-B (`phase` contract)** — the additive/defaulted/validated `phase` enum (`request|content|output|memory`, default `request`) on `ValidationRequest` ([models.py:17-39](../../src/security-controller/app/api/models.py#L17) — **no `phase` field today**). If WS-B has not landed it, WS-E adds it as an **explicit prerequisite task (E1.0)** — additive+defaulted+validated. **Unknown-phase handling is WS-B's (lld/30 §3.1), NOT WS-E's: an unknown/typo phase → 422 validation error (NOT a deny, NOT metered); only a *known-but-unbuilt* phase → fail-secure DENY.** WS-E does not re-decide this.
  - **Counsel (legal)** — BAA obligations (45 CFR 164.308/164.314) + the §7.2 breach argument confirmed **before any HIPAA GA claim ships** (Tier-2 / feedback store). A release-gate dependency, not a code check (LLD §7.3, §15.5).
- **Blocks:**
  - Any "Serverless serves a HIPAA/PHI customer" or "sensitive-data customer" GA claim — the redactor is the **hard GA gate** for those segments (HLD §6.2(e)).
  - **FR-3.14 retrain loop** — the offline re-score/retrain consumes the redacted feedback store this WS builds (LLD §6.6). The batch job itself is a separate P2 LLD gap (below).
- **Shared files / contracts:**
  - SDK request build — `_build_request` ([guard.py:325](../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L325), payload assembly [:371-389](../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L371)) — shared with the SDK/`phase` WS. **Stdlib-only** ([pyproject.toml:26](../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/pyproject.toml) `dependencies = []`; LLD 23 §2) — Tier-1 MUST preserve this.
  - The controller pipeline — [validation_service.py:239](../../src/security-controller/app/services/validation_service.py#L239) (`_capture`), [:46-75](../../src/security-controller/app/services/validation_service.py#L46) (off-path telemetry), [:206/213](../../src/security-controller/app/services/validation_service.py#L206) (error path) — the F1 barrier + no-raw path lands here.
  - The live raw-logging surface — [audit_logger.py:223](../../src/security-controller/app/utils/audit_logger.py#L223)/[:307-308](../../src/security-controller/app/utils/audit_logger.py#L307)/[:320-321](../../src/security-controller/app/utils/audit_logger.py#L320) — the clause-(a) violation §5 cleans.
  - CDK compute — [compute_stack.py:1651-1758](../../cdk/stacks/compute_stack.py#L1651) (`service_configs` → `FargateTaskDefinition` + `FargateService` + CloudMap `*.sentra.internal`) — the NER-service construct is a new peer here.
  - Signal-store CDK basis — [signal_store_table_construct.py:80-81](../../cdk/cdk_constructs/signal_store_table_construct.py#L80) (`RETAIN`, `point_in_time_recovery=False`) — the feedback-store construct anchors on it, with deltas.
  - The bundle/`phase` — WS-I (LLD 28); the meter store — WS-H (the feedback store is NOT it, LLD §14).

---

## Spike-gating map — what can start the moment WS-0 signs vs what needs the recall NUMBER

WS-E as a whole is **spike-gated** (00-index: do not build until WS-0 signed). Within that gate the milestones split by *what WS-0 output they need*:

| Milestone | What it needs from WS-0 | Can start when |
|---|---|---|
| **E1** — Tier-1 edge deterministic redactor (SDK) | **Least spike-dependent.** Deterministic (regex/Luhn/entropy) — not recall-gated. Its PCI SAD/PAN 0-miss gate is deterministic (§E8). | The instant WS-0's packet **signs** (the WS-E gate lifts); does NOT wait on the recall number. |
| **E3** — the F1 happens-before barrier wiring | Design-only ordering; not recall-gated. | On WS-0 sign (needs E1/E2 landing to wire against). |
| **E4** — NO-RAW-PHI invariant | Not recall-gated (it is an invariant, proven by test). | On WS-0 sign. |
| **E5** — opt-in redacted feedback store | Store contract not recall-gated; its **eval-gate threshold** reuses the §15.4 number. | On WS-0 sign (store builds); eval-gate threshold locked with the recall number. |
| **E6** — image per-tool `{redact\|evaluate\|block}` mode | Mode contract + `evaluate`/`block` not recall-gated. | On WS-0 sign. |
| **E7** — URL/egress | Reuses FR-2.9; not recall-gated. | On WS-0 sign. |
| **E2** — the PHI-NER model-serving CONTAINER + the recall gate | **Needs the recall NUMBER + latency benchmark.** The model choice (self-host distilled ONNX-int8 vs Comprehend-Medical fallback) is gated on the §15.5 recall target; the ≤900 ms fit is gated on the §9 benchmark. | Container *scaffold* (Dockerfile/CDK/API contract) can be built on WS-0 sign; **model selection + GA-lock** wait on the recall number. |
| **E8** — tests + gates | The **fuzzy Tier-2 recall gate is the WS-0-gated NUMBER** (mark GATED); Tier-1 matcher UTs + the **PCI 0-miss** test are deterministic (NOT recall-gated). | Deterministic tests on WS-0 sign; the recall-harness threshold-lock on the number. |

> **The one-line read:** on WS-0 sign, **E1 + E3–E7 and E2's container scaffold** are codeable; the **recall-number-dependent** pieces are E2's model-selection/GA-lock and E8's fuzzy-Tier-2 recall threshold.

---

## Read before coding — the invariants the LLD makes load-bearing (hold these or you fail OPEN / breach)

Under NFR-7 (c) a **logging bug is a reportable breach**, not a missed NFR (LLD §5.1). Violating any of these is a defect.

1. **Two tiers, two homes, one boundary (M-1).** **Tier-1 = edge deterministic redactor IN the SDK** (regex+Luhn+entropy+format-anchor → structure-preserving **typed tokens**, stdlib-only, raw structured PII/PCI **never leaves the customer**, runs on **EVERY** phase). **Tier-2 = server-side free-text PHI semantic NER on the hosted PDP** (P0, first-wave — ships WITH Tier-1, NOT deferred; transient under a BAA; never retains/logs; no human access). The Nitro enclave (mechanism b) and edge native-NER (mechanism a) are **named later hardenings, NOT this WS** (LLD §1.3, §4.5).

2. **The single worst bug: "forward/persist the raw value anyway" (LLD §1.2 tenet 1).** A Tier-1 fall-through to `_send` with raw, or a Tier-2 "skip-store but forward raw onward," is the path that actually breaches (§7.2). Tier-1 fails **at the edge before egress** (hard DENY, E1); Tier-2 is a **hold-after-receipt** (do-not-forward-onward / do-not-persist the unredactable content, E3) — never a blanket action-DENY where the rest is safe.

3. **Matcher ORDER is a security control, not cosmetics (§3.2).** SAD before PAN before any bare-numeric matcher. A bare numeric matcher running first mis-tokens a PAN as `<NUMBER>`/`<SECRET>` and loses the PCI first6/last4 obligation. The order is a frozen module constant `_ORDERED_MATCHERS`.

4. **Token grammar is namespaced + nonce'd (M-4, §3.3).** The wire grammar is `⟦AEGR:{nonce}:TYPE[:meta]⟧` — reserved sentinel + per-call `secrets.token_hex` nonce; attacker-supplied token strings are **neutralized before redaction** (`_neutralize_planted_tokens`). Do **NOT** ship a bare `<CARD>` any input can spoof (a forged marker fools a detector or fakes a redaction-quality signal into the feedback store). The nonce defends against the AGENT-side author, NOT the hosted plane (§8).

5. **PCI SAD/PAN is a HARD 0-miss deterministic gate, held SEPARATELY from the fuzzy Tier-2 target (§3.2 footgun, §7.2, §15.4).** PAN (Luhn mod-10 → `<CARD:6:4>`, middle digits gone) and SAD (CVV/track/PIN → dropped, no value) are deterministic → **hard 0-miss on `corpus/pci_sad_pan.jsonl`**, its own release-blocking test. **Never** blended/averaged into the WS-0-gated fuzzy Tier-2 free-text recall number.

6. **Tier-2 NER is a happens-before BARRIER on the PHI content path, NOT an off-path pass (F1, §2.2/§4.1/§5.3).** On a PHI-bearing free-text field: `NER → (redacted view) → { deep detectors read · audit/signal write · meter/feedback write }`. None of those three consumers may read/persist that field's content **concurrently with** NER. The "hides behind the floor / parallel overlap" claim (§9.2 lever 3) applies **ONLY to the verdict-return path for NON-PHI-bearing calls** — a PHI-bearing field pays NER on the critical path (≤900 ms ML-hot budget), not hidden behind the ≤500 ms floor.

7. **The provenance flag is NOT sufficient for a PERSISTING store — content re-scan required (F2, §5.3.3/§6.3).** A `redacted=True` flag proves a pass *ran*, not that it *caught everything* — a Tier-2 miss is un-tokenized raw carrying `redacted=True`. The gate that admits a record to ANY persisting store (signal store, feedback store) runs a **content re-scan by a STRONGER independent detector** (the §6.3 heavy reclassifier / Comprehend-Medical gate-only mode), NOT a flag check. Re-scan the WHOLE would-be-persisted record (payload + `reason` + `winning_source`/matched-rule + `detector_outcomes`), not the payload alone.

8. **Structure preservation is the point (M-5).** Tier-1 replaces the *value* but preserves shape/position/type (typed tokens) so the deep detectors keep structural signal. Do not collapse to one opaque token — residual #5 measures the recall cost of even typed-token masking.

9. **The honest claim (M-2 (c) / §7.1).** *"Transient + not-retained + not-logged + no human access under a BAA"* — **NOT** "machine-unreadable by AegionAI" (our code reads the value to scrub it; provable unreadability = the deferred enclave, §4.5). GDPR: reversible masking is **pseudonymisation**, still personal data — never "anonymised"/"Safe-Harbor de-identified" for free-text we did not semantically scrub. The legal basis is **CONTAINMENT + BAA-permitted use + risk-based breach analysis**, NOT a redaction SLA and NOT Expert Determination (§7.1/§7.2, F8).

**Scoped OUT of WS-E (named, not silently dropped) — LLD §1.3:** the Nitro enclave (mechanism b); edge native-NER (mechanism a); the FR-3.7 PDP→PEP **REDACT-verdict content-rewrite loop** (a third outcome the decorator can't do today — separate later LLD); the `redact`-mode **image-redaction engine** itself (Tesseract+Presidio+faces+DICOM — the mode contract + `evaluate`/`block` routing ARE in scope, the engine is the named later build); re-deciding ADR-032.

```mermaid
sequenceDiagram
  participant AG as AI agent
  participant SDK as Tier-1 edge redactor (SDK, stdlib)
  participant PDP as Hosted PDP (transient)
  participant NER as Tier-2 NER CONTAINER (BAA)
  participant DET as Deep detectors (Cedar/Sigma/ML)
  participant FS as Redacted feedback store (opt-in)
  AG->>SDK: guarded call (phase: request|content|output|memory)
  SDK->>SDK: neutralize planted tokens → ordered matchers → typed tokens
  Note over SDK: raw structured PII/PCI NEVER leaves
  SDK->>PDP: POST /v1/validate (structured PII masked; free-text PHI raw under BAA)
  PDP->>NER: free-text fields only (transient, in-memory)
  NER-->>PDP: redacted free-text; raw discarded — NEVER logged/retained
  Note over PDP,NER: HAPPENS-BEFORE BARRIER (F1) — NER COMPLETES before any deep-detector read / audit write / meter+feedback write of that content
  PDP->>DET: validate over typed-token text
  DET-->>PDP: decision + reason + winning_source
  PDP-->>SDK: decision (no raw echoed back)
  opt tenant opted in (DPA) AND content re-scan gate passed
    PDP->>FS: REDACTED record only (typed tokens, bounded TTL)
  end
```

---

# Milestones → tasks

## Milestone E1 — Tier-1 edge deterministic redactor in the SDK (stdlib-only) — LLD §3

> Today the SDK egresses `tool_params` + `user_input` **un-redacted** ([guard.py:371-389](../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L371)) and only the `request` phase is wired. E1 builds the deterministic redactor and runs it on every phase, before `_send`. **Least spike-dependent — codeable the moment WS-0 signs.**

### E1.0 (prerequisite) — `phase` field on the contract (only if WS-B hasn't landed it)
- **Files:** [src/security-controller/app/api/models.py:17-39](../../src/security-controller/app/api/models.py#L17) (`ValidationRequest`).
- **Change:** add an **additive, defaulted, validated** `phase` enum, `default="request"`, values `request|content|output|memory`. Coordinate with WS-B — if WS-B owns it, this task is a verify-only.
- **Implements:** LLD §1.4 note, E4.
- **FOOTGUN:** must be **additive+defaulted** (a breaking/required field re-cuts every SDK/connector). **Unknown-phase handling is WS-B's (lld/30 §3.1): unknown/typo → 422 validation error (NOT a deny, not metered); known-but-unbuilt → fail-secure DENY.** Do NOT implement an "unknown → DENY" path here (that is residual pre-reversal polarity — WS-B owns it).

### E1.1 — the deterministic matcher set + the frozen ORDER
- **File (new):** `demo-agents/sdk/aegion-guard-python/src/aegion_guard/redaction.py` — **stdlib-only** (`re`, `math`, `unicodedata`, `secrets`). **No runtime dep may be added to `pyproject.toml`** (`dependencies = []`).
- **Change:** implement each matcher `(detector → typed-token)` per the LLD §3.2 table and freeze the order in a module constant. Real names:
  ```python
  # redaction.py (NEW, stdlib-only) — order is a security control (§3.2).
  _ORDERED_MATCHERS = (
      SADMatcher(),        # most-specific/highest-harm: DROP entirely (PCI never-store) → <SAD>, no meta
      PANMatcher(),        # regex candidate → Luhn mod-10 → <CARD:6:4> (first6/last4 only) — MUST precede any bare-numeric matcher
      SSNMatcher(), MRNMatcher(), AccountMatcher(), LicenseMatcher(), DeviceMatcher(),  # format-anchored (label-adjacent+shape), not pure shape
      EmailMatcher(), PhoneMatcher(), IPMatcher(), URLMatcher(), DateMatcher(),
      SecretMatcher(),     # Shannon-entropy fallback LAST — broadest, lowest precedence → <SECRET>
  )
  ```
  Tokens per the LLD §17 canonical set: `CARD:6:4`, `SAD`, `SSN`, `EMAIL`, `PHONE`, `IP`, `URL`, `MRN`, `ACCT`, `LICENSE`, `DEVICE`, `DATE`, `SECRET`.
- **Implements:** LLD §3.2.
- **FOOTGUN:** `<CARD:6:4>` carries first6/last4 **only** (the meta is the unmasked prefix/suffix, never the middle digits); `<SAD>` carries **NO** meta (CVV/track/PIN never-store). Never emit a full PAN even tokenized.

### E1.2 — Shannon-entropy floor for `<SECRET>`
- **File:** `redaction.py` (`SecretMatcher`).
- **Change:** Shannon entropy over the candidate token's charset; a tuned floor (~≥3.5 bits/char over a 32+ char base62/hex string) + min-length that catches API keys/tokens while **NOT** scrubbing legitimate low-entropy IDs (a UUID, an order number). The exact floor is a constant validated by the §15.4 harness — set conservatively (favor a false-negative on a benign ID over destroying a legitimate value).
- **Implements:** LLD §3.4.

### E1.3 — typed-token grammar: reserved sentinel + per-call nonce + neutralize planted tokens (M-4)
- **File:** `redaction.py`.
- **Change:** implement the wire grammar `⟦AEGR:{nonce}:TYPE[:meta]⟧` and `_neutralize_planted_tokens`; the shared contract is `redact(value, *, nonce) -> str`:
  ```python
  def redact(value: str, *, nonce: str) -> str:
      escaped = _neutralize_planted_tokens(value)        # M-4: attacker can't forge a marker
      for matcher in _ORDERED_MATCHERS:                  # §3.2, highest-harm first
          escaped = matcher.sub_token(escaped, nonce=nonce)  # value → ⟦AEGR:{nonce}:TYPE[:meta]⟧
      return escaped
  ```
  The `{nonce}` is a per-call `secrets.token_hex(8)` bound to this single egress; the downstream PDP treats only `⟦AEGR:{nonce}:…⟧` (with the call's nonce) as a genuine marker.
- **Implements:** LLD §3.3, M-4.
- **FOOTGUN:** do NOT use a bare `<CARD>`. The HLD's `<CARD>` illustration is descriptive UI-facing rendering, not the wire grammar. A bare token any input can spoof re-opens M-4.

### E1.4 — run on EVERY egressing phase (the live bug), in `_build_request`
- **File:** [guard.py:325](../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L325) (`_build_request`) — after `safe_params` is built ([:371-389](../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L371)), before `return payload`.
- **Change:** redact every content-bearing field before egress, keyed on `phase`:
  ```python
  nonce = secrets.token_hex(8)                          # per-call; binds genuine markers (§3.3)
  phase = active.phase if active else "request"
  payload["tool_params"] = redact_fields(safe_params, nonce=nonce)  # request phase
  payload["user_input"]  = redact(resolved_input, nonce=nonce)
  if phase in ("content", "output", "memory"):          # WS-B phases carry content in phase-specific field
      payload[_CONTENT_FIELD[phase]] = redact(payload[_CONTENT_FIELD[phase]], nonce=nonce)
  payload["redaction_nonce"] = nonce                    # PDP uses it to recognize genuine markers
  ```
- **Implements:** LLD §3.5.
- **FOOTGUN:** do NOT redact only the `request` branch. `content` (retrieved docs, tool output, web text) is often the **richest** PII surface — leaving it raw is the live NOT-DONE bug. The §15.1 test sends PII in a `content` field and asserts the typed token, not the raw value.

### E1.5 — fail-secure on redactor error
- **File:** `_build_request` / the redaction call site in `guard.py`; align with [config.py:93/164-165](../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/config.py#L93) (fail-secure default) and the unknown→DENY transport path ([guard.py:391-406](../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L391)).
- **Change:** if `redact()` raises on any field, short-circuit to a **DENY Decision** (reason `redaction_failed`) — **never** `_send` the raw payload.
- **Implements:** LLD §3.8, E1.
- **FOOTGUN:** a redactor exception falling through to `_send` with raw is the clause-(a) breach (invariant #2). Fail to DENY, never to "send unredacted."

---

## Milestone E2 — Tier-2 PHI-NER: the SEPARATE model-serving CONTAINER (P0, first-wave) — LLD §4, §9.3 Option A, §9.6

> **THE container milestone (owner directive).** Tier-2 is a **NEW warm, always-on ECS/Fargate service, distinct from the `security-controller` container** — model-resident (self-hosted Presidio + a distilled PHI-NER exported to ONNX-Runtime + int8), a stateless fleet like the controller (LLD 27 pattern). It runs on the free-text fields that survive Tier-1, transiently under a BAA. **Container scaffold (Dockerfile/CDK/API contract) is codeable on WS-0 sign; the model SELECTION + GA-lock wait on the WS-0 recall number + §9 latency benchmark.**

### E2.1 — the NER-service container image (new Dockerfile)
- **File (new):** `docker/Dockerfile.phi-ner` (a 7th→8th image in the [build_and_push_images.sh](../../scripts/build_and_push_images.sh) set); the service code under `src/security-controller/app/redaction/phi_ner.py` (NEW component) served by its own FastAPI/uvicorn app (do NOT co-locate on the `security-controller` container).
- **Change:** the image bakes/pulls (a) **Presidio (MIT)** as the regex+NER hybrid, (b) the **distilled PHI-NER model artifact exported to ONNX** (int8-quantized) baked into the image or pulled at boot from S3, (c) the **Tesseract system binary** (apt package) for the future `redact`-mode image path (§E6 — image *engine* is the later build, but the binary belongs to this container's system deps). Model choice is the LLD §4.1 candidate set: **self-host distilled ONNX-int8 (PRIMARY)** starting pre-GA as the in-controller Presidio-spaCy hybrid (Latency Option B) → graduating to the warm ONNX microservice (Option A); Comprehend Medical is **fallback-only** if self-host misses §15.5.
- **Implements:** LLD §4.1, §9.3.
- **FOOTGUN (BUILD not buy — subprocessor boundary, not cost):** the load-bearing reason to self-host is that self-hosting adds **no new subprocessor** — raw PHI stays inside AegionAI's own controller/BAA. Every managed de-id API (Comprehend Medical, Google DLP, Nightfall, Skyflow) makes a third party OUR subprocessor and pushes raw PHI out — self-defeating for the compliance vendor. Do NOT reach for a managed API as the default.
- **FOOTGUN (cold-start off the hot path):** the model artifact must be **baked in or pulled at boot**, never lazy-loaded per request; the service is **warm/always-on** (§E2.4) so a model-load cold-start is **NOT** on the ≤900 ms critical path (§9.2 lever 4).

### E2.2 — the CDK construct for the NER service (NEW, peer to the security-controller service)
- **File (new):** `cdk/cdk_constructs/phi_ner_service_construct.py` (a new construct alongside the pattern at [compute_stack.py:1651-1758](../../cdk/stacks/compute_stack.py#L1651)); wired into `ComputeStack.service_configs` (or its own stack section) — name the service **`phi-ner`** (CloudMap DNS `phi-ner.sentra.internal`).
- **Change:** an **`ecs.FargateTaskDefinition`** (2 vCPU / 4 GB per LLD §9.3 `~$71/mo` per warm task) + **`ecs.FargateService`** with:
  - an **internal ALB target group** (or CloudMap-only, service-to-service) — the controller reaches it at `phi-ner.sentra.internal`, private subnets only (`PRIVATE_WITH_EGRESS`), the controller SG allowed inbound.
  - a **warm-pool min count**: `desired_count ≥ 1` and an **autoscale target-util** (`service.auto_scale_task_count(min_capacity=N)` + `scale_on_cpu_utilization`/`scale_on_metric`) so scale-out is on utilization, **min_capacity never 0** — no cold model-load on the hot path.
  - `circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True)`, `enable_execute_command=True`, health-check `start_period` generous (model load).
- **Implements:** LLD §9.3 Option A, §10 (stateless fleet like the controller).
- **FOOTGUN:** this is a **stateless fleet** — it holds no per-tenant state between requests (F4 buffers are per-request). Do NOT give it a sticky/session-bound routing. `min_capacity=0` is the cold-start footgun — the warm pool is the whole point of Option A.

### E2.3 — the internal API contract the controller calls (request → redacted view)
- **File:** `src/security-controller/app/redaction/phi_ner.py` (the client the controller pipeline calls) + the served endpoint on the `phi-ner` container.
- **Change:** define the internal contract — the controller POSTs the surviving **free-text fields only** (never the whole request), the service returns the **redacted view** (free-text → typed tokens `<NAME>`, `<ADDRESS>`, `<CONDITION>`, …) and **discards raw**. Encrypted in transit (TLS, in-VPC). The response carries the redacted strings + the `redacted=True` provenance, never echoes raw.
- **Implements:** LLD §4.1, §4.2, §11.

### E2.4 — the transient-processing invariant + F4 tenant isolation (be very explicit)
- **File:** the `phi-ner` service code; deployment config.
- **Change — the F4 isolation contract (this is where raw PHI actually lives, §9.6/§8):**
  - **per-request raw-buffer lifecycle with zeroing:** each request's raw free-text is held in a per-request buffer, redacted, and the buffer **zeroed/dropped immediately** after the pass — no cross-request accumulation, no buffer reuse across tenants.
  - **NER-framework input-logging DISABLED:** spaCy / transformers / ONNX-Runtime **debug/verbose input logging OFF in prod** — the framework must never log the raw it processes.
  - **no shared crash dump exposes tenant raw:** body/input capture disabled; a crash must not serialize a live tenant's raw buffer.
  - **process-level isolation today + the deferred-enclave named residual:** the warm pool is shared **at process level** today (per-request buffers, not a provable boundary). A **provable** cross-tenant boundary for raw PHI is the **deferred Nitro/CVM enclave (§4.5)** — a named residual, NOT claimed present.
  - **no data egress off the account (IAM):** the service task role has **no** IAM permission to write raw anywhere and no egress to a third-party de-id API (self-host is the default); its only writes are the redacted view back to the controller.
- **Implements:** LLD §4.2 (mechanism d), §9.6, §8.
- **FOOTGUN:** the transient invariant is meaningless if the framework logs the input. Explicitly disable spaCy/transformers/ONNX input logging AND assert it (the §15.2 no-raw test exercises the service path).
- **OPEN ITEM (owner to confirm):** the **warm-pool sharing decision for BAA tenants** (§9.6) — process-level shared today; if a BAA tenant requires a provable boundary, that is the deferred enclave, not a within-plane control. Carry as open.

### E2.5 — data-class allowlist enforcement on free-text (Appendix F)
- **File:** the controller pipeline routing into `phi_ner.py`.
- **Change:** a field *label* does not classify free-text content. **STRUCTURED fields** → class-enforced at the schema/contract layer (disallowed class → blocked or routed to in-VPC). **FREE-TEXT fields** → Tier-2 NER owns; the residual is either redacted under the BAA/DPA, or the customer is on in-VPC, or — if Tier-2 cannot handle a field — the content is **HELD (not egressed onward), per E3** (not a blanket user-request rejection).
- **Implements:** LLD §4.3, Appendix F.
- **FOOTGUN:** do NOT treat a label-"allowed" free-text field as safe to forward raw. "Block/hold" here means *that field's content does not go onward raw*, while the safe portion proceeds (§4.3 owner p6).

---

## Milestone E3 — the happens-before BARRIER wiring (F1) — LLD §2.2/§4.1/§5.3

> **The load-bearing correctness task.** In the controller pipeline, Tier-2 NER **COMPLETES** before any deep-detector read / audit-signal write / meter-feedback write of PHI-bearing content. The parallel-overlap optimization applies ONLY to the non-PHI verdict-return path.

### E3.1 — pin the NER barrier ahead of the three consumers
- **File:** [validation_service.py](../../src/security-controller/app/services/validation_service.py) — the pipeline around `_capture` ([:239](../../src/security-controller/app/services/validation_service.py#L239)) and the off-path audit write ([:46-75](../../src/security-controller/app/services/validation_service.py#L46)).
- **Change:** on a PHI-bearing free-text field, sequence `NER → (redacted view) → { deep detectors (ML/Cedar/Sigma) read · audit/signal write · meter/feedback write }`. Each of the three consumers reads only the **post-NER redacted view**. `_shared_attrs_from_request` and `_build_log_event` are fed the redacted fields, not the original request.
- **Implements:** LLD §4.1, §5.3, F1.

### E3.2 — keep the overlap optimization on the NON-PHI verdict path only
- **File:** `validation_service.py` (the `to_thread` overlap primitive, LLD 24:51).
- **Change:** for a call whose fields carry no free-text PHI (or whose verdict the deterministic tier resolves without NER-gated content), issue the floor and any NER pass concurrently — verdict return adds `max(floor, redaction)`, not the sum. Do NOT extend this overlap to a PHI-bearing field's content.
- **Implements:** LLD §9.2 lever 3, §9.4.
- **FOOTGUN:** a PHI-bearing free-text call **pays NER on the critical path** (≤900 ms ML-hot budget, LLD 24), NOT hidden behind the ≤500 ms floor. Do not state or code it as "hidden behind the floor" on the PHI path — the barrier widens the raw-live window (§5.4).

---

## Milestone E4 — the NO-RAW-PHI invariant (I-1), proven not asserted — LLD §5

> The live clause-(a) violation surface is [audit_logger.py:223](../../src/security-controller/app/utils/audit_logger.py#L223)/[:307-308](../../src/security-controller/app/utils/audit_logger.py#L307)/[:320-321](../../src/security-controller/app/utils/audit_logger.py#L320): raw `tool_params` (full) + `user_input` (truncated 200) into the DynamoDB signal store + CloudWatch. Truncation-to-200 is **not** redaction. E4 cleans it and proves it.

### E4.1 — feed the audit/signal writer the redacted view + the redaction-state guard
- **File:** [audit_logger.py:223](../../src/security-controller/app/utils/audit_logger.py#L223) (`_shared_attrs_from_request`), [:307-308](../../src/security-controller/app/utils/audit_logger.py#L307)/[:320-321](../../src/security-controller/app/utils/audit_logger.py#L320) (`_build_log_event`); the writer entry.
- **Change:** the writer takes the **post-NER redacted fields**, never the original request. Add the cheap fail-secure first line: the writer **refuses to write any field not marked `redacted=True`** (provenance flag) → drop the write + emit `RawContentBlockedFromLog`, fail-secure (better a missing audit row than a raw-PHI breach).
- **Implements:** LLD §5.3, E5.

### E4.2 — the content-aware persist-gate (STRONGER independent detector, NOT the flag) — F2
- **File:** the admission gate in front of the signal store AND the feedback store (`validation_service.py` persist path).
- **Change:** the gate that admits a record to **any persisting store** runs a **content re-scan by a stronger, independent detector** (the §6.3 heavy reclassifier / Comprehend-Medical gate-only mode — independent of / at least as sensitive as the Tier-2 primary), NOT the provenance flag. A record passes only if the re-scan finds **no residual identifier**. The cheap flag check (E4.1) runs first as short-circuit; this re-scan is the authoritative admission gate.
- **Implements:** LLD §5.3.3, §6.3, F2.
- **FOOTGUN:** re-scan the **whole would-be-persisted record** (`redacted_payload` + `reason` + `winning_source`/matched-rule + `detector_outcomes`), not just the payload — a DENY `reason` that quotes offending free-text persists a raw fragment past the payload guard (§6.2 metadata footgun).

### E4.3 — the log-sink inventory (config-controlled sinks) — F5
- **File:** deployment config + runbook; the sink list is LLD §5.2.
- **Change:** name and control each sink — **ALB access logs** (request line only; Tier-1 strips URL-query secrets §E7), **API-Gateway execution/access logs** (data-tracing / full-request-body logging **disabled** in the stage config), **uvicorn/app request+exception logs** (no-raw-body-logging ban), **X-Ray/OTel spans** (no raw field in annotations/metadata; body not captured), **boto3/botocore** (log level ≥ INFO in prod, no DEBUG wire logging), **APM frame-local capture** (§E4.4). Mark each **config-control** (asserted by config + runbook) vs the persist path (**test-asserted**, §15.2).
- **Implements:** LLD §5.2 (log-sink inventory), F5.
- **FOOTGUN:** the config-control rows are **deployment controls, not code the guard enforces** — do NOT claim "every surface proven"; the claim is precise (persist path test-proven; ingress/transport sinks config-controlled).

### E4.4 — the frame-local / APM crash-path control — F7
- **File:** the error path [validation_service.py:206/213](../../src/security-controller/app/services/validation_service.py#L206); deployment APM config.
- **Change:** the log MESSAGE being clean is not enough — an uncaught exception before the NER barrier leaves the raw `ValidationRequest` in the frame's locals, and APM agents (Sentry/Datadog) capture frame locals / `repr(request)` by default. At least one of, and assert it: (1) **strip raw fields from the request object before any throwable code** (replace with the redacted view / drop) so a later exception has no raw in the frame; (2) an **APM/frame-local-capture assertion** in §15.2; (3) name **"disable APM local-variable capture in prod"** (Sentry `include_local_variables=False` / Datadog equiv) as a config-control row. Keep the raw object's lifetime minimal — redact/zero as soon as the NER pass returns.
- **Implements:** LLD §5.4, F7.

---

## Milestone E5 — opt-in redacted feedback store (separate from the audit store AND the meter store) — LLD §6

> A **separate, tenant-scoped** DynamoDB store of **REDACTED records only**, bounded TTL, **opt-in per DPA (default OFF)**, feeding the offline re-score/retrain loop. NOT the signal store (LLD 17), NOT the meter store (WS-H).

### E5.1 — the feedback-store CDK construct + schema
- **File (new):** `cdk/cdk_constructs/feedback_store_table_construct.py` — anchored on [signal_store_table_construct.py](../../cdk/cdk_constructs/signal_store_table_construct.py) for shape, with the deltas.
- **Change:** table schema (LLD §6.2): `tenant_id` (S, PK), `record_id` (S, SK `{ms}#{uuid}`), `subject_locator` (S, GSI PK — DSAR), `redacted_payload` (M, **REDACTED only**), `phase` (S), `decision`/`reason`/`winning_source` (S, from [deny_overrides.py:51](../../src/security-controller/app/combiners/deny_overrides.py#L51) `metadata["winning_source"]`), `detector_outcomes` (M, redacted), `ttl` (N, **default 90d, DPA-scoped placeholder — owner/counsel to set final**), `opt_in` (BOOL, default OFF), `redaction_eval_pass` (BOOL, §6.3 gate result). **CDK deltas:** enable DynamoDB TTL (`time_to_live_attribute="ttl"`); **PITR default OFF** (a PITR snapshot would outlive a DSAR deletion); keep `RemovalPolicy.RETAIN` deliberate.
- **Implements:** LLD §6.2, §12.
- **FOOTGUN (PITR vs DSAR):** if PITR is on, a continuous backup retains a deleted subject past the DSAR deletion (§6.4). Default PITR OFF (or scope the DSAR procedure to the PITR window). Do not silently inherit the signal store's setting.

### E5.2 — the content-aware eval-gate BEFORE any write (stronger detector) — E3.4/F3
- **File:** the write path into the feedback store (`validation_service.py` off-path telemetry [:46-75](../../src/security-controller/app/services/validation_service.py#L46)).
- **Change:** no record is written if a residual identifier is found by an **INDEPENDENT, STRONGER detector than the Tier-2 primary** (the E4.2 re-scan — the heavy offline reclassifier / Comprehend-Medical gate-only). A gate that re-runs the primary redactor is circular (F3). On a residual hit → skip the write + emit `FeedbackRedactionGateFail`.
- **Implements:** LLD §6.3, F3.

### E5.3 — opt-in default-OFF write path (SPLIT gate)
- **File:** the tenant registry (`sentra-tenants` row) + the write path.
- **Change:** write **only** when the tenant's `sentra-tenants` row carries the DPA-scoped opt-in flag (default **OFF**); off the response path (fire-and-forget after the verdict); writes the **redacted** record only. The opt-in gate is on the **persisted store only** — transient PHI processing for redaction itself is **ALWAYS-ON under the BAA** (the containment control, no consent gate).
- **Implements:** LLD §6.5, E8.
- **FOOTGUN (default OFF):** an accidental default-ON is a clause-(b) violation AND a consent breach (mirrors LLD 27's absent-key conservative-off trap). A non-opted-in tenant produces **no** record (§15.3 asserts it).

### E5.4 — DSAR/deletion API + salted-per-tenant subject_locator
- **File:** the operator-auth API surface (a new `DELETE /v1/feedback/subjects/{subject_locator}`); the write path (locator derivation).
- **Change:** `DELETE /v1/feedback/subjects/{subject_locator}` (operator-auth, tenant-scoped) deletes every record for a subject via the `subject_locator` GSI; tenant A cannot delete tenant B's (403). Derive `subject_locator` as a **salted keyed hash `HMAC(per-tenant-salt, subject_key)`** computed **at write time before masking** where a stable subject key exists; **where no stable subject key exists → `subject_locator` null/absent, the record is TTL-only-deletable** (concede — do NOT claim subject-targeted deletability).
- **Implements:** LLD §6.4 (GDPR Recital 26), §12.
- **FOOTGUN:** the honest GDPR claim is "deletable by expiry (TTL) + by subject where a subject key exists," never an unbacked blanket "deletable."

### E5.5 — the retrain loop hand-off (FR-3.14) — feedback-store CONTRACT only
- **File:** the feedback store schema/eval-gate (owned here); the batch job is NOT owned here.
- **Change:** guarantee the store the offline job reads is redaction-gated (redacted records only §6.2, content-aware eval-gate §6.3, TTL/DSAR §6.4). The **offline reclassify/retrain batch job itself is FR-3.14 (P2, NOT-DONE)** — it extends LLD 19 §4.3/§13.3 (Opus-in-batch eval/label/re-score) + WS-F (prompt-signature corpus). **There is no dedicated FR-3.14 retrain LLD yet — a named P2 gap to create when P2 is scheduled.** WS-E neither designs nor blocks on that job.
- **Implements:** LLD §6.6.

---

## Milestone E6 — image handling: per-tool `{redact | evaluate | block}` mode — LLD §3.6 (FR-3.15)

> Server-side Tier-2 only (edge never redacts pixels — a Tesseract binary + OCR/vision model cannot vendor into the stdlib SDK zip). The `evaluate` path is **REQUIRED for the B2C-fraud beachhead**. NOT "refuse every image."

### E6.1 — edge tags binary/image fields, never redacts pixels
- **File:** `redaction.py` + `_build_request`.
- **Change:** a field detected as binary/image at the edge (non-text bytes / a base64 blob over a size+entropy threshold) is **tagged** and routed to the server-side Tier-2 image handler — the edge never attempts pixel redaction and never sends raw on `block`.
- **Implements:** LLD §3.6, E2.

### E6.2 — the server-side mode router `{evaluate | redact | block}`
- **File:** the controller pipeline (image-field routing) + the mode resolution.
- **Change:** resolve the per-tool/per-customer mode and route:
  - **`evaluate` (REQUIRED — B2C-fraud beachhead):** pass the image **intact, un-redacted** to the fraud/threat evaluator (damaged-goods / insurance / return photos must reach the evaluator's pixels).
  - **`redact`:** route to the server-side image-redact pipeline (the **engine is the named LATER build** — Tesseract+Presidio, §E6.3).
  - **`block`** (default, fail-secure): refuse egress or pass-through per policy.
- **Implements:** LLD §3.6, E2.

### E6.3 — wire `{mode}` into the policy model; name the two later `redact`-engine steps
- **File:** the tool registry (`image_mode` per tool, resolved server-side) OR a Cedar attribute on the tool/resource read by the bundle (LLD 28).
- **Change:** the mode is a **tool-registry field `image_mode` `{redact|evaluate|block}`** (or Cedar attribute where policy-conditional); **defaults to `block`** for a tool with no explicit mode; fails toward `block`/refusal on an unresolvable mode. Name the two steps the later `redact` engine does NOT cover (so they aren't assumed done): (1) **faces** — Presidio image-redactor is text-only, needs a separate detector (Rekognition/Google DLP); (2) **DICOM metadata PHI** — a distinct metadata pass. WS-E ships the **mode contract + `evaluate`/`block` routing**; the `redact`-mode engine is the named later build.
- **Implements:** LLD §3.6 (Wiring `{mode}` into the policy model).
- **FOOTGUN:** default `block` (fail-secure); never default to `evaluate` (would pass raw pixels through for a tool that never intended it).

---

## Milestone E7 — URL / egress: REUSE FR-2.9, do not build a new subsystem — LLD §3.7

### E7.1 — destination control reuses the FR-2.9 egress policy
- **File:** the egress-destination policy (Cedar / FR-2.9 destination policy) — **NOT** a new redaction URL parser.
- **Change:** an **OWASP positive ALLOW-LIST** (validate scheme/host/port against an approved list) as the **primary** control, plus explicit denial of **169.254.169.254** (cloud-metadata) + RFC-1918 private ranges. Allow-list is required because deny-lists get bypassed (encodings, DNS-rebinding, redirects).
- **Implements:** LLD §3.7 (1), FR-2.9.
- **FOOTGUN:** do NOT stand up a parallel URL-validation subsystem in the redactor — destination-safety is the egress policy's job (reused).

### E7.2 — Tier-1 query-secret strip (supplement only)
- **File:** `redaction.py` (a URL-query matcher + the `<SECRET>`/entropy matcher).
- **Change:** scrub `?token=…` / `?api_key=…` secrets in the URL query component before egress, emitting `<URL>` with the secret-bearing query masked. This is a supplement to E7.1, not a replacement.
- **Implements:** LLD §3.7 (2).

---

## Milestone E8 — tests + gates — LLD §14, §15

> Tier-1 matcher UTs + the **HARD PCI 0-miss test** are deterministic (NOT recall-gated). The fuzzy Tier-2 recall gate is the **WS-0-gated NUMBER — mark GATED**. The LIVE e2e test uses real infra (no mocks).

### E8.1 — Tier-1 unit tests (matchers + grammar + per-phase + fail-secure + image mode + stdlib guard)
- **File (new):** `demo-agents/sdk/aegion-guard-python/tests/test_redaction.py` (`asyncio_mode=auto`, `testpaths=tests`).
- **Change (LLD §15.1):** per-matcher (PAN Luhn → `<CARD:6:4>` middle-digits-gone; Luhn-fail 16-digit **not** carded; SAD → `<SAD>` no value; each of SSN/email/phone/IP/URL/MRN/account/license/device/date → its token; high-entropy → `<SECRET>`; low-entropy UUID/order-no **not** scrubbed); **ordering** (PAN → `<CARD:6:4>`, not bare `<NUMBER>`/`<SECRET>`); **grammar/namespacing** (plant `⟦AEGR:…⟧` + bare `<CARD>` → neither reads as a genuine marker); **per-phase** (PII in `content`/`output`/`memory`/`request` → typed token on the wire, not raw); **fail-secure** (force `redact()` raise → DENY, `_send` never called with raw); **image mode routing** (`block` refused / `evaluate` pixels-intact pass-through / `redact` routed / no-mode defaults `block`); **stdlib-only guard** (`aegion_guard.redaction` imports with no third-party dep; `dependencies == []` unchanged).
- **Implements:** LLD §15.1.

### E8.2 — the HARD PCI SAD/PAN 0-miss deterministic test (release-blocking, SEPARATE)
- **File (new):** `src/security-controller/tests/corpus/pci_sad_pan.jsonl` + `test_pci_deterministic.py`.
- **Change (LLD §15.4):** cover Luhn-valid PANs (canonical + spaced/dashed + embedded-in-prose) + label-anchored SAD (CVV/track/PIN). Target = **hard 0-miss**: every Luhn-valid PAN emits `<CARD:6:4>` (middle gone), every SAD dropped (no value). A single miss **fails** the test and is **release-blocking**. Held apart from the fuzzy `redaction_recall.jsonl`.
- **Implements:** LLD §15.4, §15.5 (the separate PCI gate row), invariant #5.
- **FOOTGUN:** never average this into the WS-0-gated fuzzy Tier-2 number.

### E8.3 — the NO-RAW-PHI negative-control test (incl. frame-local/APM)
- **File (new):** `src/security-controller/tests/test_redaction_no_raw_logging.py`.
- **Change (LLD §15.2):** audit/signal writer + CloudWatch carry the **typed token**, raw substring absent; redaction-state guard drops an un-flagged field + emits `RawContentBlockedFromLog`; crash-dump path (raise mid-pipeline) → no raw in the exception log; **frame-locals/APM (F7)** (raise before the NER barrier → no raw in captured frame locals / `repr(request)`); Tier-2 egress-fail-closed (E3) — held/dropped, safe fields process, not blanket-DENYed, `EgressHeldCount`/`NerUnavailableCount` emitted; **negative controls** — a "skip-store but forward raw anyway" variant AND a "logs the raw body" writer must make the test **FAIL** (proves it isn't vacuous).
- **Implements:** LLD §15.2, E5/E6, F7.

### E8.4 — feedback-store unit tests
- **File (new):** `src/security-controller/tests/test_feedback_store.py`.
- **Change (LLD §15.3):** redacted-only (raw write rejected); opt-in default OFF (non-opted-in → no record; opted-in → redacted record); eval-gate (a residual-hit record not written + `FeedbackRedactionGateFail`); TTL set; DSAR deletion (`DELETE /v1/feedback/subjects/{locator}` removes a subject; tenant A can't delete tenant B → 403); tenant isolation (A can't read B).
- **Implements:** LLD §15.3.

### E8.5 — the redaction-recall eval harness (fuzzy Tier-2 number — GATED)
- **File (new):** `src/security-controller/tests/corpus/redaction_recall.jsonl` + `test_redaction_recall.py`.
- **Change (LLD §15.4):** measure per-class identifier false-negative rate against a **labeled corpus** — `(text, [{class, span}])` — running Tier-1 (and Tier-2 for free-text). **Corpus composition = canonical + obfuscated/encoded + non-US + narrative-embedded PHI** (Appendix G (ii)) — a canonical-only pass is vacuous (E12). The §6.3 feedback eval reuses this measure.
- **GATED:** the per-class recall **NUMBER / threshold is the WS-0-gated value** (residual #5 masked-recall precondition, LLD §15.5 (i)). The harness ships now; **locking the structured-token redactor as the GA gate is GATED on WS-0's recall-delta + §15.5 (i)-(iii) on paper.** The HIPAA GA claim is additionally gated on the Tier-2 recall target + counsel BAA sign-off + I-1 proven.
- **Implements:** LLD §15.4, §15.5.

### E8.6 — the LIVE e2e integration test (real ALB + DDB + NER-service, no mocks)
- **File (new):** `tests/integration/test_redaction_e2e.py` — markers `@pytest.mark.integration` + `requires_services`, fixtures `service_urls`/`api_headers` from [tests/integration/conftest.py](../../tests/integration/conftest.py); real **SDK → ALB → controller → DynamoDB signal store + CloudWatch + feedback store + `phi-ner` service**, profile `sentra`, `us-east-1`.
- **Change (LLD §15.6):** no-raw-crosses (card+SSN+email → typed tokens on the wire, raw absent from signal store + CW after round-trip); per-phase (`content` field); Tier-2 PHI path (a name in prose on a BAA tenant → `<NAME>` persisted, raw absent from every log); feedback-store opt-in (opted-in → redacted record; non-opted-in → none; DSAR removes it); fail-secure both paths (Tier-1 error → hard-DENY, no raw wire/persist; Tier-2 outage → egress-fail-closed E3, safe portion proceeds, raw absent from wire AND every store, `EgressHeldCount`); phase-unknown → **422 validation error (WS-B's path, lld/30 §3.1 — not a deny, not metered)**, known-but-unbuilt phase → fail-secure DENY.
- **Implements:** LLD §15.6.
- **FOOTGUN:** runs **post-deploy/pre-promote** (with LLD 27 §7 post-cutover suite + WS-J), NOT the hermetic per-PR gate — needs live infra. The no-raw-in-logs assertion is **release-blocking**: a raw value in a live log fails the promote.

### E8.7 — redaction latency + failure metrics (owner p8)
- **File:** [metrics_publisher.py](../../src/security-controller/app/utils/metrics_publisher.py) (the existing surface); the SDK for the edge counter.
- **Change (LLD §9.5):** publish **per-tier latency** `RedactionTier1LatencyMs` (edge, SDK if telemetry on), `RedactionTier2NerLatencyMs` (p50/p99 dims), `RedactionOverlapSlackMs` (floor − NER); **failure counters** `RedactionFailCount`, `EgressHeldCount`, `NerUnavailableCount`; the invariant metrics `RawContentBlockedFromLog` (§5.3) + `FeedbackRedactionGateFail` (§6.3).
- **Implements:** LLD §9.5.
- **FOOTGUN:** off the response path (fire-and-forget) — a metric failure never blocks a verdict; these are ops signals, NOT the billing ledger (WS-H).

---

## Acceptance criteria

**Gate**
- [ ] 🔒 **SPIKE GATE:** WS-0's dated, signed packet exists before ANY WS-E build starts (00-index). The masked-vs-unmasked recall-delta (residual #5) is signed off **before** the structured-token redactor is locked as the GA gate.

**E1 — Tier-1 edge deterministic redactor** ✅ **DONE + DEPLOYED** (SDK on `main` @ `44947ea`; live in all 3 acme connectors — payments Lambda + identity/telecom Azure funcs — 2026-07-02)
- [x] Tier-1 redactor exists in the SDK, **stdlib-only** (`pyproject.toml` runtime `dependencies == []` unchanged), masking PAN(first6/last4)/SAD(drop)/SSN/email/phone/IP/URL/MRN-account-license-device/dates/high-entropy-secrets into **typed tokens** via the frozen `_ORDERED_MATCHERS` (SAD→PAN→…→SECRET). <!-- normalize-then-detect rewrite (LLD 29a) closed the separator-leak class -->
- [x] Redaction runs on **every egressing phase** (`request|content|output|memory`) in `_build_request` before `_send` — a test sends PII in a `content` field and asserts the typed token, not raw.
- [x] Typed-token grammar is `⟦AEGR:{nonce}:TYPE[:meta]⟧` (sentinel + per-call nonce); a planted `⟦AEGR:…⟧`/`<CARD>` cannot forge a marker (M-4); `redaction_nonce` on the payload.
- [x] `<CARD:6:4>` carries first6/last4 only (middle digits gone); `<SAD>` carries no value.
- [x] Redactor fails **secure** — an exception → DENY (`redaction_failed`), never `_send` raw.

**E2 — the PHI-NER model-serving CONTAINER (P0)** ⬜ **BUILT (synth-verified) but NOT DEPLOYED — GA-gated.** Constructs on `main` @ `3ae42e8` (Dockerfile.phi-ner + phi_ner_service_construct.py + feedback_store_table_construct.py, 44 CDK tests + `cdk synth` green); deliberately NOT wired into any deployable stack — held on WS-0 recall + counsel BAA (model selection/GA-lock).
- [x] A **separate** `phi-ner` ECS/Fargate service exists (distinct from `security-controller`), model-resident (self-host Presidio + distilled PHI-NER ONNX-int8), a **stateless warm fleet** — its own `docker/Dockerfile.phi-ner` + `cdk/cdk_constructs/phi_ner_service_construct.py` (FargateTaskDefinition + FargateService + internal target/CloudMap `phi-ner.sentra.internal`). <!-- construct built + synth-asserted; NOT deployed -->
- [x] **Warm-pool min count ≥ 1 with autoscale target-util (min_capacity never 0)** — no model-load cold-start on the ≤900 ms hot path. <!-- asserted in the CDK construct test -->
- [x] The internal API contract POSTs **free-text fields only**, returns the **redacted view**, discards raw; TLS in-VPC; IAM = no data egress off the account, no third-party de-id subprocessor. <!-- served endpoint built (stub NER); real model = GA-gated -->
- [x] **F4 tenant isolation:** per-request raw-buffer zeroing; NER-framework input-logging DISABLED; no shared crash dump exposes tenant raw; process-level isolation today with the **deferred enclave named as the residual** for a provable boundary.
- [x] Model choice is **self-host (BUILD, no new subprocessor)**; Comprehend Medical is fallback-only if self-host misses §15.5. <!-- self-host stub shipped; model SELECTION locked on WS-0 recall -->
- [x] Free-text data-class allowlist enforced (Appendix F): label does not classify free-text; residual redacted under BAA / in-VPC / **held (E3)**.

**E3 — the F1 barrier** ✅ **DONE + DEPLOYED** (DAG entry node; server on `main` @ `a2a2553`, live milestone-93+)
- [x] On a PHI-bearing free-text field, NER **completes before** any deep-detector read / audit-signal write / meter-feedback write of that content (the three read only the post-NER redacted view); the overlap optimization is confined to the **non-PHI verdict-return** path. <!-- reconciled to WS-C DAG as an entry node that redacts request.content_text in place -->
- [x] A PHI-bearing call pays NER on the **critical path** (≤900 ms ML-hot), NOT "hidden behind the floor."

**E4 — NO-RAW-PHI invariant (I-1)** ✅ **DONE + DEPLOYED** (strict fail-secure live milestone-95 @ `1339174`); F7 partial — see note
- [x] The audit/signal writer + CloudWatch carry the **redacted view** (the `audit_logger.py` 223/307/320 raw surface is cleaned); a field without `redacted=True` is dropped + `RawContentBlockedFromLog` (fail-secure). <!-- STRICT after the connector edge-rollout (transition truncate-fallback removed) -->
- [x] The persist-gate for **any** persisting store is a **content re-scan by a stronger independent detector** (NOT the flag), over the WHOLE record (payload + reason + winning_source + detector_outcomes). <!-- IndependentGateDetector; NOTE: stage-2 stub (narrow patterns) — the heavy reclassifier is stage-3/§6.6 -->
- [x] The log-sink inventory is controlled (ALB/API-GW/uvicorn/X-Ray/boto3/APM) — persist path **test-asserted** (§15.2), transport/ingress **config-controlled** (not over-claimed).
- [x] The frame-local/APM crash-path control holds and is asserted (F7). <!-- DONE (milestone-97, `9059071`): strip-early in validate_tool_call's finally scrubs raw content off the request on every exit path (normal+crash); test_frame_local_no_raw.py pins it, non-vacuous. Option-3 (APM include_local_variables=False config row) still open — deferred, no APM installed. -->

**E5 — opt-in redacted feedback store** ✅ **LOGIC DONE + DEPLOYED (moto-tested, live in controller); TABLE construct built not deployed (GA-gated w/ E2)**
- [x] A **separate**, tenant-scoped, **redacted-records-only** DynamoDB table (NOT signal store, NOT meter store), DynamoDB TTL enabled (default 90d DPA-scoped placeholder), **PITR OFF**; a test asserts no raw can be written. <!-- feedback_store_table_construct.py built + synth-asserted; TABLE not deployed (held w/ E2) -->
- [x] Write is **opt-in default OFF** (per-DPA `sentra-tenants` flag) — a non-opted-in tenant produces **no** record; transient redaction stays always-on under the BAA.
- [x] The eval-gate before any write uses a **stronger independent detector** (not the primary redactor); a residual hit → skip write + `FeedbackRedactionGateFail`.
- [x] `DELETE /v1/feedback/subjects/{subject_locator}` deletes a subject (tenant-scoped, 403 cross-tenant); `subject_locator` = salted `HMAC(per-tenant-salt, subject_key)` where a stable key exists, else TTL-only-deletable (conceded). <!-- route wired routes.py:820; live once the table is deployed -->
- [x] The store contract is redaction-gated for the FR-3.14 offline job (the batch job itself is a named P2 gap, not built here).

**E6 — image per-tool mode** ✅ **DONE + DEPLOYED** (server router `a2a2553`)
- [x] Image/binary is **server-side Tier-2 only** (edge never redacts pixels); a per-tool `image_mode` `{redact|evaluate|block}` (tool-registry field / Cedar attribute) resolves the behavior, **defaults to `block`**.
- [x] The **`evaluate`** path passes pixels **intact** to the fraud evaluator (B2C-fraud beachhead requirement); the `redact`-mode engine (Tesseract+Presidio+faces+DICOM) is named as the **later build**, faces + DICOM called out as separate steps. NOT a blanket "refuse image."

**E7 — URL/egress** ✅ Tier-1 query-secret strip DONE + deployed · ⬜ FR-2.9 destination allow-list is an UNBUILT upstream dependency (P1, owned by WS-A, pending)
- [ ] Destination control **reuses FR-2.9** (OWASP positive allow-list; deny 169.254.169.254 + private ranges) — no new URL subsystem; Tier-1 strips URL-query secrets as a supplement. <!-- Tier-1 query-secret strip: DONE + live. FR-2.9 destination allow-list: NOT built (P1, dependency on WS-A per prd:129/275) — WS-E only reuses it -->
- [x] Tier-1 URL query-secret strip (`?token=`/`?api_key=`) — DONE + deployed in the SDK redactor (the WS-E-owned half of E7).

**E8 — tests + gates**
- [x] Tier-1 matcher UTs pass (matchers + grammar + per-phase + fail-secure + image-mode + stdlib guard). <!-- SDK unit suite green: `cd demo-agents/sdk/aegion-guard-python && PYTHONPATH=src python3 -m pytest tests/ -q` @ 44947ea8d26f0772a3e104b0c64632632c62c994 (image-mode facet is server-side Tier-2, not in this Tier-1 slice) -->
- [x] The **HARD PCI SAD/PAN 0-miss test** (`corpus/pci_sad_pan.jsonl` + `test_pci_deterministic.py`) passes — release-blocking, SEPARATE from the fuzzy target. <!-- SDK unit suite green: `cd demo-agents/sdk/aegion-guard-python && PYTHONPATH=src python3 -m pytest tests/ -q` @ 44947ea8d26f0772a3e104b0c64632632c62c994 -->
- [x] The NO-RAW-PHI negative-control test passes (incl. frame-local/APM); the "skip-store but forward raw" and "logs raw body" variants make it FAIL. <!-- test_redaction_no_raw_logging.py, 12 tests, non-vacuous verified. frame-local/APM facet = partial (see E4 note) -->
- [ ] The redaction-recall eval harness runs on the obfuscated/non-US/narrative corpus; the **recall NUMBER/threshold is WS-0-GATED** (structured-token GA-gate lock gated on the WS-0 recall-delta + §15.5 (i)-(iii)). <!-- GATED — WS-0 recall number -->
- [ ] The LIVE e2e integration test (real ALB + DDB + `phi-ner`, no mocks) passes post-deploy/pre-promote; no-raw-in-logs is release-blocking. <!-- GATED on phi-ner deploy (GA-gated) -->
- [x] Per-tier latency + failure metrics published off the response path. <!-- 17 redaction metrics in metrics_publisher.py -->
- [ ] **Release gate (not code):** counsel BAA sign-off (45 CFR 164.308/164.314) + the §7.2 breach argument recorded before any HIPAA GA claim; GDPR wording = **pseudonymisation**, never "anonymised"/"Safe-Harbor de-identified" for un-scrubbed free-text (doc + UI copy check). <!-- release gate, not code -->

**Open items carried (from LLD 29):**
- [ ] Counsel sign-off on the §7.2 BAA-permitted-use + 164.402 low-probability-of-compromise breach argument (release gate, §7.3).
- [ ] The WS-0 **recall number + latency benchmark** (gates E2 model-selection/GA-lock + E8.5 threshold). <!-- WS-0 packet measured @ 9e31dca, awaiting founder signature -->
- [ ] The **warm-pool sharing decision for BAA tenants** (§9.6) — process-level today; owner to confirm whether any BAA tenant needs the deferred enclave boundary.
- [x] ADR-032 to be recorded in [adr.md](../../adr.md) — **DONE** (adr.md:1292 "Two-Tier Input Redaction and the Three-Clause NFR-7 Amendment").
- [ ] The **FR-3.14 retrain batch job** is a separate P2 LLD gap to create when P2 is scheduled (LLD 19 §4.3/§13.3 + WS-F extend it).
- [ ] **NEW (pre-HIPAA-GA hardening):** (a) the APM `include_local_variables=False` config-control row (E4.4 option 3) for any FUTURE Sentry/Datadog integration — deferred, no APM installed today; (b) the persist-gate `IndependentGateDetector` is a stage-2 stub → replace with the heavy reclassifier (§6.3/§6.6) before HIPAA GA. *(F7 strip-early + assertion: DONE, milestone-97.)*

---

## Cross-references

- **LLD sections:** §3 (Tier-1 edge redactor — E1) · §4 + §9.3 Option A + §9.6 (Tier-2 NER container + F4 isolation — E2) · §2.2/§4.1/§5.3 (F1 barrier — E3) · §5 (NO-RAW-PHI I-1 — E4) · §6 (opt-in feedback store — E5) · §3.6 (image mode — E6) · §3.7 (URL/egress reuse FR-2.9 — E7) · §14/§15 (tests + gates — E8) · §7 (compliance basis: containment + BAA-permitted-use, F8) · §16 (error model E1–E12).
- **Sub-PRD:** [prd/serverless-edition.md](../../prd/serverless-edition.md) §5 — FR-3.13 NOT-DONE, FR-3.14 NOT-DONE, FR-3.7 NOT-DONE (task normally).
- **Decisions:** **ADR-032** (two-tier redactor + NFR-7 (c) PHI-transit-under-BAA + the F1 barrier ordering-refinement — elaborated here, NOT re-opened; to be recorded in [adr.md](../../adr.md)) · **AD-6** (data-boundary lever per edition) · **AD-3** (the `phase` field).
- **Shared contracts (join keys):** `redact(value, *, nonce) -> str` · typed-token grammar `⟦AEGR:{nonce}:TYPE[:meta]⟧` · `redaction_nonce` (additive payload field) · `phase` enum (shared with **WS-B**) · `redacted=True` provenance flag + the redaction-state guard · `image_mode` enum `{redact|evaluate|block}` (default `block`) · the **feedback store** table `{tenant_id, record_id, subject_locator, redacted_payload, phase, decision, reason, winning_source, detector_outcomes, ttl, opt_in, redaction_eval_pass}` (NET-NEW; NOT the signal store, NOT the meter store) · `DELETE /v1/feedback/subjects/{subject_locator}` · metrics `RawContentBlockedFromLog`, `FeedbackRedactionGateFail`, `RedactionTier1LatencyMs`, `RedactionTier2NerLatencyMs`, `RedactionOverlapSlackMs`, `RedactionFailCount`, `EgressHeldCount`, `NerUnavailableCount` · the `phi-ner` ECS service (CloudMap `phi-ner.sentra.internal`) + `docker/Dockerfile.phi-ner` + `cdk/cdk_constructs/phi_ner_service_construct.py` · the recall harness `corpus/redaction_recall.jsonl` + the PCI corpus `corpus/pci_sad_pan.jsonl`.
- **Sibling workstreams:** **WS-0** [ws-0-measure-first-spike.md](ws-0-measure-first-spike.md) (**gates this WS**; the recall-delta that locks the GA gate + the kill/pivot branch) · **WS-B** [ws-b-multiphase-contract.md](ws-b-multiphase-contract.md) (owns the `phase` field; redaction runs per-phase) · **WS-H** (the **meter store** — the feedback store is NOT it; the §14 split) · **WS-F** [ws-f-prompt-signatures.md](ws-f-prompt-signatures.md) (shares the FR-3.14 retrain corpus / prompt-signature loop) · **WS-I** [ws-i-cedar-engine.md](ws-i-cedar-engine.md) (the bundle/`phase`; Cedar decides policy, redaction scrubs content — distinct).
- **Related LLDs:** [LLD 23](../../lld/23-sentra-guard-sdk.md) (stdlib-only SDK — Tier-1 adds no native dep) · [LLD 17](../../lld/17-validation-signal-store.md) (the signal store the feedback store is separate from; cleaned of raw by §5) · [LLD 19](../../lld/19-ml-threat-classifier.md) (the retrain target the feedback loop feeds) · [LLD 28](../../lld/28-cedar-policy-engine.md) (bundle/`phase`; `image_mode` as a Cedar attribute) · [LLD 27](../../lld/27-serverless-production-activation.md) (the stateless-fleet pattern the `phi-ner` service follows; conservative-off flag discipline).
- **Code anchors:** [guard.py:325](../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L325)/[:371-389](../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L371)/[:391-406](../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L391) · [config.py:93/164-165](../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/config.py#L93) · [pyproject.toml](../../demo-agents/sdk/aegion-guard-python/pyproject.toml) (`dependencies = []`) · [models.py:17-39](../../src/security-controller/app/api/models.py#L17) (`ValidationRequest` — add `phase`) · [audit_logger.py:223](../../src/security-controller/app/utils/audit_logger.py#L223)/[:307-308](../../src/security-controller/app/utils/audit_logger.py#L307)/[:320-321](../../src/security-controller/app/utils/audit_logger.py#L320) (the live raw-logging surface §5 cleans) · [validation_service.py:46-75](../../src/security-controller/app/services/validation_service.py#L46)/[:239](../../src/security-controller/app/services/validation_service.py#L239)/[:206/213](../../src/security-controller/app/services/validation_service.py#L206) · [deny_overrides.py:51](../../src/security-controller/app/combiners/deny_overrides.py#L51) (`winning_source`) · [compute_stack.py:1651-1758](../../cdk/stacks/compute_stack.py#L1651) (the FargateTaskDefinition/FargateService pattern the `phi-ner` construct follows) · [signal_store_table_construct.py:80-81](../../cdk/cdk_constructs/signal_store_table_construct.py#L80) (the feedback-store CDK basis — TTL + PITR deltas). **New:** `aegion_guard/redaction.py`, `app/redaction/phi_ner.py`, `docker/Dockerfile.phi-ner`, `cdk/cdk_constructs/phi_ner_service_construct.py`, `cdk/cdk_constructs/feedback_store_table_construct.py`, `tests/corpus/redaction_recall.jsonl`, `tests/corpus/pci_sad_pan.jsonl`.
- **Skills:** `sentra:threat-taxonomy` (the detector contract the redacted typed-token text still feeds) · `sentra:cedar-policy-patterns` (Cedar decides policy, redaction scrubs content — distinct).
