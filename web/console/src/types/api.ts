/**
 * DTOs from LLD-21 §6 / §11. Nullable fields follow §11.2 explicitly:
 * never assume non-null (e.g. `trust_score` is null on an empty fleet).
 */
import type {
  AgentStatus,
  CloudProvider,
  Decision,
  DiscoveryStatus,
  MetricsRange,
  Platform,
  PolicyStatus,
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
  operator_id: string
}

export interface VerdictResult {
  decision_id: string
  verdict: Verdict
  verdict_at: string
}

export interface QuarantineRequest {
  reason: string
  operator_id: string
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
}

export interface AgentDetail extends AgentListItem {
  attached_policy_ids: string[]
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
  id: string
  name: string
  cloud_provider: CloudProvider
  framework: string | null
  first_seen: string
  /** P0: provisional heuristic — label as such (§11.3). */
  risk: Risk
  status: DiscoveryStatus
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

/* ----------------------------- Policies / Sigma ----------------------------- */

export interface PolicySummary {
  policy_id: string
  name: string
  status: PolicyStatus
  version: number
  agent_count: number
  updated_at: string
}

export interface PolicyDetail extends PolicySummary {
  content: string
  s3_key: string
}

export interface SigmaRule {
  rule_id: string
  title: string
  category: string
  severity: 'low' | 'medium' | 'high' | 'critical'
  status: SigmaStatus
  match_count: number
}
