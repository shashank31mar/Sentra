# ws-e2-server-redaction — server-side redaction (controller, hermetic)

**Scope of**: [../ws-e-redaction.md](../ws-e-redaction.md) E3 + E4 + E5 + E6.2/E6.3 + E7.1 + tests E8.3/E8.4/E8.7 · **LLD**: [../../../lld/29-redaction.md](../../../lld/29-redaction.md) §4/§5/§6 (Tier-2 NER barrier is on the **PHI content-field path only** — §4.1/§5.3/F1)
**Domain**: backend (Python, FastAPI controller) · **Package**: `src/security-controller/`
**Prereq (BOTH landed on main — build ON them, do NOT rebuild):**
- **WS-B (LLD 30)** — `ValidationRequest.phase` + `content_text` + `KNOWN_PHASES` + `_CONTENT_FIELD` are on main ([models.py:27/35/77](../../../src/security-controller/app/api/models.py#L27)). **E1.0 is therefore VERIFY-ONLY** (do NOT re-add the phase field).
- **WS-C (LLD 31)** — the validate pipeline is now a **DAG scheduler**, NOT the old linear `_capture` sequence. `_run_validation_pipeline` ([validation_service.py:336](../../../src/security-controller/app/services/validation_service.py#L336)) calls `scheduler_pkg.build_dag(self, phase, stamp_ctx)` ([:413](../../../src/security-controller/app/services/validation_service.py#L413)) then `run_dag(...)` ([:416](../../../src/security-controller/app/services/validation_service.py#L416)). **The E3 barrier is reconciled to this DAG below — it is NOT a linear pre-step.**
- Stage 1 merged (`44947ea`) — the SDK egresses redacted structured PII (typed tokens) + `redaction_nonce` + `redacted=True` + `phase`/`content_text`.

## Purpose

Tie the redacted edge stream into the hosted PDP and enforce the invariants the server owns: run Tier-2 NER on surviving free-text PHI **behind the F1 barrier (reconciled to WS-C's DAG)**, clean the **live raw-logging bug** in `audit_logger.py`, gate every persist on a **stronger independent detector**, and stand up the **opt-in redacted feedback store** with DSAR. All hermetic (moto), no AWS deploy.

**KEY DESIGN — the barrier applies to the PHI content path ONLY (LLD 29 §4.1/§5.3, verified against the doc):**
- **Structured PII is already redacted at the edge (Tier-1).** `tool_params`/`user_input` arrive at the PDP carrying typed tokens (`⟦AEGR:…:CARD:6:4⟧`), NOT raw ([lld/29:324](../../../lld/29-redaction.md#L324)). Structure is preserved so the DAG's deep detectors **still get structural signal** ([lld/29:48](../../../lld/29-redaction.md#L48)). **Do NOT blanket-redact the whole request before the DAG — that would blind detection.** The detectors read the Tier-1 typed-token view as-is.
- **Tier-2 NER** redacts the surviving **free-text PHI in `content_text`** (content/output/memory phases only). On a PHI-bearing `content_text`, NER is a **happens-before barrier**: `NER → redacted content_text → { the phase's deep-detector DAG nodes read · audit write · feedback write }` ([lld/29:117/245/323](../../../lld/29-redaction.md#L117)). This is a **DAG entry node** (runs before the phase's other nodes), NOT a blanket middleware.

**Contracts this workstream OWNS / consumes:** the `phi_ner` client `redact_free_text(fields, *, nonce, tenant_id) -> RedactedView` (server side of §4.1) · the redaction-state guard + `RawContentBlockedFromLog` · the content-aware persist-gate (F2) · the feedback-store write contract + `DELETE /v1/feedback/subjects/{subject_locator}` · `image_mode` `{redact|evaluate|block}` resolution · redaction metrics. **Consumes** WS-B's `phase`/`content_text`/`KNOWN_PHASES`/`_CONTENT_FIELD` + WS-C's `ValidatorNode`/`build_dag`/`run_dag`. Reads `winning_source` from [deny_overrides.py](../../../src/security-controller/app/combiners/deny_overrides.py).

---

## Real touch-points (RE-VERIFIED 2026-07-02 against current main — post WS-B + WS-C)

- [models.py:27/35/77](../../../src/security-controller/app/api/models.py#L27) — `KNOWN_PHASES`, `_CONTENT_FIELD`, `ValidationRequest.phase` + `content_text` — **all present (WS-B). E1.0 = verify-only.**
- [validation_service.py:336](../../../src/security-controller/app/services/validation_service.py#L336) — `_run_validation_pipeline`; phase read at [:410-412](../../../src/security-controller/app/services/validation_service.py#L410); `build_dag` at [:413](../../../src/security-controller/app/services/validation_service.py#L413), `run_dag` at [:416](../../../src/security-controller/app/services/validation_service.py#L416); `validate_tool_call` [:198](../../../src/security-controller/app/services/validation_service.py#L198); `_handle_deny` [:479](../../../src/security-controller/app/services/validation_service.py#L479) (audit fire-and-forget [:571](../../../src/security-controller/app/services/validation_service.py#L571)); `_handle_allow` [:588](../../../src/security-controller/app/services/validation_service.py#L588) (audit [:626](../../../src/security-controller/app/services/validation_service.py#L626)); `_fire_and_forget` [:102](../../../src/security-controller/app/services/validation_service.py#L102).
- **WS-C scheduler pkg** `app/services/scheduler/` — `registry.py:58` `build_dag(service, phase, stamp_ctx) -> List[ValidatorNode]`; `node.py:31` `ValidatorNode` frozen dataclass (`source`, `cost_tier`, `run`, `depends_on`, `order_key`); `run.py:379` `run_dag(...)`. **The NER barrier node is added here (see E3).**
- [audit_logger.py:223](../../../src/security-controller/app/utils/audit_logger.py#L223) (`tool_params` full) + [:224](../../../src/security-controller/app/utils/audit_logger.py#L224) (`user_input[:200]`) in `_shared_attrs_from_request` ([:211](../../../src/security-controller/app/utils/audit_logger.py#L211)); [:308](../../../src/security-controller/app/utils/audit_logger.py#L308) + [:321](../../../src/security-controller/app/utils/audit_logger.py#L321) in `_build_log_event` ([:237](../../../src/security-controller/app/utils/audit_logger.py#L237)); `log_signals` [:115](../../../src/security-controller/app/utils/audit_logger.py#L115) receives `request.model_dump()` (a **dict**). **Anchors UNCHANGED post-drift. Still the live clause-(a) violation.**
- [deny_overrides.py](../../../src/security-controller/app/combiners/deny_overrides.py) — `metadata["winning_source"]` (feedback store reads it; redact if it quotes raw).
- [metrics_publisher.py](../../../src/security-controller/app/utils/metrics_publisher.py) — `publish_validation_metrics` (E8.7 extends, additive).
- **NEW (greenfield — confirmed no server redaction code exists):** `src/security-controller/app/redaction/phi_ner.py` — the **client** the NER barrier node calls (served container = stage 3). Behind an interface with a stub/reference NER for tests.
- Tests: `src/security-controller/tests/` (moto + async). Mirror style from `tests/test_dag_scheduler.py` (WS-C) + `tests/test_multiphase_contract.py` (WS-B). **NEW** `test_redaction_no_raw_logging.py` (E8.3), `test_feedback_store.py` (E8.4), `test_ner_barrier_node.py` (E3).

---

## Milestone E1.0 — `phase`/`content_text` contract — VERIFY-ONLY (WS-B landed it)

- **Status: DONE by WS-B** ([models.py:27/35/77](../../../src/security-controller/app/api/models.py#L27)). `KNOWN_PHASES` frozenset, `_CONTENT_FIELD` map, `ValidationRequest.phase` (Literal, unknown→422), `content_text` (≤1 MiB) all present; routing in `routes.py` (unknown→422, known-but-unbuilt→`_phase_not_implemented_deny`).
- **This stage's task:** a **verify test only** — assert `content_text` on a content/output/memory phase is what the NER node redacts, and that `phase` narrows to `KNOWN_PHASES`. **Do NOT re-add or re-decide the field** (that was the reverted divergence). Consume WS-B's names verbatim.
- **Implements:** consumes LLD 30 §2; supports E3/E4.

## Milestone E3 — the happens-before BARRIER (F1), reconciled to WS-C's DAG

> **Reconciliation (design-approved 2026-07-02):** WS-C made the pipeline a **frozen DAG** (`build_dag`→`run_dag`), so the barrier is **NOT** a linear pre-step and **NOT** a blanket pre-DAG redaction (that would blind the detectors — rejected). The barrier is a **DAG entry node on the PHI content path**: for a `content`/`output`/`memory` phase carrying `content_text`, a Tier-2 NER node runs FIRST (earliest `depends_on=()`), produces the redacted `content_text`, and every downstream consumer (the phase's deep-detector nodes + the audit write + the feedback write) reads that post-NER view. **Structured PII in `tool_params`/`user_input` is already Tier-1-redacted at the edge — the DAG's `request`-phase nodes read those typed tokens unchanged (LLD 29 §48/§324). NER touches only free-text `content_text`.**

### E3.1 — the Tier-2 NER barrier node (DAG entry node, PHI content path)
- **Files:** node registration in `app/services/scheduler/registry.py` (`build_dag`, line 58) mirroring `node.py:31` `ValidatorNode`; NEW NER client `app/redaction/phi_ner.py`; NEW source constant in `app/combiners/sources.py` + its `default_priority`.
- **Grounded mechanism (verified against run.py:424/464 + models.py):** `run_dag` passes the **same `request` object** to every node's `run(request, session)`, and nodes read `request.content_text` directly. `ValidationRequest` is a plain `BaseModel` (**NOT `frozen`** — only the DAG *graph* is frozen, node.py:8). So the barrier node **redacts `request.content_text` in place**; downstream nodes then read the redacted value, and because `_handle_deny`/`_handle_allow` pass `request.model_dump()` to `log_signals` ([validation_service.py:571/626](../../../src/security-controller/app/services/validation_service.py#L571)), the audit write **inherits the redacted `content_text` automatically** — one redaction pass gates all three consumers (detectors, audit, feedback). This is the F1 barrier realized on the DAG.
- **Change:** register a `ValidatorNode` with `cost_tier=EXPENSIVE_MODEL`, `depends_on=()` (**entry node** — the content-phase detector nodes declare `depends_on=(<ner source>,)` so they run strictly after it), whose `run(request, session)` calls `phi_ner.redact_free_text(request.content_text, nonce=request.redaction_nonce, tenant_id=session[...])`, sets `request.content_text = <redacted>`, and returns an **ALLOW/ABSTAIN** `ValidationResult` (the node's job is redaction, not a verdict — it does not DENY on PHI presence; egress-fail-closed on NER *outage* is E3/§below). **Added ONLY for content/output/memory phases with a non-None `content_text`** — the `request`-phase DAG is unchanged (no NER node), so WS-C's request-phase verdict-equivalence golden baseline is untouched.
- **Implements:** LLD §4.1, §5.3, F1. **Consumes** WS-C `ValidatorNode`/`build_dag`/`run_dag`.
- **FOOTGUN 1 (do not blind detection):** do NOT redact `tool_params`/`user_input` server-side or blanket-redact pre-DAG — they carry Tier-1 typed tokens the detectors need (LLD 29 §48/§324). NER is `content_text`-only.
- **FOOTGUN 2 (NO new `sentra`-prefixed name — LLD 31 line 185, STANDING rule):** the new source constant **MUST NOT** be `sentra.*` (WS-C froze that rule: zero new `sentra` identifiers). Use a clean non-`sentra` `Source.*` name (e.g. `Source.REDACTION_NER = "redaction.ner"`), register its `default_priority` in `sources.py` (an unregistered source → `default_priority` returns 0 → silently loses tie-breaks), and since the node returns ALLOW/ABSTAIN it never competes in the deny-combiner anyway — but the source must still be a real registered entry for the WS-D trail join.
- **FOOTGUN 3 (verdict-equivalence, LLD 31 §3):** WS-C's correctness bar is that the DAG reproduces a frozen golden baseline for the `request` phase. The NER node exists ONLY on content/output/memory phases — which today degrade to request-floor and have **no** golden baseline — so adding it does not violate the `request`-phase equivalence. Do NOT add the node to the `request`-phase DAG.
- **FOOTGUN 4 (in-place mutation hygiene, LLD 31 lines 342-347):** WS-C warns nodes sharing nested objects by reference can race. The NER node mutates a **top-level scalar** (`request.content_text`, a str) as the sole entry node before any dependent runs — no concurrent reader exists at that point (the `depends_on` edge serializes it). Do NOT mutate nested `session`/`tool_params` structures. TEST that a content-phase call's downstream nodes + audit all see the redacted `content_text` and never the raw.

### E3.2 — overlap optimization stays on the NON-PHI verdict path only
- **File:** `app/services/scheduler/run.py` (the tier-1 parallel-gather, `run.py:450-492`).
- **Change:** the NER node is `EXPENSIVE_MODEL` (tier-1) and, being a barrier, its dependents wait for it — so a PHI-bearing content call **pays NER on the critical path** (≤900 ms ML-hot budget). WS-C's existing tier-1 parallel-gather (independent nodes concurrent) is fine for non-content phases; do NOT let a `content_text`-consuming node run concurrently with the NER node (the `depends_on` edge enforces this).
- **Implements:** LLD §9.2 lever 3, §9.4.
- **FOOTGUN:** the barrier widens the raw-live window on the PHI path (§5.4) — do not code/claim it as "hidden behind the floor."

## Milestone E4 — the NO-RAW-PHI invariant (I-1), proven not asserted

### E4.1 — feed the audit/signal writer the redacted view + the redaction-state guard
- **File:** [audit_logger.py:211-235](../../../src/security-controller/app/utils/audit_logger.py#L211) (`_shared_attrs_from_request`, raw at :223/:224), [:237-335](../../../src/security-controller/app/utils/audit_logger.py#L237) (`_build_log_event`, raw at :307-308/:320-321).
- **Change:** the writer takes the **post-NER redacted fields**, never the original request. Add the cheap fail-secure first line: the writer **refuses to write any field not marked `redacted=True`** → drop that field's write + emit `RawContentBlockedFromLog`. Better a missing/partial audit row than a raw-PHI breach.
- **Implements:** LLD §5.3, E5.

### E4.2 — the content-aware persist-gate (STRONGER independent detector, NOT the flag) — F2
- **File:** the admission gate in front of the signal store AND the feedback store (`validation_service.py` persist path around the `_fire_and_forget(log_signals ...)` sites [:571/:626](../../../src/security-controller/app/services/validation_service.py#L571)).
- **Change:** the gate admitting a record to **any** persisting store runs a **content re-scan by a stronger, independent detector** — independent of / ≥ as sensitive as the Tier-2 primary — over the **whole** would-be-persisted record (`redacted_payload` + `reason` + `winning_source`/matched-rule + `detector_outcomes`). A record passes only if the re-scan finds **no residual identifier**. The cheap flag check (E4.1) runs first as short-circuit; this re-scan is the authoritative admission gate.
- **GROUNDED SUBPROCESSOR CONSTRAINT (LLD 29 §247 vs §6.3 — resolve, don't paper over):** LLD 29 §6.3 names the gate detector as "the heavy offline reclassifier OR Comprehend-Medical gate-only mode" — but §247 makes self-host the default *precisely to avoid a new subprocessor*, and Comprehend-Medical (even gate-only) **pushes raw PHI to AWS = a subprocessor**. For this **hermetic stage-2 build (no live NER, no AWS)**, the gate detector is a **`GateDetector` INTERFACE + a stub/second-independent-redactor-pass implementation** — NOT a wired Comprehend call. The interface must be independent of the Tier-2 primary (a gate that re-runs the primary is circular, F3). Comprehend-Medical-gate-only stays a **flagged, off-by-default option** deferred to the deploy stage with counsel sign-off — do NOT wire a subprocessor in stage 2.
- **Implements:** LLD §5.3.3, §6.3, F2.
- **FOOTGUN:** re-scan the whole record, not just the payload — a DENY `reason` quoting offending free-text persists a raw fragment past a payload-only guard.

### E4.3 — the log-sink inventory (config-controlled sinks) — F5
- **File:** deployment config + runbook (the sink list is LLD §5.2).
- **Change:** name + control each sink — ALB access logs (request line; Tier-1 strips query secrets), API-GW execution/access logs (data-tracing / full-body logging **disabled** in stage config), uvicorn/app request+exception logs (no-raw-body ban), X-Ray/OTel spans (no raw field in annotations/metadata), boto3/botocore (log level ≥ INFO in prod), APM frame-local capture (E4.4). Mark each **config-control** (asserted by config + runbook) vs the persist path (**test-asserted**, §15.2). This task is documentation + config wiring (no live deploy here).
- **Implements:** LLD §5.2, F5.
- **FOOTGUN:** config-control rows are deployment controls, not code the guard enforces — the honest claim is "persist path test-proven; ingress/transport config-controlled," never "every surface proven."

### E4.4 — the frame-local / APM crash-path control — F7
- **File:** the error path in `validate_tool_call` ([validation_service.py:198](../../../src/security-controller/app/services/validation_service.py#L198)) / `_handle_deny` [:479](../../../src/security-controller/app/services/validation_service.py#L479); APM config.
- **Change:** implement + assert at least one of: (1) **strip raw fields from the request object before any throwable code** (replace with redacted view / drop) so a later exception's frame has no raw; (2) an **APM/frame-local-capture assertion** in the §15.2 test; (3) name **"disable APM local-variable capture in prod"** (Sentry `include_local_variables=False` / Datadog equiv) as a config-control row. Keep the raw object's lifetime minimal — redact/zero as soon as the NER pass returns.
- **Implements:** LLD §5.4, F7.

## Milestone E5 — opt-in redacted feedback store (write path + gate + DSAR)

> The CDK table construct is **stage 3**; here the write/eval/DSAR **logic** is built + tested against a moto table using the stage-3 schema as the contract.

### E5.1 (contract) — the feedback-store schema this stage writes against
- **Schema (LLD §6.2, implemented as CDK in stage 3):** `tenant_id` (S, PK), `record_id` (S, SK `{ms}#{uuid}`), `subject_locator` (S, GSI PK), `redacted_payload` (M, redacted only), `phase` (S), `decision`/`reason`/`winning_source` (S), `detector_outcomes` (M, redacted), `ttl` (N, default 90d placeholder), `opt_in` (BOOL, default OFF), `redaction_eval_pass` (BOOL). Tests provision this via moto.

### E5.2 — the content-aware eval-gate BEFORE any write (stronger detector) — F3
- **File:** the write path into the feedback store (`validation_service.py` off-path telemetry, the `_fire_and_forget` helper at [:102](../../../src/security-controller/app/services/validation_service.py#L102), fired alongside the audit writes at [:571/:626](../../../src/security-controller/app/services/validation_service.py#L571)).
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

## Milestone E7 — URL/egress: DEPENDENCY on FR-2.9 (NOT built here)

### E7.1 — destination control depends on FR-2.9, which is UNBUILT — out of stage-2 scope
- **GROUNDED (PRD + code, 2026-07-02):** FR-2.9 (endpoint/destination-level egress policy — the OWASP allow-list + 169.254/RFC-1918 deny) is **P1 and NOT-FOUND** in the code ([prd/serverless-edition.md:129/275](../../../prd/serverless-edition.md#L129) — "no destination/egress primitive located"). LLD 29 §3.7 says redaction **reuses** FR-2.9; it does **not** own or build it. **There is nothing to reuse yet**, so E7.1 is a **documented DEPENDENCY, not a stage-2 build task.**
- **This stage's action:** none in code beyond what Tier-1 already shipped (the URL query-secret strip, stage 1). Record FR-2.9 as an **open cross-workstream dependency** for the destination allow-list; do NOT stand up a parallel URL-validation subsystem inside the redactor (LLD 29 §3.7 FOOTGUN). When FR-2.9 lands (its own P1 workstream), redaction's URL handling composes with it — no WS-E code change needed.
- **Implements:** LLD §3.7 (dependency note); FR-2.9 tracked as NOT-DONE upstream.

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

- [ ] `phase`/`content_text` contract **verified** (WS-B owns it, on main) — a test asserts `content_text` is what the NER node redacts + `phase` narrows to `KNOWN_PHASES`. NO re-add of the field.
- [ ] F1 barrier realized as a **DAG entry node** (`depends_on=()`) on the PHI content path: for content/output/memory phases with `content_text`, the NER node redacts `request.content_text` in place before the phase's detector nodes read it, and `model_dump()`→audit inherits the redacted view. NER node NOT added to the `request`-phase DAG (WS-C equivalence untouched). New source is **non-`sentra`** (LLD 31 line 185).
- [ ] `audit_logger.py` :223/:224/:307-308/:320-321 raw surface cleaned — writer takes the redacted view; a field without `redacted=True` is dropped + `RawContentBlockedFromLog`.
- [ ] The persist-gate for **any** persisting store is a stronger independent detector re-scan over the WHOLE record (payload + reason + winning_source + detector_outcomes), NOT the flag.
- [ ] Frame-local/APM crash-path control holds + is asserted (F7).
- [ ] Feedback store: redacted-only, opt-in **default OFF** (non-opted-in → no record), eval-gate stronger detector (residual → skip + `FeedbackRedactionGateFail`), `DELETE /v1/feedback/subjects/{locator}` (tenant-scoped, 403 cross-tenant), salted HMAC subject_locator (else TTL-only), tenant isolation.
- [ ] Image mode router: `evaluate` intact / `redact` routed / `block` default; `image_mode` policy field defaults `block`.
- [ ] FR-2.9 egress destination policy recorded as an **open upstream dependency** (P1, NOT-FOUND) — NOT built here; no parallel URL subsystem in the redactor.
- [ ] Persist-gate detector is a **`GateDetector` interface + independent stub** (NOT a wired Comprehend/subprocessor call) — Comprehend-gate-only deferred to deploy stage w/ counsel sign-off.
- [ ] Metrics published off the response path.
- [ ] **E8.3** NO-RAW negative-control test passes; the "skip-store but forward raw" + "logs raw body" variants make it FAIL (non-vacuous).
- [ ] **E8.4** feedback-store tests pass (moto).

## OUT of this stage
Stage 3 (Dockerfile.phi-ner, CDK constructs, served phi-ner endpoint, F4 in-container isolation) · E8.5 fuzzy recall harness (WS-0-gated) · E8.6 LIVE e2e (needs prod infra) · any deploy · release-gate items. See [00-index.md](00-index.md).