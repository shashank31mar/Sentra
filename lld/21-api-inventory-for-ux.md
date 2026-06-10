# LLD 21 — API Inventory for the SOC Console UX

> **Scope:** Customer/UI-facing APIs only — the surface required to power the Aegion SOC console screens (Overview, Threats, Deployments, Agent Inventory, Agent Detail, Discovery, Import, Deploy Agent, Policies, Audit Trail).
>
> **Out of scope:** Internal service-to-service calls, agent LLM-internals (Claude/Bedrock processing), and the demo-orchestrator. The UX/UI structure itself is documented in a separate LLD — this document is **API-only**.
>
> **Related:** LLD 02 (API Gateway), LLD 03 (Security Controller), LLD 05 (Agent Management APIs), LLD 06 (Data Model), LLD 11 (Policy CRUD), LLD 17 (Validation Signal Store), LLD 08 (Auth/ALB).

---

## 1. Overview

The console talks to a single public **REST API Gateway** (`/v1/*`, `prod` stage) which proxies — via VPC Link → NLB → private ALB — to the `security-controller` FastAPI service (and the agent services).

A crucial finding drove this audit: the `security-controller` service **already implements** several endpoints the new UI needs (`/v1/metrics`, `/v1/agents`, `/v1/sessions`, `/v1/decisions`, …), but **only a subset of them is wired through API Gateway** today. So gaps fall into three tiers:

| Tier | Meaning | Effort |
|------|---------|--------|
| **A — Exposed** | Live in API Gateway + implemented in service. UI can call today. | None |
| **B — Implemented, not exposed** | Code exists in `security-controller` but no API Gateway resource/method. | Add APIGW method only |
| **C — Net-new** | No backend at all (Discovery, Deployments, Connections domains). | New service + APIGW |

---

## 2. Conventions

- **Base URL:** `https://{api-id}.execute-api.{region}.amazonaws.com/prod`
- **Versioning:** all routes under `/v1`.
- **Auth:** `X-Api-Key` header (API Gateway usage plan) + bearer (Cognito via ALB, see LLD 08). `/v1/health` is public.
- **Content type:** `application/json`.
- **Pagination:** cursor-based standard (see §11.1) — `?limit=` + opaque `?cursor=`; response returns **`next_token` only** (`null` = last page). No `has_more`, no offset/page params (DDB has no offset).
- **Timestamps:** ISO-8601 UTC (e.g. `2026-06-06T04:19:54Z`).
- **Enum vocabulary** (UI-facing):
  - `cloud_provider`: `aws | gcp | azure | unknown` — the **hosting cloud** of an agent. UI-facing dimension for distribution/discovery/deployment widgets. `unknown` is the last-resort value when the cloud can't be determined from the agent's `cloud_provider` attribute *or* derived from its `platform` (the API resolves `platform`→cloud: `bedrock/sentra→aws`, `azure_foundry→azure`, `vertex_ai→gcp`). **UI must map `unknown` to a neutral badge — never assume only aws/gcp/azure** (Kombai crash fix: enum→style lookups must be defensive).
  - `platform`: `sentra | bedrock | azure_foundry` — the **governing connector/runtime** that Sentra uses to control the agent. This is a *different axis* from `cloud_provider` (e.g. a `bedrock` agent is hosted on `aws`). Do **not** conflate the two: existing backend records carry `platform`; the cloud dimension is `cloud_provider`.
  - `decision`: `ALLOW | DENY` (UI renders Allowed / Blocked)
  - `risk`: `high | med | low`
  - `discovery_status`: `managed | unmanaged`
  - `sync_stage`: `done | pending | in_progress | initializing`
  - `policy_status`: `synced | pending | failed`
  - `agent_status` / `quarantine_status`: `active | quarantined | suspended`
- **Error envelope:**
  ```json
  { "error": "human message", "error_code": "MACHINE_CODE", "request_id": "req-..." }
  ```

---

## 3. Existing customer-facing APIs (Tier A — exposed via API Gateway)

These are defined in `cdk/stacks/api_stack.py` and implemented in `security-controller`/agent services.

| Method | Path | Purpose | Input | Output | Backing store | Consumed by screen |
|--------|------|---------|-------|--------|---------------|--------------------|
| GET | `/v1/health` | Liveness + dependency check | — | `{status, dependencies{}}` | DDB/S3/CW probes | (infra) |
| POST | `/v1/validate` | Run 5-step validation pipeline on a tool call | `request_id, session_id, agent_id, tool_name, tool_params, user_input, timestamp, operation_type` | `ALLOW`/`DENY` decision + matched rules + trust score | DDB sessions, S3 policies/sigma | (data plane; powers telemetry) |
| GET | `/v1/logs` | Query audit logs | `since, until, limit, session_id, agent_id, decision, threat_type` | `{logs[], total, next_token}` | CloudWatch Logs | Threats, Audit Trail, Live Activity |
| POST | `/v1/rollback` | Roll back a reversible action | `action_id, action_type, reason, operator_id` | `{success, ...}` | DDB/S3 | Agent Detail (remediation) |
| GET | `/v1/policies` | List policies (filters) | `agent_id, status, limit, cursor` | `{policies[], total, next_token}` | DDB + S3 | Policies, Attach Policy |
| POST | `/v1/policies` | Create policy | `PolicyCreateRequest` | `{policy_id, version, s3_key}` | DDB + S3 | Policies (Cedar Builder) |
| GET | `/v1/policies/{policy_id}` | Get one policy (+ S3 content) | path `policy_id`, `include_content` | `{policy{metadata, content}}` | DDB + S3 | Policies |
| PUT | `/v1/policies/{policy_id}` | Update policy (new S3 version) | `PolicyUpdateRequest` | `{policy_id, version}` | DDB + S3 | Policies |
| DELETE | `/v1/policies/{policy_id}` | Soft-delete policy | path `policy_id` | `{success, status:"disabled"}` | DDB + S3 | Policies |
| GET | `/v1/sigma-rules` | List Sigma rules + match counts | `status, level, limit, cursor` (see §13.2 — **not** `category/severity/enabled`) | `{rules[], total, next_token}` where each rule = `{rule_id, title, category, severity, status:"enabled"\|"disabled", match_count}` | DDB + S3 | Policies / Threats |
| PATCH | `/v1/sigma-rules/{rule_id}` | Enable/disable a rule | path `rule_id`, `{status:"enabled"\|"disabled"}` (also accepts legacy `stable\|deprecated`, §13.2) | `{success, rule_id, status:"enabled"\|"disabled"}` | DDB + S3 | Policies |
| POST | `/v1/agents/customer-query/query` | Customer-query agent (read) | `{message, session_id, context}` | `AgentResponse` | Bedrock + controller | (demo agent) |
| POST | `/v1/agents/customer-query/action` | Customer-query agent (write) | `{message, session_id, context}` | `AgentResponse` | Bedrock + controller | (demo agent) |
| POST | `/v1/agents/payment/query` | Payment agent (read) | `{message, session_id, context}` | `AgentResponse` | Bedrock + controller | (demo agent) |
| POST | `/v1/agents/payment/action` | Payment agent (write) | `{message, session_id, context}` | `AgentResponse` | Bedrock + controller | (demo agent) |

---

## 4. Implemented but NOT exposed (Tier B — add API Gateway wiring)

