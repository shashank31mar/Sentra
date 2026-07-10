/**
 * DTOs from LLD-21 §6 / §11. Nullable fields follow §11.2 explicitly:
 * never assume non-null (e.g. `trust_score` is null on an empty fleet).
 */
import type {
  AgentStatus,
  CloudProvider,
  ConnectionStatus,
  Decision,
  DiscoveryStatus,
  MetricsRange,
  Platform,
  PolicyStatus,
  QuarantineStatus,
  Risk,
  ScanStatus,
  SigmaStatus,
  ThreatType,
  TimeseriesBucket,
  TrustStatus,
  Verdict,
} from './enums'

/** Error envelope (LLD §2 / §11.1). */
export interface ApiErrorBody {
  error: string
  error_code: string
  request_id?: string
}

/* ----------------------------- Identity ----------------------------- */

/**
 * Current operator identity, surfaced same-origin by the console edge at
 * `/whoami` (it echoes the ALB-injected Cognito claims). All fields are
 * best-effort — the ALB only guarantees the identity (email) by default, so
 * `name`/`groups` may be empty. Always guard before display.
 */
export interface CurrentUser {
  email: string | null
  name: string | null
  username: string | null
  groups: string[]
}

/** RBAC role on a tenant (LLD-26 §6.3). Ordered viewer < editor < admin < owner. */
export type TenantRole = 'owner' | 'admin' | 'editor' | 'viewer'

export interface TenantMembership {
  tenant_id: string
  role: TenantRole
  is_primary: boolean
}

/**
 * Server-derived operator context (`GET /v1/me`, LLD-26 WS-D D3b). This — NOT
 * the cosmetic email-domain `tenantOf()` — is the authoritative tenant + role.
 * The server resolves the tenant from the Cognito session; the console only
 * *renders* to it (client gating is UX, the server still enforces every write).
 */
export interface MeContext {
  sub: string
  email: string
  tenant_id: string
  role: TenantRole
  is_platform: boolean
  memberships: TenantMembership[]
}

/**
 * An agent currently riding the WS-B B1 legacy-fallback window: enforce is on for
 * its tenant but it hasn't registered a credential yet, so it runs on the legacy
 * self-asserted path on borrowed time. The console surfaces these so operators
 * onboard or retire them before the per-agent deadline expires to a hard DENY.
 * Times are epoch-ms (the backend's `first_seen_ms` / `deadline_ms`).
 */
export interface ResidualAgent {
  agent_id: string
  tenant_id: string
  first_seen_ms: number
  deadline_ms: number
  expired: boolean
}

export interface ResidualAgentsResponse {
  tenant_id: string
  residual_agents: ResidualAgent[]
  count: number
}

/** Generic cursor-paginated response, normalized by the api client. */
export interface Page<T> {
  items: T[]
  total: number
  /** `null` ⇒ last page (LLD §11.1). */
  next_token: string | null
}

export interface Paginated {
  limit?: number
  cursor?: string
}

/* ----------------------------- Metrics ----------------------------- */

export interface MetricsOverview {
  range: MetricsRange
  threats_blocked: number
  threats_blocked_delta_pct: number | null
  attack_categories: number
  active_agents: number
  clouds: number
  /** null when no samples in range — NOT 0 (§11.2). */
  trust_score: number | null
  trust_status: TrustStatus
  agents_below_threshold: number
  requests_total: number
  avg_latency_ms: number
  quarantined: number
  /** P0: always null / hidden (§11.2). */
  false_positive_pct: number | null
}

export interface ProviderDistribution {
  cloud_provider: CloudProvider
  label: string
  count: number
  pct: number
}

export interface PlatformDistribution {
  total_nodes: number
  providers: ProviderDistribution[]
}

export interface TimeseriesPoint {
  t: string
  allowed: number
  blocked: number
}

export interface DecisionsTimeseries {
  range: MetricsRange
  bucket: TimeseriesBucket
  series: TimeseriesPoint[]
}

/* ----------------------------- Decisions / Logs ----------------------------- */

