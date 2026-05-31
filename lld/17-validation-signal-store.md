# LLD 17: Validation Signal Store & Multi-Signal Combiner

**Version**: 0.2 (Revised post-Kiro-review — awaiting re-review)
**Last Updated**: 2026-05-26
**Status**: Draft – Ready for Review
**Owner**: Founder
**Prerequisites**:
- [LLD 03: Security Controller](03-security-controller.md)
- [LLD 04: Dashboard](04-dashboard-v2.md)
- [LLD 15: Cross-Cloud Connectors](15-cross-cloud-connectors.md)

**Related Documents**:
- [Workstream 17](../tasks/workstream-17-validation-signal-store.md) — execution tracking
- [LLD 09: Agent Execution & LLM Response](09-agent-execution-and-llm-response.md) — Bedrock connector that contributes guardrail signals
- [LLD 13: Demo Orchestrator](13-demo-orchestrator.md) — scenarios that exercise the multi-signal path

**Change log since v0.1**:
- §4: edge signals are now **symmetric** (emit one signal per invocation regardless of ALLOW/DENY outcome). Renamed `final` → `dashboard.combined`.
- §5.2: DDB sort key reordered to `request_id#timestamp_ms#source` so per-request queries are O(K) Query, not FilterExpression. Timestamp format locked to ISO 8601 ms+Z. TTL bumped 14 → 90 days. `decision_date` declared as explicit stored attribute (writer-populated).
- §6: added worked example "Bedrock Guardrail DENIES, Sentra ALLOWS". Dropped redundant `metadata.all_sources`.
- §7: DDB write is **sync best-effort with 200ms timeout**. BatchWriteItem partial failures retried up to 3 attempts.
- §9.2: **dropped option B (proximity matching) entirely**. Runner generates the correlation `request_id` and threads it via Bedrock `sessionAttributes`. Lambda echoes; connector reuses. Phase 1 includes the plumbing.
- §11: removed "missing request_id" entry — no longer possible. Added DDB timeout + BatchWriteItem partial-failure semantics.
- New §14 Test Plan, §15 Operational Runbook, §16 Cost Model.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Why Now — Concrete Trigger](#2-why-now--concrete-trigger)
3. [Architecture](#3-architecture)
4. [Signal Taxonomy](#4-signal-taxonomy)
5. [Data Models](#5-data-models)
6. [Combiner Module](#6-combiner-module)
7. [Storage Strategy — DDB + CloudWatch Dual-Write](#7-storage-strategy--ddb--cloudwatch-dual-write)
8. [APIs](#8-apis)
9. [Dashboard & Connector Integration](#9-dashboard--connector-integration)
10. [Configuration](#10-configuration)
11. [Error Handling](#11-error-handling)
12. [Monitoring & Observability](#12-monitoring--observability)
13. [Migration / Backwards Compatibility](#13-migration--backwards-compatibility)
14. [Test Plan](#14-test-plan)
15. [Operational Runbook](#15-operational-runbook)
16. [Cost Model](#16-cost-model)
17. [Out of Scope (Phase 1)](#17-out-of-scope-phase-1)
18. [Cross-References](#18-cross-references)

---

## 1. Overview

### 1.1 Purpose

Replace today's single-decision audit-log substrate with a multi-signal store that:

1. **Captures every signal** that contributed to a validation outcome (each Sentra sub-validator, each cloud-native guardrail, future ML classifier) as a first-class row.
2. **Combines signals** into a final decision using a pluggable algorithm (default: `deny-overrides`), shared between controller-internal use and the dashboard's read-time aggregation.
3. **Serves fast reads** for per-session, per-request, and time-range paginated scans from DynamoDB (single-digit ms p95), eliminating CloudWatch Logs Insights from hot-path queries.
4. **Preserves CloudWatch audit logs** unchanged as the compliance source of record.

### 1.2 Scope

| In scope | Out of scope |
|---|---|
| DDB table for signal storage with 90-day TTL | Long-term audit retention (CloudWatch keeps this) |
| `Signal` data model + combining algorithms (`deny-overrides` only) | Re-architecting validator internals — only their *output capture* changes |
| Endpoints: `/v1/sessions/{id}/signals`, `/v1/sessions/{id}/decisions`, `/v1/decisions` (paginated scan) | Streaming signal subscriptions / WebSocket push |
| Dual-write from `audit_logger` (DDB + CloudWatch) | Removing CloudWatch dual-write |
| Bedrock Lambda + connector emit a `request_id` threaded from the runner via `sessionAttributes` | Custom dashboard drill-down UI (Phase 2 polish) |
| Dashboard runner consumes new endpoints | Replacing `/v1/logs` (kept for compliance / cross-session fallback) |

### 1.3 Non-Goals

- Not an event-sourcing system. Signals are facts, not commands.
- Not a streaming pipeline. Reads are pull-based.
- Not unifying with `sentra-session-context` (tool_history serves a different projection).

---

## 2. Why Now — Concrete Trigger

S1 (cross-cloud demo) consistently shows `aws_attack: ALLOW` despite Sentra correctly returning DENY. Empirical RCA:

1. Naive Bedrock agent has no guardrail → `BedrockConnector` falls through to `decision="ALLOW"` (no guardrail trace observed).
2. Sentra's DENY lives only in the CloudWatch audit log.
3. Dashboard runner attempts an audit-log override via `/v1/logs`, backed by CloudWatch Logs Insights.
4. **Measured**: Insights indexing lag exceeds **60 seconds** for fresh `put_log_events` writes (60s of `results=0` for a just-written entry, see operational note in §15).
5. Dashboard runs the override ~1–3 s after the write → returns empty → override never fires.

Additional drivers:
- **S2/S3/S4 hit the same wall.** All four scenarios depend on reading recent decisions, often within the same step.
- **ML classifier is coming.** Sigma (regex) gains an ML sibling. We need an explicit multi-signal substrate so each validator's output is independently attributable.
- **Attribution is product UX.** The dashboard already renders a "By" column; the data model should match.

---

## 3. Architecture

### 3.1 System Diagram

```
┌──────────────────────────────────────────────────────────────────────┐
│ Sentra Security Controller (/v1/validate)                            │
│                                                                      │
│  ┌─────────────────────────────────────────────────────────┐         │
│  │ ValidationService.validate_tool_call(request)            │        │
│  │                                                          │        │
│  │   TrustChecker  ─────► Signal(source=sentra.trust)       │        │
│  │   PolicyEngine  ─────► Signal(source=sentra.policy)      │        │
│  │   SigmaEngine   ─────► Signal(source=sentra.sigma)       │        │
│  │   ContextValid. ─────► Signal(source=sentra.context)     │        │
│  │   AbuseDetector ─────► Signal(source=sentra.abuse)       │        │
│  │   [future ML]   ─────► Signal(source=sentra.ml_classifier)│       │
│  │                                                          │        │
│  │   ┌─────────────────────────┐                            │        │
│  │   │ Combiner(deny-overrides)│ ◄── all sentra.* signals    │       │
│  │   └─────────────────────────┘                            │        │
│  │                  │                                       │        │
│  │                  ▼                                       │        │
│  │     Sentra final verdict (returned in HTTP response)     │        │
│  └─────────────────────────────────────────────────────────┘         │
│                       │                                              │
│            audit_logger.log_signals(signals)                         │
│                       │                                              │
│           ┌───────────┴───────────┐                                  │
│           ▼                       ▼                                  │
│   CloudWatch Logs            DynamoDB                                │
│   /sentra/audit-logs         sentra-validation-signals               │
│   (compliance archive)       (90-day TTL, fast read)                 │
└──────────────────────────────────────────────────────────────────────┘
                                    ▲
                                    │ POST /v1/sessions/{id}/signals
                                    │   (edge signals — guardrails)
                          ┌─────────┴─────────┐
                          │ Bedrock Connector  │
                          │ Azure Connector    │
                          │ Vertex Connector   │
                          └────────────────────┘
                                    ▲
                                    │ GET /v1/sessions/{id}/decisions
                          ┌─────────┴─────────┐
                          │  Dashboard Runner  │
                          │  (re-combines all  │
                          │   signals → final) │
                          └────────────────────┘
```

### 3.2 End-to-End Decision Flow — S1 `aws_attack`

```
1. Runner generates request_id = "xc-s1-aws_attack-<uuid8>".
2. Runner invokes Bedrock with sessionAttributes={"sentra_request_id": "<rid>"}.
3. Nova Lite calls tool get_order_details(C12345).
4. Action Group Lambda reads sessionAttributes["sentra_request_id"] = <rid>.
5. Lambda → POST /v1/validate with request_id=<rid>.
6. ValidationService runs validators, producing Signals:
     trust:    ALLOW(score=100)
     policy:   ALLOW(tool in allowed_tools)
     sigma:    DENY(rule=PII_EXPOSURE)            ← contributes the DENY
     context:  ALLOW(no cross_cloud_dependency)
     abuse:    ALLOW(under rate limit)
7. Internal Combiner(deny-overrides) → sentra.combined = DENY (sigma wins).
8. audit_logger.log_signals: 5 DDB rows + 1 CloudWatch event, all keyed to <rid>.
9. Lambda returns 403 to Bedrock with sigma's reason.
10. Bedrock agent finishes stream.
11. BedrockConnector emits its observation:
      POST /v1/sessions/<sid>/signals
        {source: bedrock_guardrail, decision: ALLOW, request_id: <rid>}
12. Runner GET /v1/sessions/<sid>/decisions?request_id=<rid>
13. Controller queries DDB partition (Query, SK begins_with <rid>) → 6 signals.
14. Combiner re-applied: combined = DENY (sigma still wins; bedrock_guardrail
    ALLOW does not lift the DENY under deny-overrides).
15. Runner renders:
      Actual: DENY
      By:     🛡 sentra.sigma
      (expand) trust:ALLOW · policy:ALLOW · sigma:DENY · context:ALLOW ·
               abuse:ALLOW · bedrock_guardrail:ALLOW
```

No CloudWatch Insights in the hot path. No race condition. All correlation via the runner's `request_id`.

---

## 4. Signal Taxonomy

| Source | Producer | Layer | Default priority | Symmetric? |
|---|---|---|---|---|
| `sentra.trust` | `TrustChecker` | Controller | 90 | yes (always emits) |
| `sentra.policy` | `PolicyEngine` | Controller | 80 | yes |
| `sentra.sigma` | `SigmaEngine` (regex/pattern) | Controller | 70 | yes |
| `sentra.ml_classifier` | _Future_ ML model | Controller | 70 (ties with sigma; confidence breaks tie) | yes |
| `sentra.context` | `ContextValidator` | Controller | 60 | yes |
| `sentra.abuse` | `AbuseDetector` | Controller | 50 | yes |
| `sentra.cross_agent` | `CrossAgentValidator` | Controller | 50 | yes |
| `sentra.combined` | Internal combiner output | Controller | — (computed) | — |
| `bedrock_guardrail` | `BedrockConnector` | Edge (cloud-native) | 40 | yes |
| `azure_content_filter` | `AzureConnector` | Edge (cloud-native) | 40 | yes |
| `dashboard.combined` | Runner-side combiner | Dashboard | — (computed) | — |

**Symmetric emission rule**: Every producer emits **exactly one signal per invocation** with `decision ∈ {ALLOW, DENY}`. ALLOW means "I was consulted and approved." DENY means "I rejected." A missing signal means "this producer wasn't on the call path" — the combiner treats absence as a separate state (not ALLOW).

This rule eliminates the asymmetry trap (Kiro P2) where the combiner would see only Sentra signals after Azure Content Filter passed silently, then incorrectly conclude "Azure approved" when in fact "Azure was never asked."

**Naming convention** (locked): lowercase, dot-separated, `<scope>.<source>`. Scope is `sentra` for built-in validators, the cloud's short name for guardrails, `dashboard` for runner-side aggregates.

---

## 5. Data Models

### 5.1 `Signal`

```python
from dataclasses import dataclass, field
from typing import Literal, Optional

@dataclass(frozen=True)
class Signal:
    source: str                                       # see §4 taxonomy
    decision: Literal["ALLOW", "DENY"]
    reason: Optional[str] = None                      # human-readable
    priority: int = 0                                 # combiner tie-breaker
    confidence: Optional[float] = None                # 0.0-1.0; ML signals populate
    threat_type: Optional[str] = None                 # "PII_EXPOSURE", etc.
    matched_rule: Optional[str] = None                # rule name
    severity: Optional[str] = None                    # LOW|MEDIUM|HIGH|CRITICAL
    metadata: Optional[dict] = field(default_factory=dict)
```

Immutable. JSON-serializable. Mutable default fixed via `field(default_factory=dict)`.

### 5.2 DDB Schema — `sentra-validation-signals`

```
Partition key (PK):  session_id              (string)
Sort key (SK):       request_id#timestamp_ms#source
                     e.g. "xc-s1-aws_attack-4f3a#1779763724344#sentra.sigma"

Attributes:
  request_id          string    (runner-generated, threaded via sessionAttributes)
  timestamp_ms        number    (epoch milliseconds; integer for monotonic sort)
  timestamp_iso       string    ("2026-05-26T02:48:44.344Z" — ISO 8601 ms+Z, always)
  source              string    (signal taxonomy §4)
  decision            string    ("ALLOW" | "DENY")
  reason              string?
  threat_type         string?
  matched_rule        string?
  severity            string?
  priority            number
  confidence          number?
  agent_id            string
  tool_name           string
  tool_params         map (JSON)
  user_input          string
  platform            string    ("bedrock" | "azure_foundry" | "vertex_ai")
  cloud_region        string
  trust_score_before  number?
  trust_score_after   number?
  decision_date       string    ("YYYY-MM-DD" — writer-computed, used by GSI 2)
  expires_at          number    (epoch seconds; TTL attribute; now + 90 days)
  metadata            map?
```

**SK rationale**: `request_id` first so `Query(PK=session_id, SK begins_with <request_id>)` returns all signals for a single agent invocation in O(K) without a FilterExpression. `timestamp_ms` second so within-request signals sort chronologically. `source` last so simultaneous-millisecond signals from different validators don't collide on SK.

**Timestamp format** (locked): `timestamp_ms` is an integer (DDB Number). `timestamp_iso` is the canonical string `YYYY-MM-DDTHH:MM:SS.sssZ`. A writer-side guard rejects timestamps missing milliseconds. Both stored to support both query patterns without parsing.

**TTL**: `expires_at = now + 90 days`. DDB TTL deletes asynchronously. At ~1000 decisions/day × 6 signals × 90 days ≈ 540k items, well within DDB on-demand capacity sweet spot.

**GSI 1 — `agent-timestamp-index`** (agent-scoped lookup):
- PK: `agent_id` (string)
- SK: `timestamp_ms` (number)
- Projection: ALL

**GSI 2 — `decision-date-timestamp-index`** (paginated time-range scan):
- PK: `decision_date` (string, `YYYY-MM-DD` — explicitly stored attribute, writer-computed)
- SK: `timestamp_ms` (number)
- Projection: ALL

`decision_date` is a **real stored attribute**, not a derived one (DDB does not project from expressions). The writer computes it from `timestamp_iso[:10]` at write time. Missing it would silently drop the row from GSI 2 — `audit_logger` asserts presence.

GSI 2 doubles per-signal write capacity (each PutItem also writes to the GSI). At MVP traffic this is ~$0.05/month additional — accepted (see §16).

### 5.3 Cross-Item Grouping

Multiple signals share `request_id`. Dashboard groups by `request_id`, applies combiner. No write-time materialization of an aggregated row for external signals — the controller writes `sentra.combined` for caller convenience (matches the `/v1/validate` HTTP response body); the runner-layer aggregate is recomputed on every read because edge signals (`bedrock_guardrail`, `azure_content_filter`) may land after `/v1/validate` returned.

---

## 6. Combiner Module

### 6.1 Module Location

`src/security-controller/app/combiners/` — new package, consumed by:
- `ValidationService` (folds Sentra sub-signals into the `/v1/validate` HTTP response)
- `decisions_service.py` (folds all signals — Sentra + edge — at read time)
- Dashboard runner (via HTTP, no Python dependency on the controller package)

### 6.2 Interface

```python
from typing import Protocol, Sequence
from app.combiners.signal import Signal

class CombiningAlgorithm(Protocol):
    name: str
    def combine(self, signals: Sequence[Signal]) -> Signal: ...
```

### 6.3 Default — `DenyOverrides`

```python
class DenyOverrides:
    name = "deny-overrides"

    def combine(self, signals):
        if not signals:
            raise ValueError("no signals to combine")
        denies = [s for s in signals if s.decision == "DENY"]
        if denies:
            winner = max(denies, key=lambda s: (s.priority, s.confidence or 0))
            return Signal(
                source="combined",
                decision="DENY",
                reason=winner.reason,
                priority=winner.priority,
                threat_type=winner.threat_type,
                matched_rule=winner.matched_rule,
                severity=winner.severity,
                metadata={"winning_source": winner.source},
            )
        return Signal(
            source="combined", decision="ALLOW", reason=None, priority=0,
            metadata={},
        )
```

`metadata.all_sources` was dropped from v0.1 — the response payload in §8.2 already carries `signals[]` for the UI expander; duplicating it in metadata is wasted bytes.

### 6.4 Worked Examples

**Example A — Sentra DENY + Bedrock Guardrail ALLOW** (S1 `aws_attack` baseline):
```
Inputs:  sentra.sigma DENY priority=70 reason="PII_EXPOSURE"
         sentra.trust ALLOW priority=90
         sentra.policy ALLOW priority=80
         sentra.context ALLOW priority=60
         sentra.abuse ALLOW priority=50
         bedrock_guardrail ALLOW priority=40
Result:  combined = DENY, winning_source=sentra.sigma, reason="PII_EXPOSURE"
Rationale: 1 DENY in the set, picks it; lower-priority ALLOWs don't matter.
```

**Example B — Bedrock Guardrail DENY + Sentra ALLOW** (defense in depth from the input edge):
```
Inputs:  sentra.sigma ALLOW priority=70
         sentra.policy ALLOW priority=80
         bedrock_guardrail DENY priority=40 reason="Hate speech detected"
Result:  combined = DENY, winning_source=bedrock_guardrail, reason="Hate speech detected"
Rationale: deny-overrides; bedrock_guardrail is the sole denier and wins.
```

**Example C — Two DENYs, different priorities** (both edges fire):
```
Inputs:  sentra.sigma DENY priority=70 reason="PII_EXPOSURE"
         bedrock_guardrail DENY priority=40 reason="PII detected by AWS"
Result:  combined = DENY, winning_source=sentra.sigma (higher priority)
         reason="PII_EXPOSURE"
Rationale: sentra.sigma's higher priority drives the displayed reason; the dashboard
           expander still shows both denies so investors see defense in depth.
```

**Example D — Tied priority, confidence breaks tie** (ML lands):
```
Inputs:  sentra.sigma DENY priority=70 reason="weak regex hit" confidence=0.55
         sentra.ml_classifier DENY priority=70 reason="adversarial pattern" confidence=0.92
Result:  combined = DENY, winning_source=sentra.ml_classifier (higher confidence)
```

### 6.5 Future Algorithms (placeholders)

- `PermitOverrides` — any ALLOW wins. Document only; not for security path.
- `OrderedDenyOverrides` — deny-overrides + strict priority order.
- `WeightedConfidenceCombiner` — high-confidence ALLOW may override low-confidence DENY (ML-aware). Required when ML lands; **not** Phase 1.

Algorithm selection per request: reserved for Phase 2. Phase 1 hard-wires `deny-overrides`.

---

## 7. Storage Strategy — DDB + CloudWatch Dual-Write

### 7.1 Write Paths

| Writer | DDB | CloudWatch | Atomicity |
|---|---|---|---|
| `audit_logger.log_signals(signals)` (called once per `/v1/validate`) | N items (one per signal) via `BatchWriteItem` | 1 event with `signals[]` array | Per-item; partial failures retried up to 3 attempts on `UnprocessedItems` with exponential backoff (50/200/800ms) |
| `POST /v1/sessions/{id}/signals` (edge signals) | 1 item via `PutItem` | 1 event | Single-item; standard PutItem retry semantics |
| Legacy `audit_logger.log_decision(...)` callers | Wrapped — internally builds a single combined Signal and calls `log_signals` | unchanged | — |

### 7.2 Timing Budget

- **DDB write is synchronous best-effort** with a **200ms total timeout** (across all retries).
- If the timeout fires: log warning, increment `signal_store.write.timeout`, return the validation HTTP response anyway.
- CloudWatch write is also synchronous (already is today; format is additive only).
- The 200ms budget protects `/v1/validate` p95 (current ~600ms, budget allows 800ms with DDB overhead).

### 7.3 Failure Modes

| Failure | Behavior |
|---|---|
| DDB available but slow (>200ms) | Timeout-and-log. Validation succeeds. Runner read may miss a partial signal set; combiner produces partial result. UI shows "3 of 5 signals visible" — degrades visibly. |
| DDB unavailable (region issue) | All writes timeout; warnings logged. CloudWatch alone has the data. Runner falls back to `/v1/logs` (the same CloudWatch Insights path it uses today — slow but the existing slow path). |
| Specific item unprocessed after 3 retries | That signal is missing from DDB; logged. CloudWatch event still includes it. Runner read shows degraded set. |
| CloudWatch fails, DDB succeeds | Warning logged. Validation succeeds. Reconciliation runbook §15 step 3. |
| Both fail | Validation response already returned to caller (validation itself ran in-memory). Operator alarm. |

CloudWatch remains the compliance source of record. DDB is a fast-read cache that *usually* agrees with CloudWatch and degrades gracefully on disagreement.

### 7.4 CloudWatch Event Format (Backward-Compatible)

Existing single-event-per-validation format preserved. `signals[]` field added:

```json
{
  "request_id": "xc-s1-aws_attack-4f3a",
  "session_id": "xcloud-s1_...",
  "agent_id": "sentra-mvp-customer-service-agent-naive",
  "decision": "DENY",
  "reason": "Threat detected: PII_EXPOSURE",
  "signals": [
    {"source": "sentra.trust",   "decision": "ALLOW"},
    {"source": "sentra.policy",  "decision": "ALLOW"},
    {"source": "sentra.sigma",   "decision": "DENY", "reason": "..."},
    {"source": "sentra.context", "decision": "ALLOW"},
    {"source": "sentra.abuse",   "decision": "ALLOW"}
  ],
  "platform": "bedrock",
  "cloud_region": "us-east-1"
}
```

Old consumers (`decision` / `reason`) keep working. New consumers drill into `signals[]`.

---

## 8. APIs

### 8.1 `POST /v1/sessions/{session_id}/signals` — external producer

For edge producers (Bedrock connector, Azure connector, future) to report a signal.

Request:
```json
{
  "request_id": "xc-s1-aws_attack-4f3a",
  "source": "bedrock_guardrail",
  "decision": "ALLOW",
  "reason": null,
  "priority": 40,
  "agent_id": "sentra-mvp-customer-service-agent-naive",
  "tool_name": null,
  "platform": "bedrock",
  "cloud_region": "us-east-1",
  "metadata": {"guardrail_id": "...", "trace_present": false}
}
```

Response: `201 Created`, `{"signal_sk": "...", "stored_at": "..."}`.

Validation: `source` must be in the taxonomy; `decision` must be ALLOW or DENY; `request_id` required.

### 8.2 `GET /v1/sessions/{session_id}/decisions`

Signals grouped by `request_id`, with combiner applied per group.

Query: `request_id` (optional), `agent_id` (optional), `limit` (default 100, max 500).

Response:
```json
{
  "session_id": "xcloud-s1_...",
  "decisions": [
    {
      "request_id": "xc-s1-aws_attack-4f3a",
      "timestamp_iso": "2026-05-26T02:48:44.344Z",
      "combined": {
        "decision": "DENY",
        "reason": "Threat detected: PII_EXPOSURE",
        "winning_source": "sentra.sigma"
      },
      "signals": [
        {"source": "sentra.sigma", "decision": "DENY", "reason": "...", "priority": 70},
        {"source": "sentra.trust", "decision": "ALLOW", "priority": 90},
        "..."
      ]
    }
  ],
  "total": 1
}
```

Latency target: p95 ≤ 100ms (single DDB partition Query + in-memory combine).

### 8.3 `GET /v1/sessions/{session_id}/signals`

Raw signal list, no combiner. Filters: `request_id`, `source`, `since`, `limit`. For debugging.

### 8.4 `GET /v1/decisions` — paginated time-range scan

Backed by GSI 2 (`decision-date-timestamp-index`).

Query: `since` (ISO 8601, default now-24h), `until` (default now), `agent_id`, `decision`, `threat_type`, `limit` (default 50, max 200), `cursor` (opaque pagination token from previous response).

Response:
```json
{
  "decisions": [ /* same shape as 8.2 */ ],
  "next_cursor": "eyJ0aW1lc3RhbXAiOiAi...==",
  "has_more": true
}
```

**Cursor opacity** (binding): the cursor is a base64-encoded DDB `LastEvaluatedKey`. Consumers must treat it as an opaque blob. Do not parse, reconstruct, or persist beyond the immediate pagination loop. Format may change.

### 8.5 `GET /v1/logs` — unchanged

Still backed by CloudWatch Logs Insights. Retained for:
- Compliance audits ("show everything for May 2026")
- Cross-validation against DDB during incidents
- Sessions older than 90 days (past DDB TTL)

No deprecation planned. Both paths coexist.

---

## 9. Dashboard & Connector Integration

### 9.1 `request_id` Correlation — the Plumbing

**The runner originates `request_id` and threads it via Bedrock `sessionAttributes`.** This is the single mechanism that ties all signals — controller-side and edge-side — to the same logical request. Replaces v0.1's proximity-matching heuristic (Kiro P0).

#### 9.1.1 Runner-side (origination)

```python
# src/dashboard/components/cross_cloud_scenarios.py
request_id = f"xc-{scenario_id}-{step_id}-{uuid.uuid4().hex[:8]}"
```

One `request_id` per scenario step. One step = one agent invocation = one logical "row" the dashboard renders.

#### 9.1.2 Bedrock invocation — threading

```python
# src/connectors/bedrock/bedrock_connector.py
bedrock_agent_runtime.invoke_agent(
    agentId=agent_id,
    agentAliasId=alias_id,
    sessionId=session_id,
    inputText=user_message,
    enableTrace=True,
    sessionState={
        "sessionAttributes": {"sentra_request_id": request_id},
    },
)
```

`sessionAttributes` is a Bedrock-native pass-through — the agent runtime forwards it to every Action Group invocation in this session.

#### 9.1.3 Lambda — echo and use

```python
# lambda/bedrock_agent_actions/index.py
session_attrs = event.get("sessionAttributes") or {}
request_id = session_attrs.get("sentra_request_id") or f"bedrock-{uuid.uuid4().hex[:12]}"
# request_id is now passed to validate_with_sentra() unchanged
```

Fallback to a Lambda-generated UUID preserves backward compatibility — if the runner ever invokes without sessionAttributes (e.g., from the orchestrator's `prompts:` block, not the cross_cloud runner), the existing behavior continues.

#### 9.1.4 Connector — final emission

After `invoke_agent` returns, the connector emits its `bedrock_guardrail` signal with the same `request_id`:

```python
signals_client.post(
    session_id=session_id,
    payload={
        "request_id": request_id,
        "source": "bedrock_guardrail",
        "decision": "DENY" if observed_guardrail_trace else "ALLOW",
        "reason": guardrail_reason,
        "priority": 40,
        "agent_id": agent_id,
        "platform": "bedrock",
        "cloud_region": region,
    },
)
```

**Multi-tool-call within one invocation**: when Nova Lite calls 3 tools, the Lambda fires 3 times — each reads the *same* `request_id` from sessionAttributes. All Sentra signals share `request_id`. The combiner combines all of them under that request_id. The dashboard's per-step row reflects the worst verdict across all tool calls — which is exactly the UX we want.

#### 9.1.5 Azure invocation — analogous

Azure OpenAI doesn't have a sessionAttributes primitive, but the Function App is our code — the connector passes `request_id` in the HTTP body of `/api/tool/{name}`:

```python
# src/connectors/azure_foundry/azure_connector.py
function_response = post(
    f"{base}/api/tool/{tool_name}",
    json={
        "request_id": request_id,
        "session_id": session_id,
        "params": tool_params,
        "user_input": user_input,
    },
)
```

The Function App forwards `request_id` to `/v1/validate`. The connector emits its `azure_content_filter` signal with the same id after the agent loop completes.

### 9.2 Cross-Cloud Runner — read path

```python
# src/dashboard/components/cross_cloud_scenarios.py
decisions = client.get_session_decisions(
    session_id=session_id,
    request_id=request_id,
)
combined = decisions[0]["combined"]   # the only group; we filtered
step_result.actual_decision = combined["decision"]
step_result.decision_source  = combined["winning_source"]
step_result.signals          = decisions[0]["signals"]   # for UI expander
```

No CloudWatch Insights involvement. No retry. No proximity match. Deterministic.

### 9.3 Edge Signal Symmetry

Per §4's symmetric rule, **every** Bedrock invocation produces exactly one `bedrock_guardrail` signal (ALLOW or DENY), and every Azure tool call produces exactly one `azure_content_filter` signal. Absence of a signal in the response = "this producer wasn't on the call path" (e.g., a Bedrock invocation that didn't go through any Azure tool).

This costs ~1 extra DDB write per invocation. At MVP traffic that's negligible (see §16).

### 9.4 UI Surface (Phase 1)

- Existing "By" column populated from `combined.winning_source` with the source badge taxonomy (`🛡 sentra.sigma`, `🟧 bedrock_guardrail`, etc.).
- Step row expander reveals `signals[]` — every contributor with its decision and reason.
- No new tab or dedicated panel.

Phase 2 polish: dedicated drill-down per `request_id` with timeline of signals + per-signal latency.

---

## 10. Configuration

```yaml
# config/environments/<env>.yaml
signal_store:
  enabled: true
  table_name: sentra-validation-signals
  ttl_days: 90
  write_timeout_ms: 200
  cloudwatch_dual_write: true        # off only in tests
  batch_max_retries: 3
  retry_backoff_ms: [50, 200, 800]

combiner:
  default_algorithm: deny-overrides
  priorities:
    sentra.trust: 90
    sentra.policy: 80
    sentra.sigma: 70
    sentra.ml_classifier: 70
    sentra.context: 60
    sentra.abuse: 50
    sentra.cross_agent: 50
    bedrock_guardrail: 40
    azure_content_filter: 40
```

Priorities loaded at controller startup. Hot reload via `POST /v1/admin/reload-config` (existing pattern).

### 10.1 IaC

New CDK construct `cdk/constructs/signal_store_table.py`:
- DDB on-demand table, `RemovalPolicy.RETAIN`
- TTL attribute `expires_at`
- GSI 1 and GSI 2 per §5.2
- IAM grants for the controller task role: `PutItem`, `BatchWriteItem`, `Query` on table + both GSIs; `Scan` on GSI 2 only

Dashboard task role: no direct DDB access (reads via controller HTTP).

---

## 11. Error Handling

| Scenario | Behavior |
|---|---|
| DDB write timeout (>200ms) | Log warning + metric. Validation response returned normally. Runner sees partial signal set on read; combiner produces best-effort result. |
| `BatchWriteItem` returns `UnprocessedItems` | Retry up to 3 times with backoff [50ms, 200ms, 800ms]. Items still unprocessed after retries are dropped (CloudWatch event still includes them — no data loss for compliance). |
| DDB region failure | All writes timeout. CloudWatch is canonical. Runner reads fall through to `/v1/logs`. |
| Signal with unknown `source` | Accepted and stored. Combiner uses `priority=0`. Warning logged. (Don't fail-secure on taxonomy drift — the writer is trusted.) |
| Combiner receives empty signals list | `ValueError`. Caller (decisions_service) catches and returns 200 with `combined=null`, `signals=[]`. UI shows "no signals yet" — usually means the runner queried before any writer landed. |
| Signal POST with malformed body | 400 with field-level error. Edge producers retry once; subsequent failures dropped. |
| Cursor decode failure on `/v1/decisions` | 400. The cursor is opaque to the consumer; malformation means client tampering or version skew. |

**Fail-secure principle** (deny on validation *error*) lives in `ValidationService`, unchanged. The combiner is a pure function over already-produced signals and never causes a fail-secure outcome on its own.

The v0.1 "missing `request_id`" entry is removed — §9.1's plumbing makes it impossible. If the Lambda ever runs without `sessionAttributes["sentra_request_id"]` set (the fallback path), it generates a Lambda-side UUID and the row is still well-formed.

---

## 12. Monitoring & Observability

CloudWatch metrics (controller emits):

- `signal_store.write.success` (count, dim: `source`)
- `signal_store.write.failure` (count, dim: `source`, `error_type`)
- `signal_store.write.timeout` (count) — DDB exceeded 200ms budget
- `signal_store.write.latency_ms` (p50/p95/p99)
- `signal_store.read.requests` (count, dim: `endpoint`)
- `signal_store.read.latency_ms` (p50/p95/p99)
- `signal_store.read.empty_result` (count) — race-condition indicator

Alarms (Phase 1):
- `signal_store.write.timeout` rate > 1% over 5 minutes → page operator (DDB regional issue).
- `signal_store.write.failure` rate > 0.1% over 1 hour → investigate (taxonomy drift or schema bug).

Dashboards: "Signal Store Health" panel on the existing controller CloudWatch dashboard.

---

## 13. Migration / Backwards Compatibility

| Existing component | Behavior |
|---|---|
| `audit_logger.log_decision(...)` callers | Wrapped — internally calls `log_signals` with the validators' breakdown. No caller changes. |
| `/v1/logs` consumers | Unchanged. Continue reading CloudWatch. |
| Existing CloudWatch audit log format | Backward-compatible. `signals[]` is additive. |
| Dashboard panels not using new endpoints | Unchanged. The cross-cloud runner migrates first; other panels follow only when value justifies. |
| Existing DDB tables (`sentra-policies`, `sentra-session-context`) | Untouched. New table is additive. |
| Bedrock Action Group Lambda | Modified to read `sessionAttributes["sentra_request_id"]`. Fallback to UUID generation preserves the orchestrator's existing `prompts:` flow. |
| Bedrock connector | New signal POST after stream end. New `sessionAttributes` plumb-through. |

**Rollout order** (one deployable unit per step; each independently revertable):
1. DDB table + IaC (no code path uses it yet)
2. Audit logger dual-write + validator signal emission (rows start landing; nothing reads)
3. Read endpoints
4. Lambda `sessionAttributes` read + connector signal POSTs (correlation now end-to-end)
5. Dashboard runner cut-over (replaces audit-lookup)

---

## 14. Test Plan

### 14.1 Unit Tests

**Combiner** (`tests/unit/test_combiner.py`):
1. Empty signal list → `ValueError`.
2. Single ALLOW → combined ALLOW, no winning_source.
3. Single DENY → combined DENY, that source wins.
4. All ALLOW (5 signals) → combined ALLOW.
5. Multiple DENYs with distinct priorities → highest priority wins.
6. Tied priorities + different confidence → higher confidence wins (Example D).
7. Tied priority + tied confidence → deterministic tie-break (e.g., alphabetical on source).
8. Bedrock Guardrail DENY + Sentra ALLOW → combined DENY, source=bedrock_guardrail (Example B).
9. Unknown source name → priority=0, included in combine without crash.

**Signal store writer** (`tests/unit/test_signal_store_writer.py`):
10. Writer rejects timestamps without milliseconds (raises ValueError).
11. Writer computes `decision_date` from `timestamp_iso[:10]`.
12. BatchWriteItem mocked to return UnprocessedItems → retry path executes ≤3 times.
13. BatchWriteItem mocked to time out → graceful degrade (no exception bubbles).

### 14.2 Integration Tests

**End-to-end signal flow** (`tests/integration/test_signal_store.py`, gated by `RUN_INTEGRATION=1`):
14. POST `/v1/validate` with PII-bearing input → DDB shows 5 sentra.* rows; GET `/v1/sessions/{id}/decisions?request_id=...` returns combined DENY with winning_source=sentra.sigma.
15. Two POSTs to `/v1/validate` for the same session+different request_ids → grouped separately in the decisions response.
16. Edge signal POST after the validate → grouped with the same request_id; combiner sees both.
17. Request_id collision under same-millisecond timestamps → both signals stored (SK differs by source); no DDB ConditionalCheckFailedException.
18. DDB write fails (mocked region error) → validation succeeds; CloudWatch row exists; `/v1/sessions/{id}/decisions` returns 0 decisions for the affected session; runner-side combiner produces a "no signals" outcome.
19. GSI 2 paginated scan returns time-ordered results across multiple sessions; cursor round-trips.

**Cross-cloud demo** (`tests/integration/test_cross_cloud_scenarios.py`, RUN_INTEGRATION=1):
20. S1 `aws_attack` fires → `actual_decision = DENY`, `decision_source = sentra.sigma`. (The original bug; this test prevents regression.)
21. S1 `azure_attack` fires → still DENY with `sentra.sigma`, plus an `azure_content_filter` ALLOW signal in `signals[]`.
22. S3 multi-step refund flow → cross-cloud dependency signal appears as `sentra.context: DENY` on the refund step when the verification step is missing.

### 14.3 Load Test (manual, pre-rollout)

23. 100 concurrent `/v1/validate` calls to a single session → all signals correlate correctly; no SK collisions; p95 latency stays under 800ms (600ms validator + 200ms DDB budget).

---

## 15. Operational Runbook

### 15.1 Indexing Lag Class of Bug

CloudWatch Logs Insights indexing lag (the root cause this LLD addresses) can resurface for any new dashboard panel that bypasses `/v1/sessions/{id}/decisions`. **Rule**: any read path that queries audit data within 5 minutes of a validation must use the DDB-backed endpoint, not `/v1/logs`. If a panel is showing stale or missing recent data, check whether it's calling `/v1/logs` and switch it.

### 15.2 DDB vs CloudWatch Disagreement

| Disagreement window | Trust which? | Action |
|---|---|---|
| Within 5 min of validation | DDB | CloudWatch event may still be propagating across availability zones. DDB write happens before the HTTP response. |
| 5 min – 90 days | DDB | Both should agree. If they don't, log a discrepancy with both records' contents to `controller.discrepancy` log group for investigation. |
| > 90 days | CloudWatch | Past DDB TTL; CloudWatch is the only record. |

If a regulator or compliance audit queries a specific decision and DDB has it but CloudWatch doesn't (the rare "DDB succeeded, CloudWatch failed" case), CloudWatch is the source of record — escalate per the existing compliance runbook.

### 15.3 Recovery — DDB Region Outage

1. Validation continues to succeed (CloudWatch dual-write covers it).
2. Dashboard runner reads degrade — fall through to `/v1/logs` (slow but correct).
3. After DDB recovery: backfill is **not** automatic. Historical signals from the outage window live only in CloudWatch. Operator may run `scripts/backfill_signals_from_cloudwatch.py` (Phase 2 tool, not Phase 1) to reconstruct.
4. Document the outage window in the relevant scenario's runbook so demo replays in that window skip the affected sessions.

### 15.4 Schema Drift — Taxonomy Source Not Recognized

If `signal_store.write.failure` spikes with `error_type=unknown_source`, a writer is emitting a source string not in §4. The combiner treats unknown sources as `priority=0` — it doesn't crash, but the source's reason will lose tie-breaks. Patch the taxonomy or fix the writer.

---

## 16. Cost Model

DDB on-demand pricing (us-east-1, 2026 rates):
- Write request: $1.25 per million WCUs (1 WCU = 1KB write).
- Read request: $0.25 per million RCUs (1 RCU = 4KB strongly-consistent read).
- Storage: $0.25 per GB-month.

**MVP traffic estimate**: 1000 validations/day × 6 signals each = 6000 main-table writes/day. GSI 1 + GSI 2 each project the full item → effective 18000 WCU equivalents/day.

| Item | Monthly |
|---|---|
| Writes (main + 2 GSIs, ~540k WCUs) | ~$0.68 |
| Storage (~540k items × ~1KB × 1mo retained × 3 indexes) | ~$0.40 |
| Reads (dashboard polls, ~10k Queries/day × ~10 items each) | ~$0.08 |
| **Total** | **~$1.16/month** |

Even at 10× traffic, this is ~$12/month. Negligible against the demo/Series-A horizon. The cost case for picking DDB over CloudWatch Insights is not "save money" — it's read latency. DDB happens to also be cheap.

---

## 17. Out of Scope (Phase 1)

- `WeightedConfidenceCombiner` (lands with the ML classifier workstream)
- Streaming signal subscription / WebSocket push
- Dedicated drill-down UI for per-request signal timeline
- Cross-session aggregations beyond `/v1/decisions` paginated scan
- Replay / re-evaluation of historical signals against updated rules
- Backfilling DDB from existing CloudWatch audit logs
- `scripts/backfill_signals_from_cloudwatch.py` (referenced in §15.3 — Phase 2)

---

## 18. Cross-References

| Doc | Purpose |
|---|---|
| [Workstream 17](../tasks/workstream-17-validation-signal-store.md) | Execution tracking |
| [LLD 03: Security Controller](03-security-controller.md) | Validator stack; this LLD adds output capture |
| [LLD 04: Dashboard](04-dashboard-v2.md) | Consumer of new endpoints |
| [LLD 15: Cross-Cloud Connectors](15-cross-cloud-connectors.md) | First consumer beyond single-cloud demo |
| [LLD 09: Agent Execution](09-agent-execution-and-llm-response.md) | Bedrock connector → signal producer |
| [best-practices.md §11](../best-practices.md#11-cloud-account-reference) | DDB region / table-name conventions |