> **Status update (WS-21 + WS-23, verified against `cdk/stacks/api_stack.py`):** most of this tier is now **wired through API Gateway** — `/v1/metrics/*`, `/v1/agents`, `/v1/agents/{id}`, `/v1/agents/{id}/tools`, `/v1/sessions`, `/v1/sessions/{id}/decisions`, `/v1/decisions`, `/v1/logs/conversation/{id}`, `/v1/quarantine/{id}` (POST **and** DELETE), `/v1/discovery/*`, `/v1/decisions/{id}/verdict`, and `/v1/agents/{id}/policies` (attach/detach) are all exposed today. The rows below are kept for provenance; the **Exposed?** column reflects current reality.

These already exist in `src/security-controller/app/api/routes.py`.

| Method | Path | Purpose | Input | Output (key fields) | Exposed? | Powers UI |
|--------|------|---------|-------|---------------------|----------|-----------|
| GET | `/v1/metrics` | Aggregated summary metrics (legacy Logs-Insights path; superseded by `/v1/metrics/overview`) | `since, until` | `{requests, latency, sessions, threats}` | ❌ no | (legacy; not consumed) |
| GET | `/v1/agents` | List agents (`enrich=true`) | `enrich` | per-agent: `agent_id, name, platform, status, trust_score_avg, requests_total, requests_allowed, requests_denied, active_sessions, last_seen` | ✅ yes | Agent Inventory, Active Agents KPI |
| GET | `/v1/agents/{agent_id}` | Agent detail + runtime stats | path `agent_id` | full agent object | ✅ yes | Agent Detail |
| GET | `/v1/agents/{agent_id}/tools` | Allowed tools for an agent | path `agent_id` | `{tools[], total}` | ✅ yes | Agent Detail |
| GET | `/v1/sessions` | List sessions | `status, agent_id, limit` | `{sessions[], total}` | ✅ yes | Quarantined KPI, Threats |
| GET | `/v1/sessions/{session_id}/decisions` | Decisions grouped by request | path + `request_id, agent_id, limit` | `{decisions[]}` | ✅ yes | Agent Detail / drill-down |
| GET | `/v1/sessions/{session_id}/signals` | Raw signals (debug) | path + filters | `{signals[]}` | ❌ no | Advanced drill-down |
| POST | `/v1/sessions/{session_id}/signals` | External-producer signal write (Bedrock/Azure connectors, LLD 17 §8.1) | `session_id` + signal body | `{...}` (201) | ❌ no | (data plane; connector edge signals) |
| GET | `/v1/decisions` | Cross-session time-range decision scan (GSI-2) | `since, until, agent_id, decision, threat_type, session_id, limit, cursor` (see §13.4) | `{decisions[], total, next_token}` | ✅ yes | Live Activity feed, Allowed-vs-Blocked chart |
| GET | `/v1/logs/conversation/{conversation_id}` | Cross-agent conversation timeline | path | `{timeline[], statistics}` | ✅ yes | Audit Trail (trace view) |
| POST | `/v1/rollback/conversation/{conversation_id}` | Roll back all WRITEs in a conversation | `{reason, operator_id}` | `{rolled_back_count, ...}` | ❌ no | Audit/Threat remediation |
| POST | `/v1/quarantine/{session_id}` | Operator quarantine override (**idempotent** — §13.3) | `{reason, operator_id}` | `{success, previous_status, new_status, trust_score, idempotent?}` | ✅ yes | Threats / Agent Detail |
| DELETE | `/v1/quarantine/{session_id}` | Release/un-quarantine (operator override, **idempotent** — §13.3) | query `operator_id` | `{success, previous_status?, new_status:"active", trust_score?, idempotent?}` | ✅ yes | Threats / Agent Detail |

> **Action (largely done):** the rows consumed by the console are now exposed with `api_key_required=True`. Remaining unexposed rows (`/v1/metrics` legacy, `/v1/sessions/{id}/signals` GET+POST, `/v1/rollback/conversation/{id}`) are intentionally internal/superseded.

---

## 5. Gap master table (Tier C — net-new APIs needed by the UX)

Driven directly by widgets in the canvas screens that have **no** backend today.

| Screen | Widget / data need | Method | Proposed path | Backing store |
|--------|--------------------|--------|---------------|---------------|
| Dashboard | Cloud-Provider Distribution (AWS/GCP/Azure node counts) | GET | `/v1/metrics/platform-distribution` | DDB agent registry (needs `cloud_provider`) |
| Dashboard | Global Trust Score (single fleet aggregate) | GET | `/v1/metrics/overview` | CloudWatch `GetMetricData` + DDB |
| Dashboard | Allowed-vs-Blocked time buckets (24h) | GET | `/v1/metrics/decisions-timeseries` | CloudWatch `GetMetricData` |
| Dashboard | Live Deployment & Policy Sync table | GET | `/v1/deployments/sync-status` | Deployments |
| Dashboard | Force Global Sync | POST | `/v1/deployments/sync` | Deployments |
| Deployments | Fleet deployment list | GET | `/v1/deployments` | Deployments |
| Deployments | Single deployment | GET | `/v1/deployments/{id}` | Deployments |
| Deployment Log | Per-deployment event timeline | GET | `/v1/deployments/{id}/events` | DeploymentEvents |
| Deploy Agent | Deploy a managed agent to a platform | POST | `/v1/deployments` | Deployments |
| Discovery | Scan KPI cards (detected/unmanaged/new/platforms) | GET | `/v1/discovery/summary` | DiscoveredAgents |
| Discovery | Platform scan status (scanning/idle) | GET | `/v1/discovery/platforms` | DiscoveryScans |
| Discovery | Detected-agents table | GET | `/v1/discovery/agents` | DiscoveredAgents |
| Discovery | Trigger scan | POST | `/v1/discovery/scan` | DiscoveryScans |
| Discovery | Import selected (N) | POST | `/v1/discovery/import` | DiscoveredAgents → Agents |
| Import Agents | List/connect cloud providers | GET / POST | `/v1/connections` | Connections |
| Attach Policy | Attach/detach policy to an agent | POST / DELETE | `/v1/agents/{id}/policies` | DDB (agent↔policy) |

---

## 6. Net-new APIs — full REST specs

JSON shapes below are derived **directly from the canvas UI fields**.

### 6.1 Metrics

#### `GET /v1/metrics/overview`
Single call backing all dashboard KPI cards.

- **Query:** `range` = `1h | 24h | 7d | 30d` (default `24h`)
- **200:**
  ```json
  {
    "range": "24h",
    "threats_blocked": 4827,
    "threats_blocked_delta_pct": 12.0,
    "attack_categories": 9,
    "active_agents": 142,
    "clouds": 3,
    "trust_score": 87,
    "trust_status": "healthy",
    "agents_below_threshold": 3,
    "requests_total": 1200000,
    "avg_latency_ms": 12,
    "quarantined": 3,
    "false_positive_pct": 1.4
  }
  ```
- **Store (MVP):** CloudWatch `GetMetricData` for counters/latency/deny/trust + DDB agent registry for active-agent/provider counts. No rollup. See §10.6.

#### `GET /v1/metrics/platform-distribution`
- **200:**
  ```json
  {
    "total_nodes": 142,
    "providers": [
      { "cloud_provider": "aws",   "label": "AWS EC2 Clusters",   "count": 68, "pct": 48 },
      { "cloud_provider": "gcp",   "label": "GCP Core Project",   "count": 44, "pct": 31 },
      { "cloud_provider": "azure", "label": "Azure North Region", "count": 30, "pct": 21 }
    ]
  }
  ```