export interface DecisionItem {
  /** `{session_id}:{request_id}` (LLD §12.3). */
  decision_id: string
  session_id: string
  request_id: string
  agent_id: string
  agent_name: string
  cloud_provider: CloudProvider
  platform: Platform | null
  decision: Decision
  threat_type: ThreatType | null
  tool_name: string | null
  reason: string | null
  trust_score: number | null
  timestamp: string
  /**
   * FX-3.1: the deciding validator (e.g. `sentra.sigma`, `sentra.policy`) for the
   * per-detector facet. OPTIONAL — the field is a backend field-add on `/decisions`
   * rows (ws-g-fix-backend, `winning_source` exists on `SessionDecision.combined`
   * but not yet the list shape). Absent ⇒ the facet ships PARTIAL/disabled; NEVER
   * derive the source list from a FE constant.
   */
  winning_source?: string | null
}

export interface LogEntry {
  id: string
  timestamp: string
  session_id: string | null
  agent_id: string | null
  decision: Decision | null
  threat_type: ThreatType | null
  message: string
}

export interface VerdictRequest {
  verdict: Verdict
  reason: string
  // NOTE: no `operator_id` — the server attributes the verdict to the VERIFIED
  // `ctx.sub`, never a spoofable client field (M-G3.13, D8). Dropping the type
  // field enforces that no caller re-adds the dead stub.
}

export interface VerdictResult {
  decision_id: string
  verdict: Verdict
  verdict_at: string
}

export interface QuarantineRequest {
  reason: string
  // No `operator_id` — server derives the operator from `ctx.sub` (M-G3.13, D8).
}

/* ---------------------------- Sessions ---------------------------- */

/** A runtime session row from `GET /v1/sessions` (LLD §Task 11). */
export interface SessionInfo {
  session_id: string
  user_id: string
  agent_id: string
  trust_score: number
  quarantine_status: QuarantineStatus
  total_requests: number
  allow_count: number
  deny_count: number
  consecutive_allows: number
  created_at: string
  last_activity: string
}

export interface SessionsResponse {
  sessions: SessionInfo[]
  total: number
  next_token?: string | null
}

/** Operator un-quarantine result from `DELETE /v1/quarantine/{id}`. */
export interface ReleaseResult {
  success: boolean
  session_id: string
  new_status: string
  previous_status?: string
  trust_score?: number
  idempotent?: boolean
}

/* ---------------- Session decision trace (forensics) ---------------- */

/** One validator's contribution to a decision (`GET /v1/sessions/{id}/decisions` → signals[]). */
export interface DecisionSignal {
  source: string // e.g. sentra.sigma, sentra.policy, sentra.trust, sentra.ml_classifier, sentra.context
  decision: Decision | null
  reason: string | null
  priority: number | null
  confidence: number | null
  threat_type: ThreatType | null
  matched_rule: string | null
  severity: string | null
  metadata: Record<string, unknown>
}

/** The combined verdict for a request (winning validator folded over the signals). */
export interface DecisionCombined {
  source: string
  decision: Decision
  reason: string | null
  winning_source: string | null
  threat_type: ThreatType | null
  matched_rule: string | null
  severity: string | null
}

/** One request's full trace: the prompt, caller, and per-validator breadcrumbs. */
export interface SessionDecision {
  request_id: string
  timestamp_iso: string | null
  user_input: string | null
  agent_id: string | null
  tool_name: string | null
  source_ip: string | null
  combined: DecisionCombined
  signals: DecisionSignal[]
}

export interface SessionDecisionsResponse {
  session_id: string
  decisions: SessionDecision[]
  total: number
  next_token: string | null
}

/* ------------- Session trail (WS-D recomputed coverage) ------------- */

/** One validator's coverage bucket in the WS-D trail (`GET /v1/sessions/{id}/trail`
 *  → coverage[]). The four states mirror the writer's classifier (§7.2):
 *  `ran` (emitted a verdict) / `ran_abstain` / `ran_error` / `not_run` (pipeline
 *  short-circuited before it). `display_name`/`state_label` are server-derived on
 *  READ (never stored) — raw `source`/`state` stay machine values. */
export interface SessionTrailEntry {
  source: string
  state: 'ran' | 'ran_abstain' | 'ran_error' | 'not_run'
  decision: Decision | null
  reason: string | null
  latency_ms: number | null
  display_name: string
  state_label: string
}

