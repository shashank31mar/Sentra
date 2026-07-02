# ws-e3-phi-ner-container — phi-ner container + CDK infra (synth-only)

**Scope of**: [../ws-e-redaction.md](../ws-e-redaction.md) E2.1 + E2.2 + E2.3(server side) + E2.4 + E5.1 · **LLD**: [../../../lld/29-redaction.md](../../../lld/29-redaction.md) §4 / §9.3 Option A / §9.6 / §6.2
**Domain**: backend (Docker + Python CDK) · **Package**: `docker/`, `cdk/`, `src/security-controller/app/redaction/`
**Prereq**: stage 2 merged — the `phi_ner` client contract + the feedback-store schema this infra serves/provisions.

## Purpose

Build the **infrastructure** of the two-tier redactor: the separate `phi-ner` model-serving container + its served endpoint, the Fargate CDK construct that runs it warm, its F4 in-container isolation, and the feedback-store table construct stage 2's write path targets. **Verified by `cdk synth` + construct unit assertions only — no deploy, no image push, no live AWS.**

**Contracts this workstream OWNS:** the `phi-ner` ECS service (CloudMap `phi-ner.sentra.internal`) · `docker/Dockerfile.phi-ner` · `cdk/cdk_constructs/phi_ner_service_construct.py` · `cdk/cdk_constructs/feedback_store_table_construct.py` · the served side of `redact_free_text(...)` (the client is stage 2).

---

## Real touch-points (verified 2026-07-01)