- **Store:** DDB agent registry grouped by `cloud_provider`. ⚠️ `cloud_provider` is **not stored today** — see §10 Data Reality Check.

#### `GET /v1/metrics/decisions-timeseries`
Backs the "Allowed vs Blocked" Chart.js area chart.

- **Query:** `range` (default `24h`), `bucket` = `1h | 1d` (default `1h`)
- **200:**
  ```json
  {
    "range": "24h",
    "bucket": "1h",
    "series": [
      { "t": "2026-06-06T00:00:00Z", "allowed": 820, "blocked": 120 },
      { "t": "2026-06-06T02:00:00Z", "allowed": 910, "blocked": 180 }
    ]
  }
  ```
- **Store (MVP):** CloudWatch `GetMetricData` (`period`=bucket size). No rollup. See §10.6.

### 6.2 Discovery

#### `GET /v1/discovery/summary`
- **200:**
  ```json
  { "detected": 148, "unmanaged": 37, "new_24h": 12, "platforms_connected": 3, "platforms_total": 3, "last_scan": "2026-06-06T04:19:12Z" }
  ```

#### `GET /v1/discovery/platforms`
- **200:**
  ```json
  {
    "providers": [
      { "cloud_provider": "aws",   "agents": 72, "status": "scanning", "last_scan": "2026-06-06T04:19:12Z" },
      { "cloud_provider": "gcp",   "agents": 51, "status": "idle",     "last_scan": "2026-06-06T03:51:00Z" },
      { "cloud_provider": "azure", "agents": 25, "status": "scanning", "last_scan": "2026-06-06T04:18:40Z" }
    ]
  }
  ```
- `status`: `scanning | idle`.

#### `GET /v1/discovery/agents`
Backs the Detected Agents table.

- **Query:** `cloud_provider, framework, risk, status` (`managed|unmanaged`), `since`, `limit` (default 50), `cursor`
- **200:**
  ```json
  {
    "total": 148,
    "agents": [
      { "id": "disc-001", "name": "payments-router-prod", "cloud_provider": "aws", "framework": "LangChain", "first_seen": "2026-06-06T02:19:00Z", "risk": "high", "status": "unmanaged" },
      { "id": "disc-004", "name": "analytics-summarizer", "cloud_provider": "aws", "framework": "LlamaIndex","first_seen": "2026-06-05T04:19:00Z", "risk": "low",  "status": "managed" }
    ],
    "next_token": null
  }
  ```

#### `POST /v1/discovery/scan`
> **Discovery source (decided):** scans are driven from **policy** — i.e. Sentra enumerates agents/tools declared in governing policy artifacts (and the connectors those policies bind to), not from raw cloud-provider API crawls. `cloud_provider` is derived from the policy/connector binding.

- **Body:** `{ "cloud_providers": ["aws","gcp","azure"] }` (omit = all)
- **202:** `{ "scan_id": "scan-9f2a", "status": "scanning", "cloud_providers": ["aws","azure"] }`

#### `POST /v1/discovery/import`
Import selected discovered agents into managed inventory.

- **Body:** `{ "agent_ids": ["disc-001","disc-002","disc-003"], "policy_template_id": "tmpl-baseline" }`
- **201:**
  ```json
  { "imported": 3, "agents": [ { "discovery_id": "disc-001", "agent_id": "agt-7781", "status": "managed" } ] }
  ```
- **Store:** moves rows `DiscoveredAgents` → `Agents`.

### 6.3 Deployments  — **P1 (not MVP)**

> **Priority:** the entire Deployments domain (list, deploy, events, sync-status, force-sync) is **P1**, scheduled after the MVP console ships. APIs are specified here for completeness but are **not** wired in the first cut.

#### `GET /v1/deployments`
- **Query:** `cloud_provider, stage, policy_status, limit, cursor`
- **200:**
  ```json
  {
    "synced": 142, "total": 145,
    "deployments": [
      { "id": "dpl-9f2a41", "agent_id": "edge-gateway-v4-prod", "agent_name": "edge-gateway-v4-prod", "cloud_provider": "aws", "region": "us-east-1", "stage": "pending", "stage_pct": 82, "policy_status": "pending", "latency_ms": 12, "updated_at": "2026-06-06T04:19:50Z" }
    ],
    "next_token": null
  }
  ```

#### `POST /v1/deployments`
Deploy a managed agent (Deploy Agent flow).

- **Body:** `{ "agent_id": "agt-7781", "cloud_provider": "aws", "region": "us-east-1", "policy_id": "pol-123" }`
- **202:** `{ "id": "dpl-aa01", "stage": "initializing", "stage_pct": 0 }`

#### `GET /v1/deployments/{id}`
- **200:** single deployment object (as in list) + `events_count`.

#### `GET /v1/deployments/{id}/events`
Backs the Deployment Log timeline.

- **200:**
  ```json
  { "deployment_id": "dpl-9f2a41", "events": [ { "ts": "2026-06-06T04:18:02Z", "stage": "in_progress", "message": "Pushing policy bundle to edge", "level": "info" } ] }
  ```

#### `GET /v1/deployments/sync-status`
Backs the dashboard "Live Deployment & Policy Sync" table + header counter.

- **200:**
  ```json
  {
    "synced": 142, "total": 145,
    "rows": [
      { "agent_id": "edge-gateway-v4-prod", "cloud_provider": "aws",   "region": "us-east-1",   "stage_pct": 82,  "stage": "pending",      "policy_status": "pending", "latency_ms": 12 },
      { "agent_id": "auth-node-stable-2",   "cloud_provider": "gcp",   "region": "us-central1", "stage_pct": 100, "stage": "done",         "policy_status": "synced",  "latency_ms": 8 },
      { "agent_id": "billing-edge-canary",  "cloud_provider": "azure", "region": "north",       "stage_pct": 14,  "stage": "initializing", "policy_status": "pending", "latency_ms": null }
    ]
  }
  ```

#### `POST /v1/deployments/sync`
"Force Global Sync" button.

- **Body:** `{ "scope": "global" }` (or `{ "agent_ids": [...] }`)
- **202:** `{ "sync_id": "sync-77", "status": "in_progress", "targets": 145 }`

### 6.4 Connections (onboarding)

#### `GET /v1/connections`
- **200:** `{ "connections": [ { "id": "conn-aws-1", "cloud_provider": "aws", "status": "connected", "account_ref": "global-prod-01", "connected_at": "..." } ] }`

#### `POST /v1/connections`
- **Body:** `{ "cloud_provider": "aws", "credentials_ref": "arn:aws:iam::...:role/AegionScan" }`
- **201:** `{ "id": "conn-aws-1", "cloud_provider": "aws", "status": "connecting" }`

### 6.5 Agent ↔ Policy attach (extends existing policy domain)

#### `POST /v1/agents/{agent_id}/policies`
- **Body:** `{ "policy_id": "pol-123" }`
- **200:** `{ "agent_id": "agt-7781", "policy_id": "pol-123", "status": "attached" }`

#### `DELETE /v1/agents/{agent_id}/policies/{policy_id}`
- **200:** `{ "agent_id": "agt-7781", "policy_id": "pol-123", "status": "detached" }`

---

## 7. Backing data-model deltas

New/extended stores implied above (cross-ref LLD 06 data model, LLD 17 signal store):