/**
 * The WS-D server-recomputed decision trail for ONE request
 * (`GET /v1/sessions/{id}/trail?request_id=`, `routes.py:583`, LIVE per lld/40 v1.4).
 * The server recomputes `winning_source`/`block_point` on read from the ran DENY
 * rows (the durable copy lives on the CloudWatch `sentra.combined` event, not DDB)
 * and classifies every validator into the four coverage buckets. Distinct from the
 * client-reconstructed `SessionDecisionsResponse` — this is the authoritative trail.
 */
export interface SessionTrail {
  session_id: string
  request_id: string
  phase: string
  winning_source: string | null
  winning_source_display: string | null
  block_point: string | null
  decision: Decision
  coverage: SessionTrailEntry[]
  coverage_total: number
  ran_count: number
  abstain_count: number
  ran_error_count: number
  not_run_count: number
  next_token: string | null
}

/* ----------------------------- Agents ----------------------------- */

export interface AgentListItem {
  agent_id: string
  name: string
  platform: Platform
  cloud_provider: CloudProvider
  status: AgentStatus
  trust_score_avg: number | null
  requests_total: number
  requests_allowed: number
  requests_denied: number
  active_sessions: number
  last_seen: string | null
  /** The agent's governing policy binding, present iff that policy is
   *  lifecycle-active (agent-policy-management §4.4). null → show "Attach";
   *  non-null → show "Detach" + "Update". The single source of truth for the
   *  Inventory actions and Agent Detail/Flow tabs. */
  active_policy_id?: string | null
  /** @deprecated vestigial String-Set; the scalar binding (active_policy_id) is
   *  authoritative. No longer written by attach/detach (T21/T47). */
  attached_policy_ids?: string[] | null
  /** Present when listed with `managed_only` (Agent Inventory, feature §8.1):
   *  "managed" + the most recent validate timestamp (data flowing). */
  lifecycle_status?: 'managed'
  last_active?: string | null
}

export interface AgentDetail extends AgentListItem {
  active_policy_id?: string | null
  /** @deprecated see AgentListItem.attached_policy_ids (T47). */
  attached_policy_ids?: string[] | null
  framework: string | null
  region: string | null
}

export interface AgentTool {
  name: string
  operation_type: string
  allowed: boolean
}

/* ----------------------------- Discovery ----------------------------- */

export interface DiscoverySummary {
  detected: number
  unmanaged: number
  new_24h: number
  providers_connected: number
  providers_total: number
  last_scan: string | null
}

export interface ProviderScan {
  cloud_provider: CloudProvider
  agents: number
  status: ScanStatus
  last_scan: string | null
}

export interface DiscoveredAgent {
  /** Dedupe-stable id = the source's native_resource_id (feature §8.1). */
  id: string
  /** Our registry agent_id once imported; null for not_imported (scan-only). */
  agent_id: string | null
  native_resource_id: string
  name: string
  cloud_provider: CloudProvider
  framework: string | null
  first_seen: string | null
  /** P0: provisional heuristic — label as such (§11.3). */
  risk: Risk
  /** not_imported → imported → managed (data flowing). */
  status: DiscoveryStatus
  /** Most recent /v1/validate timestamp; null until traffic seen (Managed). */
  last_active?: string | null
}

export interface ImportResult {
  discovery_id: string
  agent_id: string | null
  status: 'managed' | 'skipped' | 'failed'
  reason: string | null
}

export interface ImportResponse {
  imported: number
  agents: ImportResult[]
}

/* ----------------------------- Connections ----------------------------- */

/**
 * A connected cloud account (connections-api-spec §3). Secrets stay in a vault;
 * we hold a reference + the least-privilege scopes only (feature.md §6 / §10.3).
 */
export interface CloudConnection {
  id: string
  cloud_provider: CloudProvider
  status: ConnectionStatus
  /** Human account label/alias; null until known. */
  account_ref: string | null
  /** Minted by us; enforced in the role trust policy (confused-deputy guard). AWS only — null for Azure. */
  external_id: string | null
  /** The principal the customer trusts in their cross-account role. AWS only — null for Azure. */
  aegion_principal_arn: string | null
  /** Set by the operator after deploying the stack; null until then. AWS only. */
  role_arn: string | null
  /** Azure service-principal reference (set after attaching creds). Absent/null for AWS. */
  azure_subscription_id?: string | null
  azure_tenant_id?: string | null
  azure_client_id?: string | null
  /** Least-privilege read-only scopes the credential grants. */
  scopes: string[]
  /** From the last successful test/scan; null until tested. */
  agents_visible: number | null
  last_scan: string | null
  connected_at: string | null
  /** Human message when status=error, else null. */
  error: string | null
}

