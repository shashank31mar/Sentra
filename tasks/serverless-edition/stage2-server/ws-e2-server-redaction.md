# ws-e2-server-redaction — server-side redaction (controller, hermetic)

**Scope of**: [../ws-e-redaction.md](../ws-e-redaction.md) E1.0 + E3 + E4 + E5 + E6.2/E6.3 + E7.1 + tests E8.3/E8.4/E8.7 · **LLD**: [../../../lld/29-redaction.md](../../../lld/29-redaction.md) §4/§5/§6
**Domain**: backend (Python, FastAPI controller) · **Package**: `src/security-controller/`
**Prereq**: stage 1 merged — the SDK now egresses redacted content + `redaction_nonce` + `redacted=True` + a client-side `phase`.

## Purpose

Tie the redacted edge stream into the hosted PDP and enforce the invariants the server owns: accept/validate `phase`, run Tier-2 NER on surviving free-text **behind the F1 barrier**, clean the **live raw-logging bug** in `audit_logger.py`, gate every persist on a **stronger independent detector**, and stand up the **opt-in redacted feedback store** with DSAR. All hermetic (moto), no AWS deploy.

**Contracts this workstream OWNS / consumes:** `phase` accept+validate (shared w/ WS-B) · the `phi_ner` client interface `redact_free_text(fields, *, nonce, tenant_id) -> RedactedView` (server side of §4.1) · the redaction-state guard + `RawContentBlockedFromLog` · the content-aware persist-gate (F2) · the feedback-store write contract + `DELETE /v1/feedback/subjects/{subject_locator}` · `image_mode` `{redact|evaluate|block}` resolution · redaction metrics. Reads `winning_source` from [deny_overrides.py:51](../../../src/security-controller/app/combiners/deny_overrides.py#L51).

---

## Real touch-points (verified 2026-07-01 — note the line drift vs the parent doc)

- [models.py:17](../../../src/security-controller/app/api/models.py#L17) — `ValidationRequest` (BaseModel). **No `phase` field today.**
- [validation_service.py:174](../../../src/security-controller/app/services/validation_service.py#L174) — `validate_tool_call`; [:253](../../../src/security-controller/app/services/validation_service.py#L253) `_run_validation_pipeline`; **`_capture` is a nested fn at [:272](../../../src/security-controller/app/services/validation_service.py#L272)** (parent doc said :239 — drift); audit writes fire-and-forget at [:593/:600](../../../src/security-controller/app/services/validation_service.py#L593) (deny, `_handle_deny` [:501](../../../src/security-controller/app/services/validation_service.py#L501)) and [:648/:655](../../../src/security-controller/app/services/validation_service.py#L648) (allow, `_handle_allow` [:610](../../../src/security-controller/app/services/validation_service.py#L610)); `_fire_and_forget` helper at [:78](../../../src/security-controller/app/services/validation_service.py#L78).
- [audit_logger.py:211](../../../src/security-controller/app/utils/audit_logger.py#L211) — `_shared_attrs_from_request`; **raw written at [:223](../../../src/security-controller/app/utils/audit_logger.py#L223) (`tool_params` full) + [:224](../../../src/security-controller/app/utils/audit_logger.py#L224) (`user_input[:200]`)**. [:237](../../../src/security-controller/app/utils/audit_logger.py#L237) `_build_log_event` — raw at [:307-308](../../../src/security-controller/app/utils/audit_logger.py#L307) (`user_input[:200]`) + [:320-321](../../../src/security-controller/app/utils/audit_logger.py#L320) (`tool_params` full). [:115](../../../src/security-controller/app/utils/audit_logger.py#L115) `log_signals` calls both. **Truncation-to-200 is NOT redaction — this is the live clause-(a) violation.**
- [deny_overrides.py:51](../../../src/security-controller/app/combiners/deny_overrides.py#L51) — `metadata["winning_source"]` (feedback store reads it; redact if it quotes raw).
- [metrics_publisher.py](../../../src/security-controller/app/utils/metrics_publisher.py) — `publish_validation_metrics` surface (E8.7 extends, additive).
- **NEW** `src/security-controller/app/redaction/phi_ner.py` — the **client** the controller calls (the served container endpoint is stage 3). At this stage, behind an interface with a stub/reference NER for tests.
- Tests: `src/security-controller/tests/` (moto + async; template `tests/test_tenancy_v2.py`). **NEW** `test_redaction_no_raw_logging.py` (E8.3), `test_feedback_store.py` (E8.4).

---

## Milestone E1.0 — accept + validate `phase` on the contract

- **File:** [models.py:17](../../../src/security-controller/app/api/models.py#L17) (`ValidationRequest`).
- **Change:** add an **additive, defaulted, validated** `phase` enum field — `default="request"`, values `request|content|output|memory`. An unknown/typo value → **422** (fail-secure reject, never silent accept). Coordinate with WS-B: if WS-B has landed it on `main` by build time, this is **verify-only** (do not duplicate); if not, land it here additively.
- **Implements:** LLD §1.4, E4.
- **FOOTGUN:** must be additive+defaulted — a required field re-cuts every SDK/connector. Unknown phase → 422 + not processed, never a silent accept.

## Milestone E3 — the happens-before BARRIER (F1)

### E3.1 — pin the NER barrier ahead of the three consumers
- **File:** [validation_service.py:253-449](../../../src/security-controller/app/services/validation_service.py#L253) (`_run_validation_pipeline` + the `_capture` nested fn at [:272](../../../src/security-controller/app/services/validation_service.py#L272)); the audit write sites [:593/:648](../../../src/security-controller/app/services/validation_service.py#L593).
- **Change:** for a PHI-bearing free-text field, sequence `phi_ner.redact_free_text(...) → (redacted view) → { deep detectors (ML/Cedar/Sigma) read · audit/signal write · meter/feedback write }`. Each of the three consumers reads **only** the post-NER redacted view. The request object handed to `audit_logger.log_signals` (and `_shared_attrs_from_request`/`_build_log_event`) carries the **redacted** fields, never the original.
- **Implements:** LLD §4.1, §5.3, F1.

### E3.2 — keep the overlap optimization on the NON-PHI verdict path only
- **File:** `validation_service.py` (the `_timed`/`to_thread` overlap primitive, LLD 24).
- **Change:** for a call with no free-text PHI, issue the deterministic floor and any NER pass concurrently (verdict adds `max(floor, redaction)`, not the sum). Do NOT extend this overlap to a PHI-bearing field's content — a PHI call **pays NER on the critical path** (≤900 ms ML-hot budget), NOT hidden behind the ≤500 ms floor.
- **Implements:** LLD §9.2 lever 3, §9.4.
- **FOOTGUN:** the barrier widens the raw-live window on the PHI path (§5.4) — do not code/claim it as "hidden behind the floor."

## Milestone E4 — the NO-RAW-PHI invariant (I-1), proven not asserted

### E4.1 — feed the audit/signal writer the redacted view + the redaction-state guard
- **File:** [audit_logger.py:211-235](../../../src/security-controller/app/utils/audit_logger.py#L211) (`_shared_attrs_from_request`, raw at :223/:224), [:237-335](../../../src/security-controller/app/utils/audit_logger.py#L237) (`_build_log_event`, raw at :307-308/:320-321).
- **Change:** the writer takes the **post-NER redacted fields**, never the original request. Add the cheap fail-secure first line: the writer **refuses to write any field not marked `redacted=True`** → drop that field's write + emit `RawContentBlockedFromLog`. Better a missing/partial audit row than a raw-PHI breach.
- **Implements:** LLD §5.3, E5.

### E4.2 — the content-aware persist-gate (STRONGER independent detector, NOT the flag) — F2
- **File:** the admission gate in front of the signal store AND the feedback store (`validation_service.py` persist path around the `_fire_and_forget(log_signals ...)` sites).
- **Change:** the gate admitting a record to **any** persisting store runs a **content re-scan by a stronger, independent detector** (the §6.3 heavy reclassifier / Comprehend-Medical gate-only mode — independent of / ≥ as sensitive as the Tier-2 primary), over the **whole** would-be-persisted record (`redacted_payload` + `reason` + `winning_source`/matched-rule + `detector_outcomes`). A record passes only if the re-scan finds **no residual identifier**. The cheap flag check (E4.1) runs first as short-circuit; this re-scan is the authoritative admission gate.
- **Implements:** LLD §5.3.3, §6.3, F2.
- **FOOTGUN:** re-scan the whole record, not just the payload — a DENY `reason` quoting offending free-text persists a raw fragment past a payload-only guard.

### E4.3 — the log-sink inventory (config-controlled sinks) — F5
- **File:** deployment config + runbook (the sink list is LLD §5.2).
- **Change:** name + control each sink — ALB access logs (request line; Tier-1 strips query secrets), API-GW execution/access logs (data-tracing / full-body logging **disabled** in stage config), uvicorn/app request+exception logs (no-raw-body ban), X-Ray/OTel spans (no raw field in annotations/metadata), boto3/botocore (log level ≥ INFO in prod), APM frame-local capture (E4.4). Mark each **config-control** (asserted by config + runbook) vs the persist path (**test-asserted**, §15.2). This task is documentation + config wiring (no live deploy here).
- **Implements:** LLD §5.2, F5.
- **FOOTGUN:** config-control rows are deployment controls, not code the guard enforces — the honest claim is "persist path test-proven; ingress/transport config-controlled," never "every surface proven."

### E4.4 — the frame-local / APM crash-path control — F7
- **File:** the error path around [validation_service.py:206-250](../../../src/security-controller/app/services/validation_service.py#L206) / `_handle_deny` [:501](../../../src/security-controller/app/services/validation_service.py#L501); APM config.
- **Change:** implement + assert at least one of: (1) **strip raw fields from the request object before any throwable code** (replace with redacted view / drop) so a later exception's frame has no raw; (2) an **APM/frame-local-capture assertion** in the §15.2 test; (3) name **"disable APM local-variable capture in prod"** (Sentry `include_local_variables=False` / Datadog equiv) as a config-control row. Keep the raw object's lifetime minimal — redact/zero as soon as the NER pass returns.
- **Implements:** LLD §5.4, F7.

## Milestone E5 — opt-in redacted feedback store (write path + gate + DSAR)

> The CDK table construct is **stage 3**; here the write/eval/DSAR **logic** is built + tested against a moto table using the stage-3 schema as the contract.

### E5.1 (contract) — the feedback-store schema this stage writes against
- **Schema (LLD §6.2, implemented as CDK in stage 3):** `tenant_id` (S, PK), `record_id` (S, SK `{ms}#{uuid}`), `subject_locator` (S, GSI PK), `redacted_payload` (M, redacted only), `phase` (S), `decision`/`reason`/`winning_source` (S), `detector_outcomes` (M, redacted), `ttl` (N, default 90d placeholder), `opt_in` (BOOL, default OFF), `redaction_eval_pass` (BOOL). Tests provision this via moto.

### E5.2 — the content-aware eval-gate BEFORE any write (stronger detector) — F3
- **File:** the write path into the feedback store (`validation_service.py` off-path telemetry, the `_fire_and_forget` pattern at [:78](../../../src/security-controller/app/services/validation_service.py#L78)).
- **Change:** no record is written if a residual identifier is found by an **independent, stronger detector than the Tier-2 primary** (the E4.2 re-scan). A gate that re-runs the primary redactor is circular (F3). On a residual hit → skip write + emit `FeedbackRedactionGateFail`.
- **Implements:** LLD §6.3, F3.

### E5.3 — opt-in default-OFF write path (SPLIT gate)
- **File:** the tenant registry (`sentra-tenants` row) + the write path.
- **Change:** write **only** when the tenant's `sentra-tenants` row carries the DPA-scoped opt-in flag (**default OFF**); off the response path (fire-and-forget after the verdict); redacted record only. The opt-in gate is on the **persisted store only** — transient PHI processing for redaction is **ALWAYS-ON under the BAA** (containment control, no consent gate).
- **Implements:** LLD §6.5, E8.
- **FOOTGUN:** an accidental default-ON is a clause-(b) + consent breach (mirrors LLD 27's absent-key conservative-off trap). A non-opted-in tenant produces **no** record (a test asserts it).

### E5.4 — DSAR/deletion API + salted-per-tenant subject_locator
- **File:** the operator-auth API surface (**new** `DELETE /v1/feedback/subjects/{subject_locator}`); the write path (locator derivation). Add the route to the controller AND to `api_stack.py` (per-resource gateway routing — an undefined route 403s; see the API-GW convention). *(api_stack wiring is config; the gateway resource is asserted, deployed in the combined step.)*
- **Change:** `DELETE /v1/feedback/subjects/{subject_locator}` (operator-auth, tenant-scoped) deletes every record for a subject via the `subject_locator` GSI; tenant A cannot delete tenant B's → **403**. Derive `subject_locator = HMAC(per-tenant-salt, subject_key)` at **write time before masking** where a stable subject key exists; where none exists → `subject_locator` null/absent, record is **TTL-only-deletable** (concede, do not claim subject-targeted deletability).
- **Implements:** LLD §6.4, §12.
- **FOOTGUN:** the honest GDPR claim is "deletable by expiry (TTL) + by subject where a subject key exists," never a blanket "deletable."

### E5.5 — the retrain-loop hand-off (FR-3.14) — CONTRACT only
- **Change:** guarantee the store the offline job will read is redaction-gated (redacted only §6.2 + eval-gate §6.3 + TTL/DSAR §6.4). The offline reclassify/retrain **batch job itself is FR-3.14 (P2, NOT built here)** — a named P2 gap (extends LLD 19 §4.3/§13.3 + WS-F). WS-E neither designs nor blocks on it.
- **Implements:** LLD §6.6.

## Milestone E6 (server side) — image mode router

### E6.2 — the server-side mode router `{evaluate|redact|block}`
- **File:** the controller pipeline (image-field routing, keyed off the edge tag from stage-1 E6.1) + mode resolution.
- **Change:** resolve the per-tool/per-customer mode and route: **`evaluate`** (REQUIRED — B2C-fraud beachhead) passes the image **intact, un-redacted** to the fraud/threat evaluator; **`redact`** routes to the server-side image-redact pipeline (**engine is the named LATER build** — Tesseract+Presidio); **`block`** (default, fail-secure) refuses egress / pass-through per policy.
- **Implements:** LLD §3.6, E2.

### E6.3 — wire `image_mode` into the policy model; name the two later `redact`-engine steps
- **File:** the tool registry (`image_mode` per tool) OR a Cedar attribute on the tool/resource (LLD 28).
- **Change:** the mode is a tool-registry field `image_mode {redact|evaluate|block}` (or Cedar attribute where policy-conditional); **defaults to `block`** for a tool with no explicit mode; fails toward `block` on an unresolvable mode. Name the two steps the later `redact` engine does NOT cover: (1) **faces** (Presidio image-redactor is text-only — needs Rekognition/Google DLP); (2) **DICOM metadata PHI** (a distinct metadata pass). This WS ships the **mode contract + `evaluate`/`block` routing**; the `redact`-mode engine is the named later build.
- **Implements:** LLD §3.6.
- **FOOTGUN:** default `block` (fail-secure); never default `evaluate` (would pass raw pixels for a tool that never intended it).

## Milestone E7 — URL/egress: REUSE FR-2.9

### E7.1 — destination control reuses the FR-2.9 egress policy
- **File:** the egress-destination policy (Cedar / FR-2.9 destination policy) — **NOT** a new redaction URL parser.
- **Change:** an **OWASP positive ALLOW-LIST** (validate scheme/host/port against an approved list) as the primary control, plus explicit denial of **169.254.169.254** (cloud-metadata) + RFC-1918 private ranges. (Tier-1's query-secret strip from stage 1 is the supplement.)
- **Implements:** LLD §3.7 (1), FR-2.9.
- **FOOTGUN:** do NOT stand up a parallel URL-validation subsystem — destination safety is the egress policy's job (reused).

## Milestone E8 (server subset) — tests + metrics

### E8.3 — the NO-RAW-PHI negative-control test
- **File (new):** `src/security-controller/tests/test_redaction_no_raw_logging.py`.
- **Change (LLD §15.2):** audit/signal writer + CloudWatch carry the **typed token**, raw substring absent; the redaction-state guard drops an un-flagged field + emits `RawContentBlockedFromLog`; crash-dump path (raise mid-pipeline) → no raw in the exception log; **frame-locals/APM (F7)** (raise before the NER barrier → no raw in captured frame locals / `repr(request)`); Tier-2 egress-fail-closed (E3) — held/dropped, safe fields process, not blanket-DENYed, `EgressHeldCount`/`NerUnavailableCount` emitted. **Negative controls (prove non-vacuous):** a "skip-store but forward raw" variant AND a "logs raw body" writer variant must make the test **FAIL**.
- **Implements:** LLD §15.2, E5/E6, F7.

### E8.4 — feedback-store unit tests
- **File (new):** `src/security-controller/tests/test_feedback_store.py` (moto DynamoDB).
- **Change (LLD §15.3):** redacted-only (a raw write is rejected); opt-in default OFF (non-opted-in → no record; opted-in → redacted record); eval-gate (a residual-hit record not written + `FeedbackRedactionGateFail`); TTL set; DSAR deletion (`DELETE /v1/feedback/subjects/{locator}` removes a subject; tenant A can't delete tenant B → 403); tenant isolation (A can't read B).
- **Implements:** LLD §15.3.

### E8.7 — redaction latency + failure metrics
- **File:** [metrics_publisher.py](../../../src/security-controller/app/utils/metrics_publisher.py) (server side; the SDK edge counter is stage 1).
- **Change (LLD §9.5):** publish `RedactionTier2NerLatencyMs` (p50/p99 dims), `RedactionOverlapSlackMs` (floor − NER); failure counters `RedactionFailCount`, `EgressHeldCount`, `NerUnavailableCount`; invariant metrics `RawContentBlockedFromLog` (§5.3) + `FeedbackRedactionGateFail` (§6.3). Off the response path (fire-and-forget) — a metric failure never blocks a verdict; NOT the billing ledger (WS-H).
- **Implements:** LLD §9.5.

---

## Acceptance checklist (this stage)

- [ ] `ValidationRequest.phase` accepted, defaulted `"request"`, validated (unknown → 422); verify-only if WS-B landed it.
- [ ] F1 barrier: on a PHI-bearing free-text field, NER completes before deep-detector read / audit write / feedback write (all read the post-NER redacted view); overlap confined to the non-PHI verdict path.
- [ ] `audit_logger.py` :223/:224/:307-308/:320-321 raw surface cleaned — writer takes the redacted view; a field without `redacted=True` is dropped + `RawContentBlockedFromLog`.
- [ ] The persist-gate for **any** persisting store is a stronger independent detector re-scan over the WHOLE record (payload + reason + winning_source + detector_outcomes), NOT the flag.
- [ ] Frame-local/APM crash-path control holds + is asserted (F7).
- [ ] Feedback store: redacted-only, opt-in **default OFF** (non-opted-in → no record), eval-gate stronger detector (residual → skip + `FeedbackRedactionGateFail`), `DELETE /v1/feedback/subjects/{locator}` (tenant-scoped, 403 cross-tenant), salted HMAC subject_locator (else TTL-only), tenant isolation.
- [ ] Image mode router: `evaluate` intact / `redact` routed / `block` default; `image_mode` policy field defaults `block`.
- [ ] Destination control reuses FR-2.9 (allow-list; deny metadata + private ranges) — no new URL subsystem.
- [ ] Metrics published off the response path.
- [ ] **E8.3** NO-RAW negative-control test passes; the "skip-store but forward raw" + "logs raw body" variants make it FAIL (non-vacuous).
- [ ] **E8.4** feedback-store tests pass (moto).

## OUT of this stage
Stage 3 (Dockerfile.phi-ner, CDK constructs, served phi-ner endpoint, F4 in-container isolation) · E8.5 fuzzy recall harness (WS-0-gated) · E8.6 LIVE e2e (needs prod infra) · any deploy · release-gate items. See [00-index.md](00-index.md).