- **`MetricsRollup`** (**P1, not MVP**) — precomputed dashboard aggregates/time-buckets. **Not needed for MVP:** metrics are served directly from CloudWatch `GetMetricData` (+ DDB agent scans). Add this cache only when a hard p95 ≤100ms SLO or real concurrent-dashboard load demands it. See §10.6 for the full rationale.
- **`DiscoveredAgents`** (new) — `id, name, cloud_provider, platform, framework, first_seen, risk, status`; transitions to `Agents` on import. **Sourced from policy artifacts** (not raw cloud crawls).
- **`DiscoveryScans`** (new) — `scan_id, cloud_provider, status, started_at, finished_at`.
- **`Deployments`** (new, **P1**) — `id, agent_id, cloud_provider, region, stage, stage_pct, policy_status, latency_ms, updated_at`.
- **`DeploymentEvents`** (new, **P1**) — append-only timeline keyed by `deployment_id`.
- **`Connections`** (new) — `id, cloud_provider, status, account_ref`.
- **`Agents`** (extend, LLD 05) — add **`cloud_provider`** attribute (today only `platform` = connector exists), plus `policy_id` linkage for attach/detach.

---

## 8. Open questions / assumptions

1. ~~**Rollups vs on-the-fly**~~ — **Resolved (§10.6):** MVP serves directly from CloudWatch `GetMetricData` + DDB; `MetricsRollup` is P1. "Last sync Ns ago" UX reflects `GetMetricData` freshness (CloudWatch metric resolution ~1 min).
2. **Live Activity transport:** spec'd as polling `GET /v1/decisions`. If true streaming is required, add `GET /v1/activity/stream` (SSE) — flagged, not specified here.
3. **Tier B exposure:** confirm we expose existing `security-controller` endpoints through API Gateway as-is (recommended) vs duplicating in a new BFF.
4. **Auth scope:** per-endpoint API-key/usage-plan vs role-based (SecOps Admin) authorization for write actions (sync, quarantine, deploy, import).
5. **Discovery/Deployments ownership:** new domains — confirm they live in `security-controller` or a new service before APIGW wiring.

---

## 9. Summary

> Original plan-time tiering (kept for context). For the **authoritative current state** — including endpoints added since (un-quarantine, idempotency, sigma contract changes, the `/v1/decisions` flat-field rows) — see **§13 As-built reconciliation**.

- **15** customer-facing endpoints already **exposed** (Tier A) cover validation, logs, policies, sigma rules, agents-as-demo.
- **11** endpoints were **implemented but not exposed** (Tier B) at audit time — most are now wired through API Gateway (see §4 status update + §13.1).
- **~18** endpoints are **net-new** (Tier C) across Metrics, Discovery, Deployments, Connections, and agent↔policy attach; Metrics/Discovery/attach + verdict are now built and exposed, Deployments + Connections + `discovery/scan` remain unbuilt (P1).
- **2** endpoints added after the original inventory: `DELETE /v1/quarantine/{session_id}` (release) and `POST /v1/sessions/{session_id}/signals` (connector signal write). See §13.

---

## 10. Data Reality Check

> Verified against the live code (`storage_stack.py`, `agent_service.py`, `metrics_service.py`, `seed_agents.py`, `signal_store_table_construct.py`). This section records where the UX assumes data the backend does **not yet store**, so nobody plans against mock values.

### 10.1 `cloud_provider` is not stored today
- The only cloud-ish field in `sentra-agent-registry` is **`platform`**, and it means the **governing connector** (`sentra | bedrock | azure_foundry` per `seed_agents.py` + sample artifacts), **not** a hosting cloud.
- There is **no GCP** data anywhere in the codebase; seeded agents are 3×`sentra` + 2×`bedrock` (+ one `azure_foundry` sample artifact) = **~5 agents total**.
- `agent_service.py` actively **filters out** `platform == 'bedrock'` agents from `/v1/agents` *(current behavior; reversed by WS-21 T05/D1 — `visibility=internal` filter stays per D4)*.
- **Implication:** `cloud_provider` (AWS/GCP/Azure) must be added as a **new attribute** on `Agents`/`DiscoveredAgents` and populated (from connector/policy binding) before Platform Distribution, multi-cloud Discovery, and the Clouds KPI return anything real. Until then these widgets render placeholder data.

### 10.2 Metrics: today's path is wrong, and the data isn't fully published
Two separate problems:

**(a) The read path uses the slow CloudWatch surface.** `GET /v1/metrics` runs **CloudWatch Logs Insights** (`start_query` → poll `get_query_results`) and falls back to a hardcoded `_default_metrics()` on timeout — seconds-scale, returns defaults under load. It should instead read **CloudWatch *Metrics*** via `GetMetricData` (pre-aggregated, ~100–300ms). See §10.6.

**(b) The metrics that matter aren't being emitted.** `MetricsPublisher` (`Sentra/SecurityController` namespace) defines exactly the right metrics — `ValidationsTotal`, `ValidationLatency`, `TrustScoreAverage`, `DenyRate`, `QuarantinedSessions`, `SuspendedSessions`, dimensioned by `AgentId`/`Decision`/`ThreatType` — **but `publish_validation_metrics` and `publish_session_metrics` are never called.** `validation_service.py` instantiates the publisher but never invokes it. Only **policy-CRUD** and a few **error** metrics actually reach CloudWatch today.
  - **MVP prerequisite:** wire `publish_validation_metrics` into the validation path (one call). Until then `GetMetricData` has nothing to return for the core KPIs.

### 10.3 Example numbers are illustrative, not real
- All large figures in this doc (142 agents, 4,827 threats blocked, 148 discovered, 9 categories, etc.) are **canvas mock values**. Real scale is ~5 agents. Treat sample payloads as shape-only.

### 10.4 What *is* genuinely backed by real data
- **Agent inventory/detail KPIs** — `trust_score_avg`, `requests_total/allowed/denied`, `active_sessions`, `last_seen` are computed live in `agent_service.py` (from `session_manager` + ECS). Real for `sentra` agents.
- **Decisions feed / timeseries** — `validation-signal-store` has **GSI-2** (`decision-date-index`) for cross-session time-range scans, so `/v1/decisions` and decisions-timeseries can aggregate over real records.
- **Policies & Sigma rules** — fully backed (DDB metadata + S3 content) and already exposed.

### 10.5 Decisions taken (this round)
| Topic | Decision |
|-------|----------|
| Cloud dimension naming | Use **`cloud_provider`** for AWS/GCP/Azure; keep `platform` for the connector axis. |
| Discovery source | Driven **from policy** artifacts/connectors, not raw cloud-provider crawls. |
| Deployments domain | **P1** — specified but not in the MVP cut. |
| Metrics efficiency | **Decided** — serve **directly from CloudWatch `GetMetricData`** for MVP (no rollup). `MetricsRollup` is P1, added only on latency-SLO/concurrency pressure. See §10.6. |

### 10.6 Metrics architecture (decided)

**MVP: serve metrics directly. No rollup Lambda, no `MetricsRollup` table.**

```
controller put_metric_data ──► CloudWatch Metrics (system of record, retains rolled-up history ~15 months)
                                       │
   GET /v1/metrics/* (time-series, counts, latency, deny rate, trust)
        └─► CloudWatch GetMetricData  (pre-aggregated by `period`; ~100–300ms; handles 1h…30d natively)
   GET /v1/metrics/* (cloud_provider distribution, active agents)
        └─► DDB scan of agent registry (~handful of rows; already done in agent_service.py)
   Cold / error?  ──► degrade to the same correct source (slower), never show "—" when data exists (§10.4 rule)
```