export interface CreateConnectionRequest {
  cloud_provider: CloudProvider
}

/** Result of `POST /v1/connections/{id}/test` — the AssumeRole probe (not an HTTP error on `ok:false`). */
export interface ConnectionTestResult {
  ok: boolean
  agents_visible: number | null
  message: string
}

/** Result of `POST /v1/connections/{id}/scan`. */
export interface ScanResult {
  scan_id: string
  status: ScanStatus
  discovered_count: number | null
}

/* ----------------------------- Policies / Sigma ----------------------------- */

/** Authoring/enforcement form of a policy (cedar-policy CT12/CT13b). `cedar`
 *  means a compiled Cedar co-artifact exists and is authoritative for evaluation;
 *  `yaml` is the legacy structured-only form. Absent ⇒ treat as `yaml`. */
export type PolicyFormat = 'yaml' | 'cedar'

export interface PolicySummary {
  policy_id: string
  name: string
  status: PolicyStatus
  version: number
  agent_count: number
  updated_at: string
  /** Authoring origin — present on the raw list passthrough. Used for the
   *  attach helper hint (§6.1) and `created_by` for the system-policy gating
   *  (§2.8). May be absent depending on the record. */
  agent_id?: string | null
  created_by?: string | null
  /** Migration-progress badge (cedar-policy CT13b). Absent ⇒ `yaml`. */
  policy_format?: PolicyFormat | null
}

/**
 * Raw policy content from `GET /v1/policies/{id}` (S3 passthrough). Typed as a
 * union because the live API does NOT guarantee a string — it can return a
 * structured object or null. Always normalize via `contentToString()` before
 * calling string methods (see policyFormat.ts). Previously typed `string`,
 * which let a non-string crash the CodeBlock viewer (`.split is not a function`).
 */
export type PolicyContent = string | Record<string, unknown> | null

export interface PolicyDetail extends PolicySummary {
  content: PolicyContent
  s3_key: string
}

/* ---- Sentra agent policy (the real `/v1/policies/{id}` content shape) ---- */

/** One inner rule in a Sentra agent policy (`content.policies[]`). */
export interface SentraPolicyRule {
  policy_id?: string
  name?: string
  description?: string
  rule?: string
  action?: string
  severity?: string
  enabled?: boolean
}

/** A cross-cloud precondition — the marquee enforcement (`content.cross_cloud_dependencies[]`). */
export interface CrossCloudDependency {
  target_agent?: string
  target_tool?: string
  required_before?: string[]
  max_age_seconds?: number
}

/**
 * Normalized view of `GET /v1/policies/{id}` for the detail page. The live response is
 * `{ policy: { metadata: {...}, content: {...} } }` — the summary fields live under `metadata`
 * and the actual policy under `content` (a Sentra agent policy, NOT Cedar). The api client
 * flattens both into this shape so the page never has to dig through the envelope.
 */
export interface PolicyDetailView {
  policy_id: string
  name: string
  status: PolicyStatus
  version: string
  agent_id: string | null
  platform: string | null
  cloud_region: string | null
  schema_version: string | null
  allowed_tools: string[]
  allowed_agents: string[]
  rules: SentraPolicyRule[]
  cross_cloud_dependencies: CrossCloudDependency[]
  max_calls_per_minute: number | null
  max_refund_amount: number | null
  /* metadata */
  created_by: string | null
  updated_at: string | null
  content_hash: string | null
  s3_key: string | null
  match_count_24h: number | null
  /* raw policy object for the YAML/JSON source viewer */
  content: unknown
  /** Enforcement form (cedar-policy CT12/CT13a). Absent ⇒ `yaml`. */
  policy_format: PolicyFormat
  /** Backend-generated, READ-ONLY compiled Cedar (cedar-policy CT12/CT13). Present
   *  when `policy_format==='cedar'`; the CEDAR source tab renders this verbatim
   *  rather than the client-side projection. Null ⇒ fall back to the projection. */
  cedar_content: string | null
  generator_version: string | null
}

/* ---- Policy create/update request shapes (what the backend expects) ---- */

