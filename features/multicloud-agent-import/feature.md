# Feature — Multi-Cloud Agent Import (Discover & Onboard Agents from AWS / Azure / GCP)

**Status:** DRAFT v2.3 — three review passes (Kiro) incorporated; **multi-tenancy is P0, verified identity (asymmetric JWT) is P1**. v2.3 adds the **detected-agents union + `NotImported/Imported/Managed` lifecycle** (§8.1), and locks **per-source `native_resource_id`** as the dedupe key.
**Owner:** Security Controller (src/security-controller) + Console (web/console) + CDK (cloud connectors)
**Last updated:** 2026-06-10
**Related LLDs:** LLD 21 (API inventory — Discovery §), LLD 11 (Policy CRUD), LLD 15 (cross-cloud demo), the multi-cloud connector vision in `Kuberneters-Control-Plane-For-AI-Agents.md`

---

## 1. Summary

Let a customer **connect their cloud accounts (AWS / Azure / GCP), discover the AI agents running there, and bring selected agents under AegionAI governance** — populating identity, tools, and a starter policy so the agent is actually governed (not just inventoried).

> **The one-line trap this doc exists to avoid:** "import an agent" is usually imagined as *list agents from the cloud and store metadata*. On **our** platform that produces either a **bricked agent** (no active policy ⇒ the controller denies every call, fail-secure) or a **ghost** (a record exists but the agent's calls never route through us). A useful import must deliver three things — a **canonical `agent_id` the runtime agrees with**, **discovered tools → an auto-seeded active policy**, and a concrete **interception path**.

---

## 2. The mental model — import is three layers, not one

| Layer | Means | Needs | Difficulty |
|---|---|---|---|
| **1. Inventory** | "this agent exists; here's its metadata" | read-only cloud access | easy |
| **2. Governance** | "here's the active policy that governs it" | tools + a policy keyed to the **right `agent_id`** | medium |
| **3. Interception** | "its tool calls route through `POST /v1/validate`" | SDK / connector / proxy in the agent's tool path | **hard — make-or-break** |

A successful "import" must advance an agent through all three (or at least 1→2, with 3 explicitly tracked). Most of this doc's requirements come from layers 2 and 3, which generic discovery thinking ignores.

---

## 3. Three enforcement truths that drive every requirement (verified against code)

1. **No active policy ⇒ DENY everything.** `PolicyEngine.validate` fails secure: if `get_agent_policy(agent_id)` raises `PolicyNotFoundError`, it returns `DENY` (`POLICY_NOT_FOUND`). `get_agent_policy` only loads policies with `status='active'` (FilterExpression in `policy_engine.get_agent_policy`). → **Importing without seeding an active policy bricks the agent.**
2. **Governance binds by the policy's `agent_id` + `active`, NOT by an "attached" relationship.** Enforcement loads the policy via the metadata GSI on `agent_id`; `attached_policy_ids` on the agent record is **never read by validation** (only by `agent_service.attach/detach_policy`). → **The imported record's `agent_id` must exactly match what the agent's runtime sends in `ValidationRequest.agent_id`, or nothing governs it.**
3. **Caller identity is self-asserted and unverified today.** `ValidationRequest.agent_id` is a plain required string (`api/models.py:ValidationRequest`); the validate route reads it straight from the body and loads the policy by it (`routes.validate_tool_call` → `policy_engine.get_agent_policy(request.agent_id)`). The only auth on the endpoint is the **shared** API-Gateway key — it proves "a legitimate caller," not "*which* agent." → **Any caller holding the key can claim any `agent_id` and inherit that agent's policy.** Acceptable for the seeded-by-us demo; **not** acceptable once we tell a customer "this policy governs your agent."

**Corollary — identity is the highest-risk surface, in three linked ways.** Import must (a) mint a stable `agent_id` and guarantee the runtime emits the same one (**canonicalization**), (b) **verify** the caller actually is that agent (**anti-spoofing** — §14), and (c) scope every record and lookup to the owning customer (**multi-tenancy** — §14). These collapse into **one mechanism**: a per-agent credential, issued at import, that the runtime presents on every validate call. The controller resolves the authoritative `(tenant_id, agent_id)` *from the verified credential*, not from the request body — so the same artifact fixes spoofing and carries the tenant.

---

## 4. Current-state analysis (verified against code)

### 4.1 What "discovery/import" does **today**
| Component | State |
|---|---|
| `services/discovery_service.py` | **STATIC, policy-derived** (docstring line 2). "Discovered agents" are derived from existing **policy artifacts + `sentra-agent-registry`** — *not* a cloud scan. `cloud_provider`/`framework` come from the registry if managed, else defaulted; `risk` is a provisional heuristic from the policy's severity breakdown. |
| `GET /v1/discovery/{agents,summary,platforms}` | Read models over those static artifacts. |
| `POST /v1/discovery/import` | Body `{agent_ids[], enforcement_mode="monitor"}`. For each id: `failed` if no governing policy, `skipped` if already in registry, else **writes a registry row** (`status:active`, `enforcement_mode`). Returns `{imported, agents:[{discovery_id, agent_id, status:managed|skipped|failed, reason}]}`. **It is a registry write, not a cloud onboarding.** |
| `sentra-agent-registry` (DDB) | Keyed by `agent_id`. `policy_validator._agent_exists` requires an agent to be here before a policy can be created. |
| Console `features/import/ImportAgentsPage.tsx` + `lib/api/discovery.ts` | Lists unmanaged (policy-derived) agents, RiskBadge/CloudBadge, `useImportAgents`. No cloud-account connection, no credential capture, no per-cloud scan. |

### 4.2 The chicken-and-egg that already exists
- **Policy create requires the agent to be in the registry** (`policy_validator._agent_exists`).
- **Import requires a governing policy** (`import_agents`: "no governing policy" → failed).
- So today an agent must be *seeded into the registry and given a policy out-of-band* before discovery/import shows it. Real multi-cloud import must **break this loop**: discovery (from the cloud) creates the registry candidate; import seeds the policy.

### 4.3 What does **not** exist today (the actual gap)
- No **cloud-account connection** (no stored IAM role / service principal / service account, no credential vault reference).
- No **active scanner** against AWS Bedrock / Azure / GCP Vertex APIs.
- No **tool introspection** (action-group OpenAPI / function routes / Vertex tool defs → tool list).
- No **canonical-id mapping** (native ARN/resource-id ⇄ our `agent_id`).
- No **interception model** (the imported agent doesn't call `/v1/validate` unless its code/runtime is changed).
- No **policy auto-seed** on import.

---

## 5. Goals & Non-Goals

### Goals
- A customer can **connect** an AWS account / Azure subscription / GCP project (read-only) and **scan** it for AI agents.
- Discovery surfaces real agents with **native id, cloud, platform, region, model, framework, and tools**.
- Operator selects agents to **import**, which **(a)** mints a canonical `agent_id`, **(b)** auto-seeds an **active** starter policy from discovered tools, **(c)** records the **interception plan/status**, and **(d)** registers the agent.
- Imported agents show **honest governance state**: `discovered → policy-seeded → intercepting (governed)`.
- Works incrementally per cloud (ship AWS first), and degrades cleanly (inventory-only if interception isn't wired yet).
- **Verified agent identity:** the runtime proves it is the imported agent (per-agent credential issued at import); the controller never trusts a self-asserted `agent_id` for a managed agent.
- **Per-tenant isolation from day one:** every connection, discovered agent, policy, credential, and signal is scoped to the owning customer (`tenant_id` in the key), so onboarding a second customer is a data operation, not a re-architecture.

### Non-Goals
- **Auto-instrumenting the customer's agent code.** We can detect, seed policy, and *guide/scaffold* interception; we do not silently modify their runtime. (A managed sidecar/proxy is a later phase.)
- Real-time streaming discovery. Scans are on-connect + scheduled/refresh.
- GCP and Azure parity in v1 — phase per cloud.
- Cross-cloud topology auto-inference (which agent calls which) — operator-declared in v1 (feeds `cross_cloud_dependencies`).
- Replacing the SDK as the recommended interception path.

---

## 6. The information we need — the Import Record

Each field is tied to the platform consumer that needs it (so we don't collect noise).

| Group | Fields | Consumed by |
|---|---|---|
| **A. Identity & canonicalization** | `tenant_id` (owning customer — part of **every** store key), `agent_id` (canonical, tenant-scoped), `native_resource_id` (ARN / Azure resource id / Vertex resource name), `display_name`, `owner/team`, `environment` | every endpoint; controller resolves `(tenant_id, agent_id)` from the **verified credential**, then cross-checks the body (§3, §14) |
| **B. Cloud placement** | `cloud_provider` (aws/azure/gcp), `platform` (bedrock/azure_foundry/vertex_ai), `account`/`subscription`/`project`, `region` | `platform`/`cloud_region` resolution, CloudBadge, cross-cloud latency budget |
| **C. Capability surface (tools)** | `tools[]` = `{name, operation_type READ|WRITE, params_schema, backend_ref}` | `allowed_tools` seed; READ/WRITE → rollback eligibility; `/v1/agents/{id}/tools` |
| **D. Model & framework** | `foundation_model(s)`, `framework` (Bedrock Agents / LangChain / Semantic Kernel / Vertex Reasoning Engine / custom) | risk scoring, ML-classifier context, **which interception adapter** |
| **E. Interception & identity** | `method` (sdk \| connector \| proxy \| none), `endpoint?` (e.g. the tool Lambda/Function URL), `propagation` (session/request-id mechanism), `status` (planned/live), **`credential_key_id`** (id of the agent's registered **public** key; agent holds the private key) | actual governance + **verified** identity; the connector/traffic path (cf. `IDENTITY_FUNC_URL`/`PAYMENTS_LAMBDA_NAME`) |
| **F. Discovery credentials** | `connection_id` → `{cloud, role_arn \| service_principal \| service_account, external_id, scopes}` (secret stored in a vault; reference only) | the scan itself |
| **G. Governance seed** | `allowed_tools` (from C), `max_calls_per_minute`, trust thresholds, data-classification, compliance profile | the auto-seeded **active** policy (§3) |
| **H. Cross-cloud relations** | `cross_cloud_dependencies[] = {target_agent, target_tool, required_before[], max_age_seconds}` | cross-cloud preconditions (operator-declared v1) |

**Minimum-viable record (to actually govern):**
```jsonc
{
  "tenant_id": "...", "agent_id": "<canonical>", "native_resource_id": "arn:aws:bedrock:...",
  "cloud_provider": "aws", "platform": "bedrock", "account": "5311...", "region": "us-east-1",
  "display_name": "Acme Payments Agent", "owner": "payments-team",
  "framework": "bedrock_agents", "foundation_model": "amazon.nova-lite-v1",
  "tools": [{ "name": "process_refund", "operation_type": "WRITE", "params_schema": { } }],
  "interception": { "method": "sdk", "endpoint": "...", "propagation": "bedrock_session_attributes", "status": "planned", "credential_key_id": "agk_..." },
  "policy_seed": { "allowed_tools": ["process_refund"], "max_calls_per_minute": 30, "cross_cloud_dependencies": [] },
  "connection_id": "conn-aws-acme"
}
```

---

## 7. Per-cloud discovery — what each cloud gives us + access required

| Cloud | Discovery API | Yields | Tool introspection | Access (read-only) |
|---|---|---|---|---|
| **AWS Bedrock Agents** | `bedrock-agent:ListAgents`/`GetAgent`/`ListAgentActionGroups` | agent id, ARN, alias, foundation model, IAM role, region, account | **action groups → tools** via their OpenAPI/function schemas; backing Lambda(s) | cross-account **IAM role** (`bedrock-agent:List/Get*`, `lambda:GetFunction`) + `external_id` |
| **Azure (AI Foundry / Functions)** | Azure Resource Graph / ARM; AI Foundry project API | subscription, RG, Function App / AI project, model deployment, managed identity, region | function **routes** / tool manifest | **service principal** with Reader on subscription/RG |
| **GCP Vertex AI (Agent Builder / Reasoning Engine)** | `aiplatform` ListReasoningEngines / agents | project, location, reasoning-engine/agent resource name, model, service account | Vertex **tool definitions** | **service account** with `aiplatform.*.get/list` |

Tool introspection is **per-cloud work** (three implementations), not one adapter. Where a cloud doesn't expose tool schemas, fall back to operator-supplied tool lists.

---

## 8. Interception — the make-or-break (Layer 3)

Discovery (read creds) gives inventory. To **govern**, the agent's tool calls must reach `/v1/validate`. Options, by how invasive:

1. **SDK in the agent code (recommended).** `aegion-guard` + `@guard.tool`, with `agent_id` set to the canonical id. We *scaffold* this (generate the snippet/PR), but the customer deploys it. Cleanest, lowest latency, what the demo uses.
2. **Connector / sidecar.** A thin interceptor at the tool boundary (e.g. an action-group Lambda wrapper / Function middleware) that calls validate. We can ship this as a deployable artifact per platform.
3. **Proxy in front of the model/tool layer.** Most general, highest effort/latency; for runtimes we can't modify.
4. **None (inventory-only).** Imported for visibility; **explicitly not governed** — UI must say so (otherwise it looks protected but isn't).

**Decision the doc forces:** "managed" must mean **interception is live (validate calls observed)**, not merely "a record exists." Track `interception.status: planned | live` and surface it; show governed only when we've **seen a validate call** from that `agent_id`.

### 8.1 Detected-agents inventory — union, dedupe, and the lifecycle status (decided)

The **Detected Agents** list is the **union of two sources**, deduplicated:

1. **Imported (our side)** — agents that already have a registry row (managed by Sentra), across **all** clouds.
2. **Visible-but-not-imported** — agents the live scan sees in a connected cloud account (`bedrock:ListAgents` today; Azure/GCP later) that have **no** registry row yet.

This replaces the prior policy-derived-only read-model: the list now reflects **what is actually in the customer's account** plus **what we already govern**, not just what has a Sentra policy artifact.

**Dedupe key — the source's native unique id (decided).** Every agent record (imported **and** scanned) stores a **`native_resource_id`** — the unique id from its source of truth: AWS Bedrock `agentId` (or ARN), Azure resource id, GCP Vertex resource name. The union dedupes on `native_resource_id`. Existing registry rows that predate this field fall back to a **normalized-name** match until backfilled. → **Storing the native id per source is the prerequisite for a correct, duplicate-free union.**

**Lifecycle status — `NotImported → Imported → Managed` (decided).** A single status per agent, derived (never hand-set):

| Status | Means | Derived from |
|---|---|---|
| **NotImported** | visible in the cloud account; no registry row on our side | scan ∧ ¬registry |
| **Imported** | registry row + policy exist, but no validate traffic yet | registry ∧ no recent validate signals |
| **Managed** | **data is flowing** — the agent's calls reach `/v1/validate` | registry ∧ validate signals observed |

- **`Imported → Managed` is automatic and evidence-based (decided):** it flips **only** when we receive `/v1/validate` data for that agent (i.e. after the customer wires the SDK — §8 interception). It is **never** a manual toggle. Source of truth = the validation-signal store (per-agent index, LLD 17). This makes "Managed" un-fakeable: it literally means "we've seen this agent's traffic."
- **Managed is sticky + last-active (decided):** once data is seen the agent stays `Managed`; we surface a **`last_active`** timestamp so a silent agent is visible (an idle Managed agent does not flicker back to Imported).
- **Three distinct axes — do not conflate (clarifies a real UX trap):** (a) **cloud-account connection** (`AssumeRole` works → we can *list* the account) is a *connection* property, not an agent property; (b) **Imported** = registry row exists; (c) **Managed** = validate data flowing (SDK wired). An agent can be `Managed` (traffic flowing) while its account has no discovery connection, and vice-versa. The console must label the account-connection state separately from the per-agent lifecycle status.

**Scope of the list (decided):** union of *all* imported agents (every cloud) + *all* agents visible via connected accounts, deduped, with the existing cloud/connection/status filters. Not scoped to a single connection.

**Two views, two audiences (decided):**
- **Detected Agents (Import tab)** = the **full union** with all three statuses (`NotImported/Imported/Managed`) — this is the onboarding/triage view.
- **Agent Inventory** = **only `Managed`** agents (data actually flowing). An imported-but-silent agent (`Imported`) is still *onboarding* and belongs in the Import tab, not the operational Inventory. Inventory uses the **same signal-derived status** — it shows an agent the moment its `/v1/validate` traffic is observed, and (sticky) keeps it with a `last_active` if it goes quiet. So Inventory answers "what are we actually governing right now," not "what records exist."

---

## 9. Proposed architecture & flow

```
Connect cloud account ──▶ Scan (per-cloud adapter) ──▶ Discovered inventory (cache)
        │                         │                              │
   creds in vault          tool introspection            review & select
        │                         │                              │
        └─────────────────────────┴───────────────▶ Import ──▶ { canonical agent_id,
                                                                 auto-seed ACTIVE policy,
                                                                 register agent,
                                                                 interception plan + scaffold }
                                                          │
                                                          ▼
                                          Governed once a validate call is observed
```

New backend pieces: **CloudConnection** store (creds ref), **per-cloud Scanner adapters**, **DiscoveryCache** table, **Canonicalizer** (native id ⇄ agent_id), **PolicySeeder** (tools → active policy), **InterceptionTracker** (planned→live).

---

## 10. Decisions & open questions (proposed defaults)

1. **Canonical `agent_id` scheme.** **(decided)** `agent_id = "{tenant_id}-{cloud}-{slug(native_resource_id)}"` — slug off the **stable** native resource id (ARN / resource name), **not** the mutable display name, so a rename in the cloud doesn't change our id and the "idempotent by `native_resource_id`" guarantee (§15) holds. `native_resource_id` stored verbatim; explicit operator override allowed. The runtime no longer has to *emit* this value correctly by hand — the canonical `agent_id` is baked into the **SDK scaffold generated at import**; the keypair is generated and the public key registered **at deploy time** (§14.1, two-phase), and the controller thereafter derives `agent_id` from the verified JWT.
2. **Policy auto-seed default + how `monitor` is honored.** **(decided)** seed an **active** policy with `allowed_tools` = discovered tools, conservative `max_calls_per_minute`, **enforcement_mode `monitor`** (validate runs; a DENY is shadow-logged, not blocking) until the operator promotes to `enforce`. **Mechanism:** stamp `enforcement_mode` onto the **policy metadata** at seed time. The `agent-index` GSI is `ProjectionType.ALL`, so the existing query in `policy_engine.get_agent_policy` already returns the field — **no new registry read on the hot path** (the validate path never reads the registry; it loads policy metadata + S3, in `validation_service._run_validation_pipeline`). **Plumbing note (not zero-code):** `get_agent_policy` today reads only `s3_bucket`/`s3_key` from the metadata item and returns the S3 YAML, **discarding** `enforcement_mode` — so honoring `monitor` requires threading `metadata.get('enforcement_mode')` into its return (or stamping it into the S3 policy doc and reading it there). Honor it at the **final verdict** in `validation_service` (convert `should_deny → log-only`), *after* the pipeline — not inside individual validators, or a sigma DENY would still short-circuit. Distinct from the global per-validator `ml_classifier_shadow_mode` flag (that's one validator; this is per-agent, whole-pipeline).

**`monitor` must also suppress the trust penalty, not just the block.** `_handle_deny` applies a trust-score penalty and STEP 1 `trust_checker` hard-DENYs a quarantined session *before* policy/enforcement_mode is consulted. If `monitor` only converts the final verdict to ALLOW, repeated shadow-DENYs still accrue penalties → the agent gets quarantined → it starts getting **real** DENYs at step 1, breaking the non-blocking guarantee. So `monitor` must also skip the penalty application and the DECISION metric for shadow-DENYs. **Caveat:** `monitor` only prevents bricking when canonicalization is correct — if the runtime presents no/mismatched credential there's no policy and fail-secure DENYs *before* `enforcement_mode` is consulted (§15).
3. **Credential model.** **(proposed)** AWS cross-account role + external id; Azure SP; GCP SA. Secrets in a vault (Secrets Manager / Key Vault), platform stores **reference + scopes only**. Confirm vault + least-privilege scopes per cloud.
4. **Interception in v1.** **(proposed)** SDK-scaffold (generate snippet/PR) + inventory-only fallback; sidecar/proxy is a fast-follow. Confirm we don't auto-modify customer runtimes in v1.
5. **Cross-cloud relations.** **(proposed)** operator-declared in v1 (auto-inference later). Confirm.
6. **Cloud rollout order.** **(proposed)** AWS Bedrock → Azure → GCP. Confirm.
7. **Does import honor existing static discovery?** **(proposed)** keep the static/policy-derived list as a "registered but not cloud-linked" source, and merge cloud-scanned agents into the same inventory keyed by canonical id. Confirm the merge/dedupe rule.
8. **Anti-spoofing / verified identity.** **(decided — in scope; asymmetric JWT, see §14)** agent holds a private key and registers its public key at import; signs a short-lived JWT per validate call; the controller verifies it statelessly against the cached public key and resolves `(tenant_id, agent_id)` from claims, rejecting (DENY `IDENTITY_UNVERIFIED`) a body `agent_id` that disagrees. Chosen over symmetric HMAC for standards-alignment, zero-secret-on-our-side breach posture, faster stateless verify, and a path to **federating customer-IdP tokens**. Trade-off accepted: a small **quarantine/revocation denylist** for instant containment. Open sub-decision: per-request JWT vs short-TTL bearer reused across calls.
9. **Multi-tenancy.** **(decided — P0; see §14.2)** `tenant_id` in the partition key on every store from day one, delivered via **new `*-v2` tables + a migration script + a `TENANCY_V2_ENABLED` cutover flag** (not an in-place mutation). Tenant comes from the operator's connection at inventory time and from the JWT `tid` claim at runtime — never self-asserted. Tenant *lifecycle* (signup, RBAC, billing) is a separate LLD. Existing demo agents migrate to `tenant=default`.

---

## 11. New / changed API (additions over §4.1)

```
POST   /v1/connections            { cloud, credentials_ref|inline, scopes }      -> { connection_id, status }
GET    /v1/connections                                                            -> [ { connection_id, cloud, status, last_scan } ]
POST   /v1/connections/{id}/scan                                                  -> { scan_id, discovered_count }   (async)
GET    /v1/discovery/agents        ?connection_id&cloud&status&cursor             -> paginated DiscoveredAgent (+ tools, model, native id)
POST   /v1/discovery/import        { discovered_ids[], enforcement_mode, overrides? }
                                    -> { imported, agents:[{discovery_id, agent_id, status, reason, policy_id, interception_status}] }
GET    /v1/agents/{id}/interception                                               -> { method, status, last_validate_seen }
POST   /v1/agents/{id}/credential   { public_key }                               -> { key_id }   (registers the agent's PUBLIC key; agent keeps the private key. Rotation re-registers.)
                                    Auth: operator/tenant-scoped session OR one-time enrollment token — NOT the shared agent key (§14.1).
```
**Validate auth (new):** `Authorization: Bearer <agent-JWT>` + `X-Aegion-Key-Id`. The agent signs the JWT with its private key (claims `sub`=agent_id, `tid`=tenant_id, `aud`, `exp`, `jti`, `req`=sha256(body)). The controller verifies the signature against the cached public key, resolves `(tenant_id, agent_id)` from **claims**, then loads policy. Managed agent with absent/expired/bad token → `DENY (IDENTITY_UNVERIFIED)`.

Existing `/v1/discovery/*` extended; `/v1/policies` (auto-seed) and `/v1/agents/{id}/tools` reused.

---

## 12. Backend changes (high level)

| Change | Where | Detail |
|---|---|---|
| CloudConnection store + creds-vault ref | new `services/connections_service.py`, new DDB `sentra-cloud-connections`, Secrets Manager | per-cloud role/SP/SA + scopes + external_id |
| Per-cloud Scanner adapters | new `services/scanners/{aws,azure,gcp}.py` | list agents + introspect tools + map to the Import Record |
| DiscoveryCache | new DDB `sentra-discovery-cache` | scanned inventory keyed by `(connection_id, native_resource_id)` |
| Canonicalizer | `discovery_service` | native id ⇄ canonical `agent_id`, collision/override handling |
| Tenant scoping — new tables + flag-gated migration **(P0)** | new `*-v2` DDB tables + GSIs; `scripts/migrate_tenancy.py`; `TENANCY_V2_ENABLED` flag | `tenant_id` in the partition key (registry, policy metadata + `agent-index` GSI → PK `tenant_id#agent_id`, connections, discovery cache, credentials, signals). Migration copies existing rows under `tenant=default`; flag flips read/write paths to v2; old tables `RETAIN`ed for rollback. |
| Per-agent JWT credential + verify | new `sentra-agent-credentials` DDB (public keys); verify step in `routes.validate_tool_call` | register `key_id`→`public_key`; validate verifies the agent-signed JWT against the cached public key, checks the denylist, resolves authoritative `(tenant_id, agent_id)` from **claims** **before** `get_agent_policy`. Body `agent_id` mismatch → DENY/flag. |
| PolicySeeder on import (saga, not txn) | `discovery_service.import_agents` + `policy_service.create_policy` | No atomic primitive spans 2 DDB tables + S3. **Import saga (Phase A):** write registry row → create policy (`monitor`); on failure compensate (delete prior writes). Idempotent by `(tenant_id, native_resource_id)`. **Credential registration is NOT in this saga** — the keypair doesn't exist until the customer deploys the scaffold (Phase B, §14.1). |
| enforcement_mode via policy metadata | `policy_service.create_policy` (seed) + `validation_service` (honor) | stamp `enforcement_mode` onto policy metadata at seed → returned by existing GSI query, **no hot-path registry read**. Honor at **final verdict** (`should_deny→log-only`), not per-validator. |
| Interception tracking | new field + `GET /agents/{id}/interception` | flip `planned→live` when a validate call from that `agent_id` is observed |
| IAM (CDK) | `cdk` | the controller's role needs `sts:AssumeRole` into customer roles (or per-tenant connector); document least privilege |

> CDK **does** change here (new tables, assume-role trust, vault access) — unlike the policy-management feature. Confirm with `cdk diff` at deploy.

---

## 13. Frontend (high level)

- **Connect Account wizard** (`features/connect/…`): pick cloud → guided role/SP/SA setup (copyable CFN/Bicep/TF snippet + external id) → test connection.
- **Discovery review** (extend `ImportAgentsPage`): per-connection scanned agents with cloud/model/tools/risk; multi-select; per-row "what import will do" (canonical id, seeded policy, interception status).
- **Import result** drawer: per-agent status + the **interception next step** (copy SDK snippet / download connector).
- **Agent detail**: show `interception.status` and "governed since first validate seen."
- Mock-mode parity for all of the above.

---

## 14. Security & trust boundary — the identity & tenancy spine

Discovery creds are **least-privilege, read-only**; secrets live in a vault (Secrets Manager / Key Vault / GCP SM), the platform stores **reference + scopes only**; AWS roles carry an **external-id** the controller enforces to block the confused-deputy attack.

The harder problem is **runtime** identity. Today `ValidationRequest.agent_id` is self-asserted (§3, truth 3): the validate route trusts whatever string the caller sends. For a governance product that is a hole — a low-trust agent can present a high-trust agent's `agent_id` and inherit its policy, and the audit trail misattributes actions. Import is exactly where we close it, because import is where we first control the agent's config.

### 14.1 One mechanism, two problems (anti-spoof + tenancy) — asymmetric JWT

At import we establish a **per-agent asymmetric credential** (JWT / RFC 7519):
- The agent (or our scaffold) generates a **keypair in the customer's environment**; the **private key never leaves their vault**. The agent registers only its **public key** with us (`POST /v1/agents/{id}/credential`), stored as `key_id → {tenant_id, agent_id, public_key, status}` in `sentra-agent-credentials`. → **We never hold anything that can impersonate the agent** (breach-posture win over a shared secret; lets us federate a customer IdP later).
- On each validate call the runtime presents a **per-request JWT it signs with the private key**: `sub = agent_id`, `tid = tenant_id`, `aud = sentra/validate`, `exp` (~90s), `req = sha256(body)` (binds the token to this exact request), `jti` (carried for optional server-side replay defense — see §14.3). Sent as `Authorization: Bearer <jwt>` + `X-Aegion-Key-Id`.

> **Registration auth (the linchpin).** `POST /v1/agents/{id}/credential` must be authenticated by an **operator/console session scoped to the owning tenant**, *or* a **one-time enrollment token** minted at import and bound to the canonical `agent_id` — **never the shared agent API-Gateway key**. Otherwise any key-holder could register a public key for any `agent_id` and then mint valid JWTs for it, moving the spoofing hole up one level rather than closing it.

> **Two-phase, by necessity.** The keypair is generated when the customer **deploys** the SDK scaffold — *after* the operator clicks Import. So credential registration cannot be part of the import transaction:
> - **Phase A — import (operator):** seed registry + policy (`monitor`), interception `planned`; canonical `agent_id` baked into the generated scaffold; a one-time enrollment token issued.
> - **Phase B — deploy (customer):** the agent generates its keypair, registers its public key (enrollment token / console-authed), and starts signing → interception flips to `live`.
> The import saga (§12) therefore covers **registry + policy only**; credential registration is a distinct later step.

The controller:
1. Loads the public key for `key_id` from a cache (JWKS-style) — **no per-request DDB read**.
2. Verifies signature + `exp / aud / req`. Bad / expired / absent on a managed agent → **DENY (`IDENTITY_UNVERIFIED`)**.
3. Checks a fast **quarantine/revocation denylist** so containment stays near-instant despite stateless tokens.
4. Takes `(tenant_id, agent_id)` from the **verified claims** as authoritative for policy load and audit; the body's `agent_id` is a cross-check only — a mismatch raises a `runtime_id_mismatch` flag (§15).

This single credential **both** proves the caller is the agent (anti-spoof, your point 1) **and** carries the tenant (multi-tenancy, your point 2). Chosen over symmetric HMAC for standards-alignment, zero-secret-on-our-side, stateless (faster) verify, and a path to federating customer-IdP tokens — at the cost of a denylist for revocation (§14.3).

> **Auditing a failed identity (the unverified-tenant gap).** On an `IDENTITY_UNVERIFIED` deny the claims didn't verify, so neither the claim `tid` nor the request body is trustworthy to key the signal row — yet this is the event we *most* want audited, and §14.2 makes `tenant_id` part of the signal-store PK. Resolution: key the audit row off the **registered `key_id`** if one was presented (server-side trusted — we stored its `tenant_id` at registration, independent of the bad signature); if no/unknown `key_id`, write under a reserved **`tenant=_unverified`** bucket. This keeps "every signal is tenant-scoped" true without trusting unverified claims.

```mermaid
sequenceDiagram
    participant A as Imported Agent (SDK/connector)
    participant GW as API Gateway (shared key)
    participant C as Controller /v1/validate
    participant K as public-key cache (JWKS)
    participant DL as quarantine denylist (cache)
    participant P as policy metadata GSI
    A->>GW: validate + Authorization: Bearer JWT (+ X-Aegion-Key-Id)
    GW->>C: forward (shared-key authn only)
    C->>K: public key for key_id (cached)
    K-->>C: public key
    C->>C: verify JWT sig + exp/aud/req; bad/expired → DENY IDENTITY_UNVERIFIED
    C->>DL: is (tenant_id, agent_id) quarantined/revoked?
    DL-->>C: no
    C->>C: claims authoritative; cross-check body.agent_id
    C->>P: get_agent_policy(tenant_id, agent_id from claims)
    P-->>C: active policy (+ enforcement_mode)
    C-->>A: ALLOW / DENY (governed by the right policy)
```

### 14.2 Multi-tenant data model

`tenant_id` is part of the **partition key** on every store from day one — `sentra-agent-registry`, `sentra-policies-metadata` (and the `agent-index` GSI: PK `tenant_id#agent_id`), `sentra-cloud-connections`, `sentra-discovery-cache`, `sentra-agent-credentials`, and the validation-signal store. Every read is tenant-filtered; a missing/mismatched tenant is a hard error, never a cross-tenant read. `agent_id` is unique only *within* a tenant — which is why the canonical scheme (§10.1) is tenant-prefixed.

**App-layer surface of the cutover (the GSI change ripples).** Changing the `agent-index` PK to `tenant_id#agent_id` is not just a table-definition change — **four** call sites today query that GSI by bare `agent_id` and must compute the composite key: `policy_engine.get_agent_policy`, `agent_service.get_agent_tools`, `agent_service._get_agent_tools_count`, and `policy_service.query_policies` (the `if agent_id:` branch). (`create_policy` does **not** belong here — it reaches DDB via a `get_item` by `policy_id`, the base-table PK, not the GSI.) The `*-v2`/flag approach handles storage; these four are the application-layer work the flag does **not** do for you.

**Signal-store caveat.** Tenanting the validation-signal store touches LLD 17's *locked* writer contract — the `request_id#timestamp_ms#source` SK and the writer-populated `decision_date` GSI attribute (best-practices §12). Adding `tenant_id` to those keys means updating `signal_store_writer` (and both GSIs), so it's flagged here rather than discovered mid-implementation.

**Where tenant_id comes from:** in **P0** (inventory) it is inherited from the operator's **cloud connection** (the connection is created by a known tenant), so discovered/imported rows are tenant-stamped with no runtime credential. In **P1** (governance) the runtime JWT's `tid` claim must **match** the record's tenant, or validate DENYs — closing the loop.

**Migration (P0, flag-gated).** We do **not** mutate the existing flat tables in place. We stand up **new tenant-scoped tables** (`*-v2`, `tenant_id` in the PK), run a **migration script** that copies every existing row under `tenant=default`, then flip `TENANCY_V2_ENABLED=true` so all read/write paths switch to the v2 tables atomically (from the app's view). Cutover uses a **brief write-freeze** (MVP traffic is low — simpler and safer than dual-write): freeze writes → final delta copy → flip flag → unfreeze. Old tables are kept (`RemovalPolicy.RETAIN`) for rollback until cutover is verified. Existing demo agents land in `tenant=default` and are grandfathered (runtime credential optional until rolled out).

**Scope line:** this feature delivers the tenant-scoped **data model + isolation** and tenant resolution. Tenant **lifecycle** (signup, RBAC, billing) is a separate LLD.

### 14.3 Latency

Each call carries a **per-request JWT** (signed fresh) with a `req = sha256(body)` claim that **binds the token to this exact request** — a captured token can't be replayed against a *different* call (tamper-bound), and short-TTL bearer-reuse was rejected because losing that binding defeats the point for a security product. Signature verification against a **cached public key** is µs and stays **stateless** — no per-request DDB read, faster than the HMAC-with-lookup alternative.

**Residual replay risk (named, not hand-waved):** binding stops *altered* replays but not an *identical* request replayed inside the acceptance window. We bound it with a tight `exp` (~90s) and TLS (tokens aren't observable in transit). Note the **effective window = `exp` + clock-skew leeway**, so the leeway should be the **minimum field clock-skew data supports (target ~30s, not a round 60s)** — every second of leeway widens the replay window. `ValidationRequest` already carries a unique `request_id` (+ timestamp) that `req=sha256(body)` binds to, so two *legitimately distinct* calls always differ; the residual is strictly an identical re-send. `jti` (or that `request_id`) is the dedup key for an opt-in **seen-cache** if we ever need strict once-only semantics — that trades away full statelessness, which is why it's off by default in v1.

The only near-real-time lookup is the small **quarantine/revocation denylist**: **DDB-backed** (`sentra-agent-credentials.status`) with a short-TTL in-process cache so emergency containment stays sub-budget; ElastiCache/Redis is the scale-up path, not v1. Public keys cached per `key_id`, refreshed on rotation; clock skew handled with bounded `exp/nbf` leeway (~30s — see the replay-window note above).

---

## 15. Edge cases

| Case | Handling |
|---|---|
| Native id already mapped to a canonical id | Re-scan updates in place (idempotent by `native_resource_id`); don't duplicate. |
| Two clouds, same display name | Canonical id includes cloud + tenant → no collision. |
| Tools can't be introspected (cloud doesn't expose schema) | Import with empty `allowed_tools` → policy seed in `monitor` only; prompt operator to supply tools. |
| Imported but never sends a validate call | Stays `interception: planned` → UI shows **"not yet governed"**, never "protected". |
| Policy seed fails (validation) | Per-row `failed` with the server 400 reason; registry row rolled back. |
| **Discovery** credential revoked (scan 403, cloud-scan creds) | Connection marked `error`; last good inventory retained; alert. |
| Agent presents valid credential but body `agent_id` ≠ resolved id | Authoritative id comes from the credential; the body value is ignored for policy load and a `runtime_id_mismatch` flag is surfaced on the agent. |
| Managed agent sends no / expired / bad-signature JWT | `DENY (IDENTITY_UNVERIFIED)` — for a managed agent, unverified identity is fail-secure regardless of `monitor`. Grandfathered `default`-tenant demo agents are exempt until credentials roll out. |
| Clock skew (customer cloud vs us) | `exp/nbf` validated with bounded leeway (~30s, minimal); beyond leeway → DENY, surfaced as a clock-skew warning on the agent. |
| **Agent runtime** credential revoked / quarantined (JWT signing key) | entry in the quarantine/revocation denylist → verify rejects within cache-propagation time; rotate via `POST /v1/agents/{id}/credential` (re-register public key, evict `key_id` from cache). |

---

## 16. Phased implementation

- **P0a — Tenancy migration FIRST (do ASAP, before any new feature code):** stand up the **tenant-scoped `*-v2` tables** for the existing stores (registry, policies-metadata, validation-signals), update the GSI callers to the composite key, run the **migration script** (existing rows → `tenant=default`), and flip `TENANCY_V2_ENABLED` (write-freeze cutover). **Decision (locked):** migrate first — *not* "ship inventory on flat tables, migrate later." Building inventory on the flat schema and migrating afterwards doubles the work; doing tenancy first means every new table below is **born tenant-scoped**. This is the riskiest single item, so it ships as its **own milestone with nothing else in it**.
- **P0b — AWS inventory (on the tenant foundation):** connect AWS account → scan Bedrock agents + action-group tools → discovery review (read-only). New tables (`connections`, `discovery-cache`) are created tenant-scoped from the start (no migration). `tenant_id` stamped from the connection; no runtime credential yet. *(Decoupled from P0a as a separate milestone, but built **on top of** the completed migration — never bypassing it.)*
  - **P0b.1 — Detected-agents union + lifecycle status (§8.1):** the scan **persists** what it lists into `discovery-cache` keyed by `native_resource_id`; `GET /v1/discovery/agents` returns the **union** of imported (registry) + scanned agents, deduped by native id (normalized-name fallback). Every agent carries `native_resource_id` (stored on import + scan). Status `NotImported/Imported/Managed` is **derived** — `Managed` from validate-signal activity (per-agent index, LLD 17), sticky + `last_active`; `Imported→Managed` flips only on observed traffic, never manually. Console shows the three-state badge and labels account-connection state separately from per-agent lifecycle.
- **P1 — Govern (AWS):** canonical id + policy auto-seed (`monitor`, via policy-metadata) on import; the **import saga** (registry→policy only, idempotent by native id — credential registration is Phase B, §14.1); **per-agent asymmetric-JWT identity** in the validate path (runtime `tid` claim must match the record's tenant); `enforcement_mode` honored at final verdict; interception tracking + SDK scaffold (carries the canonical `agent_id` + the enrollment flow; **the keypair is generated at deploy in the customer's environment — the scaffold never carries a key**).
- **P2 — Interception depth:** connector/sidecar artifact; "governed" gating on observed validate calls; enforce promotion UX.
- **P3 — Azure**, **P4 — GCP** (repeat the adapter + introspection per cloud).
- Cross-cloud relations (operator-declared) folded into P1.

---

## 17. Testing plan
- **Per-cloud scanner adapters** against recorded API fixtures (moto for AWS; canned ARM/Vertex responses).
- **Canonicalizer**: native id ⇄ agent_id, collisions, overrides, idempotent re-scan.
- **Import saga**: registry+policy seeded via compensating saga; assert **rollback on injected step-2/step-3 failure**; idempotent re-import by `(tenant_id, native_resource_id)`; partial-failure per-row status.
- **enforcement_mode**: `monitor` logs but allows **and suppresses the trust penalty** (repeated shadow-DENYs must NOT quarantine → no step-1 DENY); `enforce` blocks.
- **Identity (JWT)**: valid token → resolved `(tenant_id, agent_id)` authoritative; bad/expired/wrong-`aud` → `IDENTITY_UNVERIFIED`; body `agent_id` ≠ claim → flag; clock-skew at the 30s boundary; revoked/denylisted → DENY; `IDENTITY_UNVERIFIED` row keyed under `key_id`'s tenant or `_unverified`.
- **Registration auth**: `POST /credential` rejects the shared agent key; accepts only an operator/tenant-scoped session or a valid one-time enrollment token.
- **Tenant isolation**: tenant A cannot read/govern tenant B's agents/policies/signals across registry, policy GSI, and signal store.
- **Interception tracking**: `planned→live` on first observed validate.
- **Frontend** against mock router (connect wizard, review, import result).
- Gates: `tsc -b`/`npm run build` clean, controller `pytest` green, `cdk diff` reviewed.

---

## 18. Open questions for review

**Resolved in this revision** (were open, now decided):
- **Canonical id** (§10.1): tenant-prefixed, slugged off the **stable native id**, derived from the verified credential. ✅
- **`monitor` semantics** (§10.2): via **policy-metadata projection**, honored at the final verdict. ✅
- **Registry⇄policy chicken-and-egg** (§4.2): **import saga** with compensation, idempotent by `(tenant_id, native_resource_id)`. ✅
- **Anti-spoofing** (§14): **in scope** — per-agent **asymmetric JWT**; controller never trusts a self-asserted `agent_id` for a managed agent. ✅
- **Multi-tenancy** (§14.2): **P0** — `tenant_id` in every key, via **new `*-v2` tables + migration script + `TENANCY_V2_ENABLED` flag** (lifecycle/RBAC deferred to a separate LLD). ✅
- **JWT shape** (§14): **per-request JWT** with a `req = sha256(body)` claim (replay- and tamper-bound per call); short-TTL bearer-reuse rejected. ✅
- **Denylist store** (§14.3): **DDB-backed** (`sentra-agent-credentials.status`) + a short-TTL in-process cache on the hot path; ElastiCache/Redis is the scale-up path, not v1. ✅
- **Clock skew** (§15): `exp/nbf` leeway **~30s** (minimal — leeway adds to the replay window). ✅
- **Migration cutover** (§14.2): **brief write-freeze** at the `TENANCY_V2_ENABLED` flip (MVP traffic is low; simpler and safer than dual-write). ✅

**Closed in v2.1** (review pass 2): credential-registration auth (§14.1 — operator/enrollment-token, not the shared key); two-phase saga so credential isn't registered at import (§12/§14.1); `monitor` also suppresses the trust penalty (§10.2); `get_agent_policy` enforcement_mode plumbing called out (§10.2); `jti`/stateless replay contradiction resolved (§14.3); GSI-caller + signal-store cutover surface enumerated (§14.2); §17 updated. ✅

**Closed in v2.2** (review pass 3): fixed the 4th GSI caller (`policy_service.query_policies`, not `create_policy` — §14.2); §16 P1 saga corrected to registry→policy + scaffold-carries-no-key wording; removed the §18 sequencing question now locked in §16; added the **unverified-identity audit-tenant** resolution (`key_id`-tenant or `_unverified` — §14.1); tightened leeway guidance to ~30s + `request_id` dedup hook (§14.3); de-duplicated the two "credential revoked" edge rows (§15). ✅

**Still open (need product / per-cloud security input):**
1. **§8/§10.4** — Confirm v1 interception = **SDK scaffold + inventory-only fallback** (no auto-modifying customer runtimes).
2. **§10.3** — Per-cloud least-privilege scopes + vault choice per cloud.

*(P0 sequencing is **locked** in §16 — migrate first, then inventory on the tenant foundation — so it is no longer an open question.)*