**Why no cache for MVP:**
- `GetMetricData` already returns aggregated series and serves **all ranges** via the `period` arg — the earlier ≤24h-DDB / >24h-CloudWatch split is unnecessary; one API covers both.
- At MVP scale (~5 agents, few operators) latency/cost/throttling are non-issues.

**Sources are split** (not purely CloudWatch): counters/latency/decisions-timeseries → CloudWatch; `cloud_provider` distribution + trust + active-session counts → DDB registry/sessions. Each endpoint reads whichever owns the number.

**Prerequisites before this works (see §10.2b):**
1. Emit the core metrics — call `publish_validation_metrics` in the validation path (currently never invoked).
2. Repoint `GET /v1/metrics` from Logs Insights → `GetMetricData`.

**Add `MetricsRollup` (P1) only when one of these triggers:**

| Trigger | Why direct serving fails |
|---|---|
| Hard p95 ≤100ms SLO (LLD 17) | `GetMetricData` is ~150–300ms; DDB cache read is single-digit ms. |
| Many concurrent dashboard users | Each user×widget = a `GetMetricData` call; a 1-min Lambda collapses them into one poll. |
| CloudWatch API cost / throttling | `GetMetricData` is billed per data-point and capped (~50 TPS/account). |
| Single pre-joined payload wanted | Precompute joins CloudWatch + DDB once instead of per request. |

> When triggered, `MetricsRollup` = a small DDB table refreshed by a **1-min EventBridge→Lambda** that calls `GetMetricData` + scans the registry, writes ready-to-serve rows keyed by `range`/`bucket`. Because each run is a full recompute from the authoritative source, it is **drift-free and self-healing** (no streaming/idempotency machinery needed). Note: EventBridge scheduled rules have a **1-min minimum**; true 30s needs staggered rules or a self-re-invoking Lambda.

---

## 11. Implementation Contract (build-ready schemas)

> Makes §6 codeable. Covers **net-new** endpoints. Type tables are the source of truth for Pydantic models; JSON in §6 is illustrative only.
>
> **Build spec:** per-API logic, exact handlers/stores, API Gateway wiring, and the verified list of existing-implementation issues live in [`tasks/workstream-21-soc-console-apis.md`](../tasks/workstream-21-soc-console-apis.md).

### 11.1 Section conventions

**Type legend:** `str`, `int`, `float`, `bool`, `ts`(ISO-8601 UTC str), `enum<…>`, `T?`(nullable), `T[]`(array). "Req" = required in request.

**Authorization roles** (resolves Open-Q4). Bearer claim `role`:
- `viewer` — all `GET`s.
- `operator` — `viewer` + write actions (`scan`, `import`, `deploy`, `sync`, `quarantine`, policy attach/detach).
- `admin` — `operator` + `connections` create/delete.

Each write endpoint lists its **min role**. Insufficient role → `403 FORBIDDEN`.

**Standard error codes** (all endpoints; envelope per §2):

| HTTP | `error_code` | When |
|------|--------------|------|
| 400 | `VALIDATION_ERROR` | Bad/missing param, unpar. query, bad enum value |
| 401 | `UNAUTHENTICATED` | Missing/invalid bearer or API key |
| 403 | `FORBIDDEN` | Authenticated but role too low |
| 404 | `NOT_FOUND` | Path id does not exist |
| 409 | `CONFLICT` | State conflict (already attached, already managed, in-progress) |
| 422 | `UNPROCESSABLE` | Well-formed but semantically invalid (e.g. unknown `agent_ids`) |
| 429 | `RATE_LIMITED` | Usage-plan throttle |
| 503 | `DEPENDENCY_UNAVAILABLE` | CloudWatch/DDB/connector down (per §10.4, degrade before erroring) |

**Pagination (CANONICAL — cursor-based, applies to *every* list endpoint incl. Tier A):** standard cursor pagination (Google AIP-158 shape). DDB has no offset, so page/offset params are **not** supported.
- **Request:** `limit` (int, default per endpoint, **max 200**) + `cursor` (opaque base64 token; omit on first page).
- **Response:** `next_token` (`str?`) — **`null` ⇒ last page**. **No `has_more`** (redundant with `next_token != null`). No `next_cursor`/`cursor` in responses.
- **Round-trip:** to fetch the next page, pass the response's `next_token` value back in the `?cursor=` query param.
- **Bounded lists** (≤ a few rows: `/discovery/platforms`, `/connections`, `/metrics/*`) are **not paginated** and omit `next_token` entirely.
- **Tier A migration:** `/v1/logs`, `/v1/policies`, `/v1/sigma-rules`, `/v1/decisions` currently emit `has_more`/`next_cursor` — must be normalized to this shape (WS-21 T06) before the console ships, since these are public-facing.

**Idempotency (POST creates):** `Idempotency-Key` header (client UUID) on `scan`, `import`, `deploy`, `sync`, `connections`. Same key within 24h returns the original `2xx` (no duplicate job). Missing key on these → `400`. **Exception (P0, WS-21 F8):** P0 discovery (`scan`/`import`) is the **read-model** with no key store, so idempotency there is **best-effort** — `import` is safe by skipping already-`managed` rows; `scan` is a read. Full `Idempotency-Key` semantics apply when those domains get persistence (dynamic discovery / deploy).

**Async job pattern:** actions returning `202 {…_id, status}` are pollable via a dedicated status GET (defined below). `status` enum: `queued | in_progress | completed | failed`.

---

### 11.2 Metrics

#### `GET /v1/metrics/overview` — role `viewer`
- **Query:** `range` `enum<1h|24h|7d|30d>` default `24h`.
- **200 fields:**

| Field | Type | Notes |
|-------|------|-------|
| `range` | `enum` | echo of input |
| `threats_blocked` | `int` | `DenyRate`→count over range (CW) |
| `threats_blocked_delta_pct` | `float?` | vs previous equal window; null if no prior data |
| `attack_categories` | `int` | distinct `ThreatType` dims seen in range (CW) |
| `active_agents` | `int` | registry count, `status=active`, **all cloud providers** (D1 — no bedrock exclusion); excludes `visibility=internal` infra unless D4 says otherwise (DDB) |
| `clouds` | `int` | distinct `cloud_provider` among active agents (DDB) |
| `trust_score` | `int?` | 0–100, avg `TrustScoreAverage` (CW). **`null` when no samples in range** (empty fleet / no validations) — not `0`, which would falsely read as "fully untrusted" (Kiro review). |
| `trust_status` | `enum<healthy\|degraded\|critical\|unknown>` | `≥80 healthy`, `50–79 degraded`, `<50 critical`; **`unknown` when `trust_score` is null**. |
| `agents_below_threshold` | `int` | agents with avg trust < 70 (DDB sessions) |
| `requests_total` | `int` | `ValidationsTotal` sum (CW) |
| `avg_latency_ms` | `int` | `ValidationLatency` avg (CW) |
| `quarantined` | `int` | sessions `status=quarantined` (DDB) |
| `false_positive_pct` | `float?` | `FalsePositiveOverturns / Denials` = operator-overturned DENYs ÷ DENYs, a **confirmed-FP lower bound** (§12.3); null until verdict data exists. **P0: always null / hidden.** |

- **Errors:** 400, 401, 503.
- **Notes:** `threats_blocked_delta_pct`, `false_positive_pct` are `null` (not 0) when their inputs don't exist yet (see §10.3).

#### `GET /v1/metrics/platform-distribution` — role `viewer` (not paginated)
- **200:** `total_nodes: int`, `providers: Provider[]` where `Provider = { cloud_provider: enum, label: str, count: int, pct: int(0–100) }`. `pct` rounds to nearest int; rounding remainder added to largest bucket so sum = 100.
- **Errors:** 401, 503.