/** One inner rule in a create/update request (`policies[]`). Mirrors the
 *  backend PolicyRule; `policy_id`, `name`, `severity` are the required core. */
export interface PolicyRuleRequest {
  policy_id: string
  name: string
  severity: string
  action?: string
  rule?: string
  description?: string
  enabled?: boolean
  [key: string]: unknown
}

/** Body for POST /v1/policies (create) — the structured document the backend
 *  validates (agent-policy-management §7). On UPDATE, `version` is OMITTED so the
 *  backend auto-increments (sending the prefilled value overwrites the same S3
 *  version and breaks audit/rollback — T31/K10). */
export interface PolicyCreateRequest {
  schema_version: 'v1'
  agent_id: string
  name: string
  version?: string
  allowed_tools: string[]
  policies: PolicyRuleRequest[]
  description?: string
  platform?: string
  cloud_region?: string
  allowed_agents?: string[]
  cross_cloud_dependencies?: CrossCloudDependency[]
  max_calls_per_minute?: number
}

export interface SigmaRule {
  rule_id: string
  title: string
  category: string
  severity: 'low' | 'medium' | 'high' | 'critical'
  status: SigmaStatus
  match_count: number
}

/** One detection selection within a Sigma rule (e.g. `instruction_override`). */
export interface SigmaRuleSelection {
  name: string
  /** Matched field + modifier, e.g. "prompt|contains". */
  field: string
  /** Literal substrings/patterns the rule matches on. */
  patterns: string[]
}

/** Full Sigma rule content for the detail view (`GET /v1/sigma-rules/{id}/content`). */
export interface SigmaRuleContent {
  rule_id: string
  title: string
  description: string
  level: string
  status: string
  tags: string[]
  condition: string | null
  selections: SigmaRuleSelection[]
  patterns_total: number
}

/* ----------------------------- Usage (WS-H, provisional) ----------------------------- */

/**
 * Metered usage rollup (`GET /v1/usage`, WS-H-owned — PROVISIONAL). Treat the
 * response as untrusted data and validate before rendering; until WS-H ships the
 * endpoint returns 404/501 and the UI renders a PARTIAL banner (never fabricated
 * totals). All fields optional so a partial rollup renders without crashing.
 */
export interface UsageRollup {
  period?: string
  validations?: number
  quota?: number
  blocks?: number
  agents?: number
}

/* --------------------- Platform (cross-tenant, M-G4) --------------------- */

/**
 * One tenant row from `GET /v1/platform/tenants` (`tenancy_routes.py:437`,
 * `require_platform`). The six metric fields are OPTIONAL (PRE-G4-a — not emitted
 * until the per-tenant rollup lands); treat every field as untrusted and guard
 * before render (deny_rate/trust may be absent/NaN/out of range). Identity mode is
 * canonical `enforce`/`shadow`/`off` — never "monitor".
 */
export interface PlatformTenantRow {
  tenant_id: string
  display_name: string
  plan: string
  status: string
  identity_mode: string
  created_at: string
  /** Whether this tenant has granted platform-read consent (drill-down gating).
   *  Projected onto the list row by the backend (ws-g-fix-backend FXB-1.2); optional
   *  only to stay compatible with a pre-FXB-1.2 controller (ConsentPill → "unknown"). */
  platform_read_consent?: boolean
  blocks_24h?: number
  deny_rate?: number
  trust?: number
  agents?: number
  quarantined?: number
  decisions_24h?: number
}

export interface PlatformTenantsResponse {
  count: number
  tenants: PlatformTenantRow[]
  /** Present only once server paging lands (PRE-G4-b); absent ⇒ full unpaged set. */
  cursor?: string
}

export interface PlatformMemberRow {
  operator_sub: string
  role: string
}

/** `GET /v1/platform/tenants/{id}` (`tenancy_routes.py:454`, `require_platform`). */
export interface PlatformTenantDetail {
  tenant_id: string
  display_name: string
  status: string
  plan: string
  identity_mode: string
  /** Loose quota bag — narrow the specific key you read (never assume presence). */
  quota: Record<string, unknown>
  platform_read_consent: boolean
  members: PlatformMemberRow[]
  /** Optional 24h usage for the FX-3.6 quota-headroom readout (absent ⇒ headroom
   *  shows "unknown"). */
  decisions_24h?: number
}
