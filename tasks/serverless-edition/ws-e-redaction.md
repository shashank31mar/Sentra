# WS-E: Two-Tier Redaction + Redacted Feedback Store

> **Doc role:** This is the **workstream SCOPE** — boundary, dependencies, real `file:line` anchors, footguns, and acceptance criteria. It is an **INPUT to this workstream's implementation-grade LLD**, *not* the granular task breakdown. The granular, buildable tasks are generated **from the approved LLD** (canonical order: HLD → LLD → tasks). See [00-index.md](00-index.md) for the doc-role map.

**Parent HLD**: [hld/serverless-edition.md](../../hld/serverless-edition.md) §8 hand-off row 5 (`FR-3.13 boundary`) + §6.2(e) ("Keeping the customer's data safe") + Appendix F (data-class allowlist) + Appendix G (the gate's pass/fail rule) + Appendix I (PHI mechanism / enclave hardening).
**Status**: Not started
**Owner**: TBD
**Implements**: **FR-3.13** (input-side PII/credential redaction — *all* egressing phases, NOT-DONE) · **FR-3.14** (continuous improvement: red-team + retrain + retrospective re-score — NOT-DONE) · **NFR-7** (Serverless data-boundary trust model, **3-clause amended**) · **ADR-032** (two-tier redactor + NFR-7 (c) PHI-transit-under-BAA amendment).

> **Next step: an implementation-grade LLD.** This WS doc scopes the build — what to build, where it touches code, the invariants it must prove, and the acceptance bar. The concrete schemas, function signatures, regex/checksum tables, NER model choice, exact file diffs, and per-class test cases are produced by the LLD that follows it. Per the owner directive, **the LLD goes to implementation level** and extends **three** docs: LLD 23 (SDK edge redactor), LLD 17 (validation signal store → feedback store), and a **NEW server-side-semantic-redaction LLD** (+ counsel sign-off on the BAA). Until that LLD is approved, treat every pseudo-code block here as a sketch with real names, not a spec.

> **GATE — do NOT start the build of this WS until WS-0 (the measure-first spike) signs off.** Per HLD §8 MEASURE-FIRST GATE, the **masked-vs-unmasked recall-delta** (residual #5) is a **precondition of locking the redaction GA gate** — it must be on paper *before* the structured-token redactor is locked as the gate. WS-0 owns producing that delta (exfiltration + indirect-injection, on an obfuscated/non-US corpus). The redactor still *ships* at GA regardless; what is forbidden is **declaring the deep-tier depth claim met on masked content before the delta exists**. The kill/pivot branch (worst quadrant: high escalation AND low masked-recall) is decided in WS-0, not here.

---

## 1. Dependencies

- **Depends on**:
  - **WS-0** (measure-first spike) — **HARD gate**: produces the recall-delta that locks (or re-scopes) the GA redaction gate. No WS-0 signed packet → this WS does not start.
  - **WS-D / WS-B contract growth** — the `phase` field. WS-E adds redaction *to every egressing phase*; the `phase` enum itself is added by the contract workstream (`ValidationRequest`, [models.py:17](../../src/security-controller/app/api/models.py#L17) — **no `phase` field today**, default `"request"`). If that WS has not landed `phase`, WS-E adds the field as an **explicit prerequisite task (E1.0)**, not an assumption.
  - **Counsel (legal)** — BAA obligations (45 CFR 164.308/164.314) must be confirmed **before the HIPAA GA claim ships** (Tier-2 / feedback store). Not a code dependency; a release-gate dependency.
- **Blocks**:
  - Any "Serverless serves HIPAA/PHI customer" or "sensitive-data customer" GA claim — the redactor is the **hard GA gate** for those segments (HLD §6.2(e)).
  - **FR-3.14 retrain loop** (E3) consumes the redacted feedback store this WS builds; the offline re-score / retrain depend on the store + the redaction-quality eval.
- **Shared**:
  - SDK request build — `_build_request` ([guard.py:325](../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L325), payload assembly [:373-389](../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L373)) — shared with the SDK contract WS. **Footgun**: the SDK is **stdlib-only by design** ([pyproject.toml:23-26](../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/pyproject.toml#L23), `dependencies = []`; LLD 23 §2). Tier-1 MUST stay stdlib-only.
  - Signal/feedback store — [signal_store_table_construct.py:80-81](../../cdk/cdk_constructs/signal_store_table_construct.py#L80) (`RETAIN`, `point_in_time_recovery=False`) — shared with LLD 17 / WS-17.
  - Pipeline `_capture` / trail — [validation_service.py:239](../../src/security-controller/app/services/validation_service.py#L239) (`_capture(result)`) — shared with the trail WS; **the redacted record written here must carry NO raw value** (invariant I-1 below).

---

## 2. Model — read before coding

The hard model the implementer must hold. Violating any of these is a defect, and under clause (c) a **logging bug is a reportable breach**, not a missed NFR.

**M-1. Two tiers, two homes, one boundary.**
- **Tier 1 — edge deterministic redactor, IN THE SDK** (ships in the SDK install). Regex + Luhn + Shannon-entropy + format-anchored matchers. Replaces *values* with **structure-preserving typed tokens** (`<CARD>`, `<SSN>`, `<EMAIL>`, `<SECRET>`, …). Sub-ms, in-process, **raw never leaves the customer** for structured PII/PCI. Runs **before egress on EVERY phase** (request/content/output/memory), not just `request`.
- **Tier 2 — server-side free-text PHI semantic NER**, on the hosted PDP. **P0 — first-wave build** (owner decision): it ships in the *initial* Serverless build alongside Tier 1, NOT deferred. Too heavy for the stdlib edge (spaCy ≈50 ms+, transformer ≈700 ms — blows the ≤500 ms floor). Processes raw free-text **transiently under a BAA**, redacts in place, **never retains, never logs, no human access** (mechanism d). The **Nitro Enclave (mechanism b, Appendix I) is a NAMED LATER hardening, NOT this WS.** Edge native-NER (mechanism a) is a premium "strict-residency" tier, also NOT this WS.

**M-2. NFR-7 has THREE clauses** (HLD §6.2(e), amended by ADR-032):
- **(a) No raw retention, any edition.** Raw/un-redacted content is **NEVER persisted on ANY edition** — not in logs, the audit/signal store, the meter store, the feedback store, or crash dumps.
- **(b) Redacted feedback store (opt-in).** Serverless MAY retain **REDACTED** records in a separate, access-controlled, OPT-IN, DPA-scoped, retention-bounded store for offline re-score + retrain. The only thing that may outlive a single transient evaluation.
- **(c) PHI transit clause.** Structured PII: raw never leaves (redacted inline at the edge). Free-text PHI: raw **MAY transit to the hosted PDP under a BAA**, redacted server-side transiently, never retained, never logged, no human access, then discarded. The honest claim is *"transient + not-retained + not-logged + no human access under a BAA"* — **NOT** "machine-unreadable by AegionAI" (our code reads the value to scrub it; "never readable" needs the enclave, later).

**M-3. Standards the redactor is anchored to** (do not invent your own list):
- **HIPAA Safe Harbor — 45 CFR 164.514(b)(2)** — 18 identifier categories. Structured ones (SSN, MRN/account/license/device numbers, phone/fax, email, IP/URL, explicit dates) → Tier 1. Free-text ones (names, prose addresses, conditions, the catch-all) → Tier 2.
- **PCI-DSS** — PAN masked to **first-six / last-four**; sensitive authentication data (CVV/CVC, full track, PIN) under a hard **never-store / never-log** rule. Most fully deterministic obligation; matters most for the fintech/payments beachhead.
- **GDPR Recital 26** — reversible masking/tokenization is **pseudonymisation** and **remains personal data**. Call it "pseudonymisation," **never** "anonymised" / "Safe-Harbor de-identified" for free-text we did not semantically scrub.

**M-4. Token namespacing/escape is a security control, not cosmetics.** An attacker can put the literal string `<CARD>` (or any token) into a `tool_param`/`user_input` to confuse the downstream detector or forge a "redaction happened" signal. The token grammar MUST be **namespaced + escaped** so an attacker-supplied token string is distinguishable from a real redaction marker. Decide the grammar once in the LLD (e.g. a reserved sentinel + per-call nonce or an escape of attacker-supplied `<`/`>` sequences) — **do NOT** use a bare `<CARD>` that any input can spoof.

**M-5. Structure preservation is the whole point.** Tier 1 replaces the *value* but preserves *shape/position* so the deep detectors still get structural signal (this is exactly what residual #5 measures the cost of). Do not collapse all redactions to a single opaque token; keep them **typed**.

**Scoped OUT of this WS (named, not silently dropped):**
- **FR-3.15 image/binary content** — the text redactor cannot scrub images. Image content is **blocked from egress or routed to in-VPC** until an image-redaction mechanism is designed. WS-E **stubs the refusal**, does not redact images.
- **FR-3.7 server-side `REDACT` verdict (content-rewrite path)** — acting on a REDACT verdict requires the PEP to *rewrite* outgoing content, which the decorator cannot do today (it only ALLOWs/DENYs). The rewrite path is a separate named LLD deliverable.

```mermaid
sequenceDiagram
  participant AG as AI agent
  participant SDK as SDK edge redactor (Tier 1, stdlib)
  participant PDP as Hosted PDP
  participant NER as Server-side semantic NER (Tier 2, BAA)
  participant FS as Redacted feedback store (opt-in)
  AG->>SDK: guarded call (any phase: request/content/output/memory)
  SDK->>SDK: regex+Luhn+entropy+format-anchor → typed tokens (raw structured PII never leaves)
  SDK->>PDP: egress payload (structured PII already masked; free-text PHI raw under BAA)
  PDP->>NER: free-text fields (transient, encrypted)
  NER-->>PDP: redacted free-text (raw discarded; NEVER logged/retained)
  PDP->>PDP: validate (deep tier sees typed tokens — recall-delta is WS-0's number)
  PDP-->>SDK: decision + reason + source
  opt tenant opted in (DPA-scoped)
    PDP->>FS: REDACTED record only (bounded TTL) → offline re-score/retrain (FR-3.14)
  end
```

---

## 3. Milestones → tasks

### Milestone E1 — Tier 1: edge deterministic redactor in the SDK (FR-3.13)

> Today the SDK egresses `tool_params` + `user_input` **un-redacted** ([guard.py:373-389](../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L373)), and only the `request` phase is wired ([_build_request](../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L325)). E1 builds the redactor and runs it on every phase.

- **E1.0 (prerequisite) — `phase` field on the contract.** If the SDK-contract WS has not yet added it: add an **additive, defaulted, validated** `phase` enum to `ValidationRequest` ([models.py:17](../../src/security-controller/app/api/models.py#L17)), `default="request"`, values `request|content|output|memory`. **Footgun**: this must be *additive + defaulted* (HLD tie-breaker A) — a breaking/required field re-cuts every SDK/connector. Unknown phase → fail-secure DENY, not silent accept.

- **E1.1 — the deterministic matcher set** (new module under `demo-agents/sdk/aegion-guard-python/src/aegion_guard/`, stdlib-only). Each matcher is `(detector → typed-token)`:

  | Class | Mechanism | Typed token | Standard | Note |
  |---|---|---|---|---|
  | PAN (card) | regex candidate → **Luhn check** | `<CARD:first6:last4>` | PCI-DSS | mask to first-6/last-4 — do NOT emit the full PAN even tokenized |
  | SAD (CVV/track/PIN) | format-anchored | `<SAD>` | PCI-DSS | **never-store / never-log** — drop the value entirely, no first/last retained |
  | SSN | regex (US) + format-anchor | `<SSN>` | HIPAA SH | obfuscated/non-US forms → measured leak (Appendix G) |
  | email | regex | `<EMAIL>` | HIPAA SH | |
  | phone/fax | regex | `<PHONE>` | HIPAA SH | |
  | IP / URL | regex | `<IP>` / `<URL>` | HIPAA SH | |
  | MRN / account / license / device no. | **format-anchored** (label-adjacent + shape) | `<MRN>` etc. | HIPAA SH | format-anchored, not pure shape — bounds false positives |
  | explicit dates | regex | `<DATE>` | HIPAA SH | |
  | high-entropy secret / API key | **Shannon entropy** threshold + charset heuristic | `<SECRET>` | — | entropy floor set in LLD; avoid scrubbing legitimate IDs |

  **Footgun**: order matters — run the **most specific / highest-harm matchers first** (SAD before generic numeric; PAN+Luhn before bare-number). A bare numeric matcher that runs first will mis-token a PAN as `<NUMBER>` and lose the first6/last4 obligation.

- **E1.2 — typed-token grammar with namespacing/escape** (M-4). Define the reserved grammar once; **escape or neutralize attacker-supplied token-looking strings in the raw input** before redaction so a planted `<CARD>` cannot masquerade as a real marker. Pseudo-code (real names):
  ```python
  # aegion_guard/redaction.py  (NEW, stdlib-only)
  def redact(value: str) -> str:
      escaped = _neutralize_planted_tokens(value)   # M-4: attacker can't forge <CARD>
      for matcher in _ORDERED_MATCHERS:              # E1.1, highest-harm first
          escaped = matcher.sub_typed_token(escaped) # value → <TYPE[:meta]>
      return escaped
  ```

- **E1.3 — run on EVERY egressing phase, not just `request`.** Wire `redact()` into the payload assembly so `tool_params`, `user_input`, and the `content`/`output`/`memory` fields are all redacted **before** `_send`. Touch-point: payload dict build at [guard.py:373-389](../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L373) (inside `_build_request`) — extend to redact each content-bearing field per `phase`. **Footgun**: do NOT redact only inside the `request` branch — `content` (retrieved docs, tool output, web text) is often the *richest* PII surface; leaving it raw is the live NOT-DONE bug.

- **E1.4 — fail-secure on redactor error.** If the redactor raises, the SDK must NOT egress the raw value. Align with the existing fail-secure default ([config.py:167](../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/config.py#L167), `_DEFAULT` True; `SENTRA_FAIL_SECURE` override) and the unknown→DENY path ([guard.py:416](../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L416)). **Footgun**: a redactor exception that falls through to `_send` with the raw payload is a clause-(a) violation — fail to DENY, never to "send unredacted."

- **E1.5 — image/binary refusal stub (FR-3.15 out-of-scope, named).** If a field is binary/image, **refuse egress or route to in-VPC** — do not attempt to redact and do not send raw. A named stub, not a redaction.

### Milestone E2 — Tier 2: server-side free-text PHI semantic NER (FR-3.13, mechanism d) — P0

> P0, first-wave — ships with Tier 1. Heavy NER is server-side, **off the blocking path where possible**. This is what lets HIPAA/PHI customers use Serverless under a BAA.

- **E2.1 — semantic NER layer (NEW server-side component).** Runs on the hosted PDP, on free-text fields surviving Tier 1. Catches Safe-Harbor free-text identifiers (names, prose addresses, conditions, profession, catch-all). Model choice (CPU spaCy vs transformer vs managed API) is an **LLD decision gated on the Appendix-G recall target** — name it, don't assume. Reference hybrids: Presidio (regex+NER), Comprehend Medical, Google Cloud SDP.

- **E2.2 — transient-processing invariant (mechanism d).** Raw PHI is processed **transiently**: redacted in place, **raw discarded immediately**, **never written to any log/store/crash dump**, **no human access**. Touch-points the LLD must prove clean: the request log path, `_capture(result)` ([validation_service.py:239](../../src/security-controller/app/services/validation_service.py#L239)), the fire-and-forget audit write, and any exception handler. **Footgun**: structured logging of the request body (a common debug aid) here = reportable breach. Audit/redact the log surface explicitly.

- **E2.3 — data-class allowlist enforcement (Appendix F).** A field *label* is a schema-level control only; it cannot stop a disallowed-class PII string in a free-text field. Enforce two ways: **(1) STRUCTURED fields** — class-enforced at the schema/contract layer (disallowed class → blocked or routed to in-VPC); **(2) FREE-TEXT fields** — NOT class-trustable from the label; the residual is owned: edge redactor catches structured-token PII even embedded in prose, and free-text non-structured PII is either redacted server-side under the BAA/DPA or the customer is on in-VPC, or held until Tier 2 ships. **Footgun**: do NOT treat a label-"allowed" free-text field as safe to egress raw.

### Milestone E3 — Opt-in DPA-scoped redacted feedback store + retrain loop (FR-3.14, NFR-7 (b))

> A **separate**, tenant-scoped store of **REDACTED records only**, bounded TTL, **opt-in per DPA**. Feeds the offline re-score + retrain loop. Gated on a redaction-quality eval + DSAR/deletion API + counsel.

- **E3.1 — feedback store table** (NEW; do NOT reuse the signal store as-is). Anchor against LLD 17 / [signal_store_table_construct.py](../../cdk/cdk_constructs/signal_store_table_construct.py). Proposed shape (LLD finalizes attrs/types):

  | Attr | Type | Notes |
  |---|---|---|
  | `tenant_id` | S (PK) | tenant-scoped isolation — never cross-tenant readable |
  | `record_id` | S (SK) | `{ms}#{uuid}` |
  | `redacted_payload` | M | **REDACTED only** — invariant I-1; no raw value ever |
  | `phase` | S | `request|content|output|memory` |
  | `decision` / `reason` / `winning_source` | S | from the combiner ([deny_overrides.py](../../src/security-controller/app/combiners/deny_overrides.py), `metadata['winning_source']`) |
  | `ttl` | N | bounded TTL (DynamoDB TTL attr) — record must expire; not retained indefinitely |
  | `opt_in` | BOOL | written only when tenant opted in (DPA) |

  CDK: a new construct; keep `RemovalPolicy.RETAIN` semantics deliberate, and **enable DynamoDB TTL** (the signal store does not set TTL today; this store must). **Footgun**: the signal store has `point_in_time_recovery=False` ([:81](../../cdk/cdk_constructs/signal_store_table_construct.py#L81)) — decide PITR explicitly for a store that may hold redacted-but-still-personal data (GDPR pseudonymisation = still personal data).

- **E3.2 — opt-in gate + write path.** Records written **only** when the tenant has opted in (DPA-scoped flag on the tenant registry). Write is off-path (after the verdict), and writes the **redacted** record — never the raw. **Footgun**: default OFF; an accidental default-ON is a clause-(b) violation and a consent breach.

- **E3.3 — DSAR / deletion API.** A per-tenant, per-subject deletion path (GDPR DSAR). The store must support targeted deletion before this WS can claim feedback-store GA.

- **E3.4 — redaction-quality eval gate.** The feedback store + retrain loop is **gated on a redaction-quality eval** (the Appendix-G recall measurement, owned by WS-0 for the gate-lock, re-run on the feedback corpus here). No retrain on a corpus whose redaction quality is unmeasured.

- **E3.5 — offline re-score + retrain loop (FR-3.14).** Offline job re-scores stored redacted records when signatures/models update; produces FP/FN metrics; retrains the edge deterministic floor / prompt-signatures. Extends LLD 19 (ML retrain) + the prompt-signature corpus (WS-F/(e2)). Off-path, batch — never on the validate hot path.

  ```mermaid
  flowchart LR
    V["verdict (off-path)"] -->|opt-in only| FS["redacted feedback store (bounded TTL)"]
    FS --> EVAL["redaction-quality eval (Appendix G)"]
    EVAL --> RS["offline re-score → FP/FN metrics"]
    RS --> RT["retrain edge floor / signatures (FR-3.14)"]
    FS --> DSAR["DSAR / deletion API"]
  ```

---

## 4. Error model

| Condition | Response |
|---|---|
| Tier-1 redactor raises on a field | **Fail-secure**: DENY / refuse egress; never `_send` raw ([guard.py:391](../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L391), respect `fail_secure` [config.py:167](../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/config.py#L167)) |
| Binary/image field (FR-3.15, out-of-scope) | Refuse egress or route to in-VPC; never send raw, never attempt text redaction |
| Tier-2 NER unavailable / errors on free-text PHI | Do NOT egress raw downstream and do NOT persist; fail the validate closed (deny) rather than process PHI without redaction |
| `phase` unknown / unparseable | Fail-secure DENY (E1.0); never default to "send everything" |
| Feedback-store write fails | Off-path, swallow + alarm; MUST NOT block the verdict and MUST NOT fall back to writing raw |
| Tenant not opted-in | No feedback-store write at all (default OFF) |
| Planted token string in input (`<CARD>` etc.) | Neutralize/escape (M-4); never let it read as a genuine redaction marker |

---

## 5. Acceptance criteria

- [ ] **GATE**: WS-0 recall-delta packet (masked-vs-unmasked, exfil + indirect-injection, obfuscated/non-US corpus) is signed off **before** this WS's redactor is locked as the GA gate.
- [ ] Tier-1 edge redactor exists in the SDK, **stdlib-only** (no runtime dep added to `pyproject.toml`), and masks PAN(first6/last4) / SAD(drop) / SSN / email / phone / IP / URL / MRN-account-license-device / dates / high-entropy secrets into **typed tokens**.
- [ ] Redaction runs on **every egressing phase** — `request`, `content`, `output`, `memory` — verified by a test that sends PII in a `content` field and asserts the egressed payload carries the typed token, not the raw value.
- [ ] Typed-token grammar is **namespaced/escaped**; a test plants `<CARD>` in raw input and asserts it cannot forge a redaction marker (M-4).
- [ ] PCI: PAN → first6/last4 only; SAD (CVV/track/PIN) **never stored, never logged** — asserted by test.
- [ ] Tier-2 server-side semantic NER ships P0; a test proves raw free-text PHI is **never written to logs / signal store / audit / feedback store / crash dumps** (invariant M-2 (a)/(c)) — the no-raw-PHI-in-logs invariant is **proven, not asserted**.
- [ ] Redactor fails **secure**: a redactor exception denies/refuses egress, never sends raw (test forces the exception).
- [ ] Image/binary content (FR-3.15) is refused/routed, not redacted — named stub present and tested.
- [ ] FR-3.7 REDACT-rewrite path is **explicitly out of scope** and noted as a separate LLD deliverable (not silently implemented or silently dropped).
- [ ] Redacted feedback store: separate, **tenant-scoped**, **redacted-records-only**, **bounded TTL**, **opt-in default OFF**; a test asserts no raw value can be written and a non-opted-in tenant produces no record.
- [ ] DSAR / deletion API exists and deletes a subject's records from the feedback store.
- [ ] Offline re-score / retrain loop (FR-3.14) consumes the feedback store off-path and produces FP/FN metrics; gated on the redaction-quality eval.
- [ ] Counsel BAA sign-off (45 CFR 164.308/164.314) recorded **before** any HIPAA GA claim ships (release gate, not a code check).
- [ ] GDPR wording: redaction is called **pseudonymisation**, never "anonymised" / "Safe-Harbor de-identified" for un-semantically-scrubbed free-text (doc + UI copy check).

---

## 6. Cross-references

- **HLD**: [hld/serverless-edition.md](../../hld/serverless-edition.md) §6.2(e), §6.1 (block diagram + edge-redaction flow), §8 hand-off row 5 (`FR-3.13 boundary`), MEASURE-FIRST GATE, residual #5 (recall-delta) + #7 (Serverless = PHI revenue edition under BAA), Appendix F (data-class allowlist), Appendix G (gate pass/fail rule), Appendix I (PHI mechanism d / enclave hardening b).
- **Sub-PRD**: [prd/serverless-edition.md](../../prd/serverless-edition.md) §5 status table — FR-3.13 NOT-DONE ([:282](../../prd/serverless-edition.md#L282)), FR-3.14 NOT-DONE ([:283](../../prd/serverless-edition.md#L283)), FR-3.7 NOT-DONE ([:144](../../prd/serverless-edition.md#L144)); open question §3 (un-redacted interim, [:413](../../prd/serverless-edition.md#L413)).
- **ADR**: ADR-032 (two-tier redactor + NFR-7 (c) PHI-transit amendment) — to be written in [adr.md](../../adr.md).
- **Sibling WS**: **WS-0** (measure-first spike — recall-delta gate, blocks this WS); **WS-A/B/D** (the `phase` contract growth + tenant registry the opt-in flag lives on); **WS-F** (prompt-signature rename — shares the FR-3.14 corpus/retrain loop).
- **LLDs the implementation-grade LLD extends**: **LLD 23** (SDK edge redactor; must NOT add a native runtime dep — preserve stdlib-only); **LLD 17** ([validation signal store](../../lld/17-validation-signal-store.md) → feedback-store TTL/retention shape); **NEW server-side-semantic-redaction LLD** (+ counsel on BAA); **LLD 19** (ML retrain data source).
- **Code touch-points**: [guard.py:325](../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L325) / [:373-389](../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L373) (`_build_request` payload), [:391](../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L391) (`_send`), [:416](../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L416) (unknown→DENY); [config.py:167](../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/config.py#L167) (fail-secure default); [models.py:17](../../src/security-controller/app/api/models.py#L17) (`ValidationRequest`, add `phase`); [validation_service.py:239](../../src/security-controller/app/services/validation_service.py#L239) (`_capture`); [deny_overrides.py](../../src/security-controller/app/combiners/deny_overrides.py) (`winning_source`); [signal_store_table_construct.py:80-81](../../cdk/cdk_constructs/signal_store_table_construct.py#L80) (feedback-store CDK basis).