#### `GET /v1/metrics/decisions-timeseries` — role `viewer` (not paginated)
- **Query:** `range` `enum<1h|24h|7d|30d>` default `24h`; `bucket` `enum<1h|1d>` default `1h`. **Reject** `range=30d & bucket=1h` (>200 points) → `400 VALIDATION_ERROR`.
- **200:** `range`, `bucket`, `series: Point[]` where `Point = { t: ts(bucket start), allowed: int, blocked: int }`. Empty buckets returned with `0/0` (dense series).
- **Errors:** 400, 401, 503.

---

### 11.3 Discovery

#### `GET /v1/discovery/summary` — role `viewer` (not paginated)
| Field | Type | Notes |
|-------|------|-------|
| `detected` | `int` | total `DiscoveredAgents` |
| `unmanaged` | `int` | `status=unmanaged` |
| `new_24h` | `int` | `first_seen` within 24h |
| `providers_connected` | `int` | `Connections` with `status=connected` |
| `providers_total` | `int` | configured providers (const 3) |
| `last_scan` | `ts?` | most recent `DiscoveryScans.finished_at`; null if never |

#### `GET /v1/discovery/platforms` — role `viewer` (not paginated)
- **200:** `providers: ProviderScan[]`, `ProviderScan = { cloud_provider: enum, agents: int, status: enum<scanning|idle>, last_scan: ts? }`.

#### `GET /v1/discovery/agents` — role `viewer`
- **Query (all optional filters):** `cloud_provider` `enum`, `framework` `str`, `risk` `enum<high|med|low>`, `status` `enum<managed|unmanaged>`, `since` `ts`, `limit` `int` default 50, `cursor` `str`.
- **200:** `total: int`, `agents: DiscoveredAgent[]`, `next_token: str?`.

| `DiscoveredAgent` | Type | Notes |
|-------|------|-------|
| `id` | `str` | `disc-…` |
| `name` | `str` | |
| `cloud_provider` | `enum` | derived from policy/connector binding |
| `framework` | `str?` | open set (LangChain, LlamaIndex…); null if undetected |
| `first_seen` | `ts` | |
| `risk` | `enum<high\|med\|low>` | **P0: provisional heuristic** (WRITE-tool presence), not measured — UI should label as provisional until dynamic discovery (WS-21 T62) |
| `status` | `enum<managed\|unmanaged>` | |

#### `POST /v1/discovery/scan` — role `operator`, idempotent
- **Body:** `{ cloud_providers: enum[]? }` (omit/empty = all). Unknown provider → `400`.
- **202:** `{ scan_id: str, status: enum<queued|in_progress>, cloud_providers: enum[] }`.
- **409** if a scan for an overlapping provider set is already `in_progress`.

#### `GET /v1/discovery/scans/{scan_id}` — role `viewer` *(NEW — job status)*
- **200:** `{ scan_id, status: enum<queued|in_progress|completed|failed>, cloud_providers: enum[], started_at: ts, finished_at: ts?, detected_count: int, error: str? }`.
- **404** unknown `scan_id`.

#### `POST /v1/discovery/import` — role `operator`, idempotent
- **Body:** `{ agent_ids: str[] (req, 1–100), policy_template_id: str? }`. `policy_template_id` optional; when omitted the agent is imported **unmanaged-by-policy** (attach later via §11.5). Templates resolve against existing policies (`pol-…`); see Open-Q below.
- **201:** `{ imported: int, agents: ImportResult[] }`, `ImportResult = { discovery_id: str, agent_id: str?, status: enum<managed|skipped|failed>, reason: str? }`. Partial success allowed (per-row status).
- **422** if **all** `agent_ids` unknown; **409** rows where the discovered agent is already `managed` (returned as `skipped`).
- **Open-Q:** `policy_template_id` source — reuse a flagged policy as template vs a new `/v1/policy-templates` domain. Flagged, not built.

---

### 11.4 Connections (onboarding)

#### `GET /v1/connections` — role `viewer` (not paginated)
- **200:** `connections: Connection[]`, `Connection = { id: str, cloud_provider: enum, status: enum<connected|connecting|error|disconnected>, account_ref: str?, connected_at: ts?, last_error: str? }`.

#### `POST /v1/connections` — role `admin`, idempotent
- **Body:** `{ cloud_provider: enum (req), credentials_ref: str (req) }`. `credentials_ref` = ARN/secret-ref, **never raw secrets**.
- **201:** `{ id: str, cloud_provider: enum, status: "connecting" }`.
- **409** if a connection for that `cloud_provider` already exists.

---

### 11.5 Agent ↔ Policy attach

#### `POST /v1/agents/{agent_id}/policies` — role `operator`
- **Path:** `agent_id: str`. **Body:** `{ policy_id: str (req) }`.
- **200:** `{ agent_id: str, policy_id: str, status: "attached", attached_at: ts }`.
- **404** unknown `agent_id` or `policy_id`; **409** already attached.

#### `DELETE /v1/agents/{agent_id}/policies/{policy_id}` — role `operator`
- **200:** `{ agent_id, policy_id, status: "detached" }`.
- **404** if not currently attached.

---

### 11.6 Deployments — **P1** (typed for completeness, not in MVP cut)

- `GET /v1/deployments` — role `viewer`, paginated. Item: `{ id, agent_id, agent_name, cloud_provider, region, stage: enum<initializing|in_progress|pending|done>, stage_pct: int(0–100), policy_status: enum<synced|pending|failed>, latency_ms: int?, updated_at: ts }`. Top-level `synced: int, total: int, next_token: str?`.
- `POST /v1/deployments` — role `operator`, idempotent. Body `{ agent_id (req), cloud_provider (req), region (req), policy_id? }` → **202** `{ id, stage: "initializing", stage_pct: 0 }`.
- `GET /v1/deployments/{id}` — `viewer`; list item + `events_count: int`. **404** unknown.
- `GET /v1/deployments/{id}/events` — `viewer`; `events: Event[]`, `Event = { ts, stage: enum, message: str, level: enum<info|warn|error> }`.
- `GET /v1/deployments/sync-status` — `viewer`, not paginated; `{ synced: int, total: int, rows: SyncRow[] }`.
- `POST /v1/deployments/sync` — `operator`, idempotent; body `{ scope: "global" } | { agent_ids: str[] }` → **202** `{ sync_id, status: enum<queued|in_progress>, targets: int }`.
- `GET /v1/deployments/sync/{sync_id}` *(NEW — job status)* — `viewer`; `{ sync_id, status, targets, completed: int, failed: int, started_at, finished_at: ts? }`.

---

### 11.7 New-table key designs (DynamoDB)

> Resolves §7's missing access patterns. All tables on-demand billing; `created_at`/`updated_at` on every item.

**`DiscoveredAgents`** — backs §11.3.
- PK `id` (`disc-…`).
- **GSI-1 `status-index`**: PK `status`, SK `first_seen` → list unmanaged newest-first, `new_24h`.
- **GSI-2 `provider-index`**: PK `cloud_provider`, SK `first_seen` → provider filter + `/discovery/platforms` counts.
- `framework`/`risk` filters applied **post-query** (low-cardinality; avoids extra GSIs at MVP scale).
- Attrs: `id, name, cloud_provider, platform, framework, first_seen, risk, status, source_policy_id`.