- **NEW** `docker/Dockerfile.phi-ner` — a new image (the set built by [scripts/build_and_push_images.sh](../../../scripts/build_and_push_images.sh)).
- **NEW** `src/security-controller/app/redaction/phi_ner.py` **served side** — its own FastAPI/uvicorn app (do NOT co-locate on the `security-controller` container). Stage 2 built the client that calls it.
- **NEW** `cdk/cdk_constructs/phi_ner_service_construct.py` — follows the pattern at [compute_stack.py:1651](../../../cdk/stacks/compute_stack.py#L1651) (`ecs.FargateTaskDefinition`) / [:1725](../../../cdk/stacks/compute_stack.py#L1725) (`ecs.FargateService`).
- **NEW** `cdk/cdk_constructs/feedback_store_table_construct.py` — anchors on [signal_store_table_construct.py](../../../cdk/cdk_constructs/signal_store_table_construct.py) (TTL at ~:79 `time_to_live_attribute`, PITR at ~:81 `point_in_time_recovery`); apply the TTL+PITR deltas.
- CDK unit-assertion tests: `tests/unit/` at repo root (CDK stack/construct tests) — use `aws_cdk.assertions.Template`.

---

## Milestone E2 — the phi-ner container + CDK

### E2.1 — the NER-service container image (new Dockerfile)
- **File (new):** `docker/Dockerfile.phi-ner`; served code `src/security-controller/app/redaction/phi_ner.py` (own FastAPI/uvicorn app).
- **Change:** the image bakes/pulls (a) **Presidio (MIT)** regex+NER hybrid, (b) the **distilled PHI-NER model exported to ONNX** (int8-quantized), baked in or pulled at boot from S3, (c) the **Tesseract system binary** (apt) for the future `redact`-mode image path. Model = **self-host distilled ONNX-int8 (PRIMARY)** starting pre-GA as the in-controller Presidio-spaCy hybrid (Latency Option B) → graduating to the warm ONNX microservice (Option A). Comprehend Medical is **fallback-only**.
- **Implements:** LLD §4.1, §9.3.
- **FOOTGUN (BUILD not buy — subprocessor boundary):** self-hosting adds **no new subprocessor** — raw PHI stays inside AegionAI's own controller/BAA. Every managed de-id API makes a third party OUR subprocessor and pushes raw PHI out — self-defeating for a compliance vendor. Do NOT reach for a managed API as the default.
- **FOOTGUN (cold-start off the hot path):** the model artifact is baked-in or pulled at boot, **never lazy-loaded per request**; the service is warm/always-on so a model-load cold-start is NOT on the ≤900 ms path.

### E2.2 — the CDK construct for the NER service (peer to security-controller)
- **File (new):** `cdk/cdk_constructs/phi_ner_service_construct.py` (pattern at [compute_stack.py:1651-1758](../../../cdk/stacks/compute_stack.py#L1651)); service name **`phi-ner`**, CloudMap DNS `phi-ner.sentra.internal`.
- **Change:** an `ecs.FargateTaskDefinition` (2 vCPU / 4 GB) + `ecs.FargateService` with:
  - an **internal target group** (or CloudMap-only, service-to-service) — the controller reaches it at `phi-ner.sentra.internal`, private subnets only (`PRIVATE_WITH_EGRESS`), the controller SG allowed inbound.
  - a **warm-pool min count**: `desired_count ≥ 1` + `service.auto_scale_task_count(min_capacity=N≥1)` with `scale_on_cpu_utilization`/`scale_on_metric` so scale-out is on utilization, **`min_capacity` never 0**.
  - `circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True)`, `enable_execute_command=True`, health-check `start_period` generous (model load).
- **Implements:** LLD §9.3 Option A, §10 (stateless fleet like the controller).
- **FOOTGUN:** stateless fleet — no per-tenant state between requests (F4 buffers are per-request); no sticky/session-bound routing. `min_capacity=0` is the cold-start footgun the warm pool exists to prevent.

### E2.3 (served side) — the internal API contract endpoint
- **File:** the served endpoint in `phi_ner.py` (the client is stage 2).
- **Change:** the served endpoint receives the surviving **free-text fields only** (never the whole request), returns the **redacted view** (free-text → typed tokens `<NAME>`, `<ADDRESS>`, `<CONDITION>`, …) + `redacted=True`, and **discards raw**. TLS in-VPC. Never echoes raw.
- **Implements:** LLD §4.1, §4.2, §11.

### E2.4 — the transient-processing invariant + F4 tenant isolation (in-container)
- **File:** the `phi-ner` service code; deployment config.
- **Change — the F4 isolation contract (§9.6/§8):**
  - **per-request raw-buffer lifecycle with zeroing** — each request's raw free-text held in a per-request buffer, redacted, buffer zeroed/dropped immediately after; no cross-request accumulation, no reuse across tenants.
  - **NER-framework input-logging DISABLED** — spaCy / transformers / ONNX-Runtime debug/verbose input logging OFF in prod.
  - **no shared crash dump exposes tenant raw** — body/input capture disabled; a crash must not serialize a live tenant's raw buffer.
  - **process-level isolation today + the deferred-enclave residual** — warm pool shared at process level today (per-request buffers, not a provable boundary); a provable cross-tenant boundary is the **deferred Nitro/CVM enclave (§4.5)** — a named residual, NOT claimed present.
  - **no data egress off the account (IAM)** — the service task role has **no** IAM permission to write raw anywhere and no egress to a third-party de-id API; its only write is the redacted view back to the controller.
- **Implements:** LLD §4.2(d), §9.6, §8.
- **FOOTGUN:** the transient invariant is meaningless if the framework logs the input — explicitly disable spaCy/transformers/ONNX input logging AND assert it.
- **OPEN ITEM (owner):** warm-pool sharing for BAA tenants (§9.6) — process-level shared today; a provable boundary is the deferred enclave. Carry as open.

## Milestone E5.1 — the feedback-store CDK construct

- **File (new):** `cdk/cdk_constructs/feedback_store_table_construct.py` — anchored on [signal_store_table_construct.py](../../../cdk/cdk_constructs/signal_store_table_construct.py) for shape, with the deltas.
- **Change:** table schema (LLD §6.2): `tenant_id` (S, PK), `record_id` (S, SK `{ms}#{uuid}`), `subject_locator` (S, GSI PK — DSAR), `redacted_payload` (M, redacted only), `phase` (S), `decision`/`reason`/`winning_source` (S), `detector_outcomes` (M, redacted), `ttl` (N, default 90d DPA-scoped placeholder), `opt_in` (BOOL, default OFF), `redaction_eval_pass` (BOOL). **CDK deltas:** enable TTL (`time_to_live_attribute="ttl"` — signal store uses `expires_at`); **PITR default OFF** (`point_in_time_recovery=False`); keep `RemovalPolicy.RETAIN` deliberate.
- **Implements:** LLD §6.2, §12.
- **FOOTGUN (PITR vs DSAR):** if PITR is on, a continuous backup retains a deleted subject past the DSAR deletion — default PITR OFF; do not silently inherit the signal store's setting.

---

## Acceptance checklist (this stage)

- [ ] `docker/Dockerfile.phi-ner` exists — separate from `security-controller`, bakes Presidio + distilled ONNX-int8 PHI-NER + Tesseract binary; model baked-in/pulled-at-boot (not lazy-per-request); self-host (no new subprocessor).
- [ ] `phi_ner_service_construct.py` synthesizes a `FargateTaskDefinition` (2 vCPU/4 GB) + `FargateService` named `phi-ner`, CloudMap `phi-ner.sentra.internal`, private subnets, controller SG inbound, `min_capacity ≥ 1` autoscale (never 0), circuit-breaker.
- [ ] The served endpoint takes free-text fields only, returns the redacted view + `redacted=True`, discards raw, TLS; task role has no raw-egress IAM.
- [ ] F4 in-container isolation: per-request buffer zeroing, NER-framework input-logging OFF (asserted), no crash-dump raw, process-level isolation w/ the deferred enclave named as the residual.
- [ ] `feedback_store_table_construct.py` synthesizes the §6.2 schema — TTL on (`ttl`), **PITR OFF**, `subject_locator` GSI, `RemovalPolicy.RETAIN`.
- [ ] `cd cdk && cdk synth` produces valid CloudFormation for both new constructs; construct unit assertions pass. **No deploy.**

## OUT of this stage
The combined deploy + image push + **LIVE e2e (E8.6)** — the final step for all three stages together, **needs founder authorization** (dev-stack = prod). Model selection lock / GA gate (WS-0 recall), fuzzy recall threshold (E8.5), release-gate items (counsel BAA, ADR-032). See [00-index.md](00-index.md).