**`DiscoveryScans`** — backs scan + status.
- PK `scan_id`.
- **GSI-1 `latest-index`**: PK `const="SCAN"`, SK `started_at` → most-recent scan for `summary.last_scan`.
- Attrs: `scan_id, cloud_providers(SS), status, started_at, finished_at, detected_count, error`.

**`Connections`** — backs §11.4.
- PK `id` (`conn-…`).
- **GSI-1 `provider-index`**: PK `cloud_provider` (unique-per-provider check → drives the `409`).
- Attrs: `id, cloud_provider, status, account_ref, credentials_ref, connected_at, last_error`.

**`Agents` (extend, LLD 05)** — add `cloud_provider` attr (stored + seeded). `platform-distribution` is computed with a small table Scan at MVP scale; the **`cloud-provider-index` GSI is deferred to P1** (per-provider `Select=COUNT` queries) once the fleet is large enough that the Scan cost matters — provisioning an unused GSI is write-amplification for zero read benefit (WS-21 T04, Kiro review). Agent↔policy attach stored as `attached_policy_ids: SS` on the agent item (single-table) — detach = `DELETE` from set.

**Deployments tables** (`Deployments`, `DeploymentEvents`) — **P1**, key design deferred with the domain.

---

## 12. False-positive / false-negative feedback & background re-check

> Backs the `false_positive_pct` field (§11.2) and the canvas **"FALSE POSITIVE"** controls. Core principle: **a decision cannot label itself.** Knowing a past ALLOW/DENY was wrong requires either a human or a *better judge* than the runtime made — never the runtime judge alone.

### 12.1 Definitions
- **False positive (FP):** a **DENY** that was actually legitimate. Labeled on *blocked* items.
- **False negative (FN):** an **ALLOW** that was actually malicious. Labeled on *allowed* items.
- The canvas exposes an FP control today; an FN control ("report missed threat") on allowed rows is **TBD** — confirm before P2.

### 12.2 Two label sources, one loop
| Source | Precision | Recall | Cost |
|--------|-----------|--------|------|
| **Human verdict** (FP/FN buttons) | High | Low (only what an operator notices) | ~free |
| **Background re-check** (auto candidate generation) | Lower (candidates, not truth) | High | $ |

They compose: **re-check generates candidates → routed to the same review queue → operator confirms via the same buttons → label.** The reported metric rests on **confirmed** labels; re-check only reduces how much a human must review.

### 12.3 Human verdict endpoint (the feedback capture)

#### `POST /v1/decisions/{decision_id}/verdict` — role `operator`
- `decision_id` = `{session_id}:{request_id}` (maps to signal-store keys).
- **Body:** `{ verdict: enum<false_positive|confirmed_threat|false_negative|confirmed_safe> (req), reason: str (req), operator_id: str (req) }`.
- **200:** `{ decision_id, verdict, verdict_at: ts }`.
- **409** if already verdicted; **404** unknown decision.
- **Storage:** write `operator_verdict, verdict_reason, verdict_by, verdict_at` onto the decision item in the validation-signal-store (no such attrs today).
- **Metric:** on `false_positive`, emit CloudWatch `FalsePositiveOverturns` (dims `AgentId`, `ThreatType`); on `false_negative`, emit `FalseNegativeReports`. Then `false_positive_pct = FalsePositiveOverturns / Denials` over range (both via `GetMetricData`, per §10.6). Reported value is a **confirmed-FP lower bound** (overturned ÷ all DENYs) — label as such in the UI.

### 12.4 Background re-check — needs a *better judge* (P1/P2)

Three judges, increasing cost. Runs **off the hot path** (no latency budget): scheduled batch or queue-driven, sampled/prioritized.

| Judge | Mechanism | Catches | Cost |
|-------|-----------|---------|------|
| **Rule-replay** | Re-run the *current* sigma/policy set against the stored input. New-rules-DENY on a past ALLOW = candidate **FN**; tuned-rules-ALLOW on a past DENY = candidate **FP**. | Drift as rules/intel improve | Cheap (engine exists, inputs persisted) |
| **Oracle re-eval** | Stronger model (bigger Claude + CoT + fuller context, or ensemble) re-scores the input; disagreement with runtime = candidate. | Genuine misclassifications | $$ — must sample |
| **Outcome correlation** | Did an ALLOWed action later correlate with a rollback / anomaly / downstream security event? | **FN via real-world harm** | Needs downstream telemetry |

```
decisions (signal store; user_input/tool_params persisted — replay-ready)
   │ sample/prioritize: all DENYs + low-confidence ALLOWs + N% sample
   ▼
async re-check worker ── rule-replay ─┐
                       ── oracle ──────┼─► disagreement → candidate {orig, new, confidence}
                       ── outcome join ┘     └─ write `recheck_verdict` on decision
   ▼
review queue ──► operator confirms via FP/FN buttons (§12.3) ──► label ──► metric + rule tuning
```

### 12.5 Constraints & caveats
- **No free ground truth** — re-check yields *candidates*; the oracle is itself fallible. Keep a small **human-labeled gold set** to calibrate the oracle before trusting it.
- **FN is structurally harder than FP** — only catchable via oracle or downstream harm, so FN rate is more estimate than measurement.
- **Replay faithfulness** — `user_input`/`tool_params` are persisted (faithful for stateless validators: sigma/ML). **Context-dependent validators** (trust score, session history) used mutable state at decision time; either snapshot context per decision (storage cost) or accept replay covers only the stateless validators.
- **Cost control mandatory** — never oracle every decision; prioritize DENYs (rare) + high-uncertainty ALLOWs; batch off-peak.

### 12.6 Phasing
| Phase | Scope |
|-------|-------|
| **P0** | Capture FP/FN verdicts (§12.3) and **store silently** — accumulate the gold-label set. **Do not** show `false_positive_pct` on the UX (returns `null`). Ensure decisions persist enough to replay (mostly already true). |
| **P1** | **Rule-replay** re-check + review queue. Cheap, reuses the engine. Surface candidates for human confirmation. |
| **P2** | **Oracle re-eval** + **outcome correlation**; publish FP%/FN% on the dashboard; feed confirmed labels into rule tuning. |

---

## 13. As-built reconciliation (verified against code)

> Added after a code audit of `src/security-controller/app/api/routes.py` and `cdk/stacks/api_stack.py`. This section is the **authoritative current state** where it disagrees with §3–§6 above (those captured the original plan). It records (a) the complete set of routes that exist in the controller, (b) endpoints that were added since the original inventory, and (c) request/response **contract changes** that diverged from the earlier spec.

### 13.1 Complete controller route list (as implemented)

Every `@router.*` in `routes.py`, with API Gateway exposure status:

| Method | Path | Exposed (APIGW)? | Section |
|--------|------|------------------|---------|
| GET | `/v1/health` | ✅ | §3 |
| POST | `/v1/validate` | ✅ | §3 |
| GET | `/v1/logs` | ✅ | §3 |
| GET | `/v1/sessions/{session_id}/decisions` | ✅ | §4 |
| GET | `/v1/sessions/{session_id}/signals` | ❌ | §4 |
| POST | `/v1/sessions/{session_id}/signals` | ❌ | §4 (new row) |
| GET | `/v1/decisions` | ✅ | §4, §13.4 |
| GET | `/v1/sessions` | ✅ | §4 |
| GET | `/v1/metrics` | ❌ (legacy) | §4 |
| GET | `/v1/metrics/overview` | ✅ | §6.1 / §11.2 |
| GET | `/v1/metrics/platform-distribution` | ✅ | §6.1 / §11.2 |
| GET | `/v1/metrics/decisions-timeseries` | ✅ | §6.1 / §11.2 |
| GET | `/v1/discovery/agents` | ✅ | §6.2 / §11.3 |
| GET | `/v1/discovery/summary` | ✅ | §6.2 / §11.3 |
| GET | `/v1/discovery/platforms` | ✅ | §6.2 / §11.3 |
| POST | `/v1/discovery/import` | ✅ | §6.2 / §11.3 |
| POST | `/v1/agents/{agent_id}/policies` | ✅ | §6.5 / §11.5 |
| DELETE | `/v1/agents/{agent_id}/policies/{policy_id}` | ✅ | §6.5 / §11.5 |
| POST | `/v1/decisions/{decision_id}/verdict` | ✅ | §12.3 |
| GET | `/v1/agents` | ✅ | §4 |
| GET | `/v1/agents/{agent_id}` | ✅ | §4 |
| GET | `/v1/agents/{agent_id}/tools` | ✅ | §4 |
| GET | `/v1/policies` | ✅ | §3 |
| POST | `/v1/policies` | ✅ | §3, §13.5 |
| GET | `/v1/policies/{policy_id}` | ✅ | §3 |
| PUT | `/v1/policies/{policy_id}` | ✅ | §3 |
| DELETE | `/v1/policies/{policy_id}` | ✅ | §3 |
| GET | `/v1/sigma-rules` | ✅ | §3, §13.2 |
| PATCH | `/v1/sigma-rules/{rule_id}` | ✅ | §3, §13.2 |
| GET | `/v1/logs/conversation/{conversation_id}` | ✅ | §4 |
| POST | `/v1/rollback` | ✅ | §3 |
| POST | `/v1/rollback/conversation/{conversation_id}` | ❌ | §4 |
| POST | `/v1/quarantine/{session_id}` | ✅ | §4, §13.3 |
| DELETE | `/v1/quarantine/{session_id}` | ✅ | §4, §13.3 (**new**) |

> **Note — `POST /discovery/scan` and the job-status GETs** (`/discovery/scans/{scan_id}`, `/deployments/sync/{sync_id}`) specified in §11.3/§11.6 are **not implemented** in the controller today. P0 discovery is the read-model (summary/platforms/agents/import only); `scan` and async job-status polling are deferred with their domains.

### 13.2 `GET /v1/sigma-rules` + `PATCH /v1/sigma-rules/{rule_id}` — contract changed

**What §3 originally said:** query `category, severity, enabled`; PATCH body `{status}` with stored `stable|deprecated`.

**As built (WS-23 fix):** the API now speaks the console's vocabulary while DynamoDB keeps the Sigma-native vocabulary internally.

- **`GET /v1/sigma-rules` query params:** `status` (`stable|experimental|deprecated` — the *stored* status filter, applied via the `status-index` GSI), `level` (`critical|high|medium|low`), `limit` (default 50, max 200), `cursor`. There is **no** `category`/`severity`/`enabled` query param.
- **`GET` response — each rule is mapped to the console contract** (not the raw DDB item):

  | Field | Type | Source |
  |-------|------|--------|
  | `rule_id` | `str` | DDB `rule_id` |
  | `title` | `str` | DDB `title` |
  | `category` | `str` | derived from the first `attack.*`/`owasp.*` tag, else `logsource.category`, else `"detection"` |
  | `severity` | `enum<critical\|high\|medium\|low>` | DDB `level` (renamed) |
  | `status` | `enum<enabled\|disabled>` | DDB `status`: `stable ⇒ enabled`, everything else (`experimental`/`deprecated`) ⇒ `disabled` (reflects real engine enforcement — only `stable` rules load) |
  | `match_count` | `int` | DDB `stats.match_count_24h` (flattened) |

- **`PATCH /v1/sigma-rules/{rule_id}` body:** `{ "status": "enabled" | "disabled" }`. Legacy `stable|deprecated` are still accepted for back-compat. The handler translates `enabled→stable` / `disabled→deprecated` before writing, and the response echoes the **console** vocabulary: `{ success, rule_id, status: "enabled"|"disabled" }`.
- **Cache behavior:** a successful PATCH invalidates the per-rule cache entry **and** the whole `sigma_rules:` list-cache family, so the next `GET` reflects the change immediately rather than after the 300s TTL. (Enforcement is independent of this cache — the `SigmaEngine` is constructed per validate request and re-reads `status='stable'` from DDB every call.)

### 13.3 `POST /v1/quarantine/{session_id}` is now idempotent + `DELETE` release added

**`POST /v1/quarantine/{session_id}` (changed):** previously returned `400 "Session already quarantined/suspended"` on a repeat. **Now idempotent** — re-quarantining an already-`quarantined`/`suspended` session returns `200` with the existing state and an `idempotent: true` flag instead of erroring. Success body:
```json
{ "success": true, "message": "...", "session_id": "...",
  "previous_status": "active", "new_status": "quarantined",
  "trust_score": 12.0, "idempotent": false }
```
A safe double-click / retry no longer fails. (`404` for unknown session still applies.)

**`DELETE /v1/quarantine/{session_id}` (NEW — WS-23):** operator "un-quarantine" / release. Idempotent.
- **Query:** `operator_id` (default `"operator"`).
- **Behavior:** sets `quarantine_status` back to `active` **and restores `trust_score` to 70** (just above the quarantine threshold) so the trust check doesn't immediately re-quarantine the session on its next validation. Releasing an already-`active` session is a no-op success (`idempotent: true`).
- **200:**
  ```json
  { "success": true, "message": "Session ... released from quarantine",
    "session_id": "...", "previous_status": "quarantined",
    "new_status": "active", "trust_score": 70.0 }
  ```
- **404** unknown session; **500** on update failure.

> **Enum note:** §2 lists `quarantine_status` as `active | quarantined | suspended`. Release always targets `active`; it does not transition `suspended` sessions through any intermediate state.

### 13.4 `GET /v1/decisions` — added `session_id` filter + flattened row fields

- **Added query param:** `session_id` (optional) — filter the cross-session scan to one session.
- **Full query set:** `since, until, agent_id, decision, threat_type, session_id, limit, cursor`.
- **Response rows now carry flat, console-ready fields** (WS-23) so `DecisionItem` renders without drill-down: each decision includes `decision_id` (`{session_id}:{request_id}`), `agent_id`, `agent_name`, `cloud_provider`, `platform`, `decision`, `threat_type`, `tool_name`, `reason`, `trust_score`, `timestamp` — plus the original `combined`/`signals` detail for back-compat.
- **Pagination caveat:** the handler currently queries per-day newest-first and **returns `next_token: null`** (cross-day cursor pagination is a documented follow-up). Live Activity reads the most-recent page; deep historical paging via this endpoint is not yet available.

### 13.5 `POST /v1/policies` — server-owned envelope fields now auto-generated

`PolicyCreateRequest` omits the server-owned envelope fields, but the policy schema validator requires `policy_id`/`status`/`created_at`/`created_by`. The create handler now **generates these up front** (`policy_id = "agent-config-{agent_id}"`, `status="active"`, timestamps, `created_by=operator`) so a well-formed create validates instead of being rejected. The S3 upload also now targets the **configured artifacts bucket** (`settings.s3_bucket`, CDK-suffixed) rather than the previously hard-coded `sentra-mvp-artifacts` name. No request/response shape change for callers — this fixes creates that previously failed.
