import type {
  AgentListItem,
  CloudConnection,
  DecisionItem,
  DiscoveredAgent,
  DiscoverySummary,
  MetricsOverview,
  PlatformDistribution,
  PolicySummary,
  ProviderScan,
  ResidualAgent,
  SessionInfo,
  SigmaRule,
  TimeseriesPoint,
} from '../types/api'
import type { CloudProvider, Decision, ThreatType } from '../types/enums'

export const overview: MetricsOverview = {
  range: '24h',
  threats_blocked: 4827,
  threats_blocked_delta_pct: 12.0,
  attack_categories: 9,
  active_agents: 142,
  clouds: 3,
  trust_score: 87,
  trust_status: 'healthy',
  agents_below_threshold: 3,
  requests_total: 1_200_000,
  avg_latency_ms: 12,
  quarantined: 3,
  false_positive_pct: null, // P0: hidden
}

export const platformDistribution: PlatformDistribution = {
  total_nodes: 142,
  providers: [
    { cloud_provider: 'aws', label: 'AWS EC2 Clusters', count: 68, pct: 48 },
    { cloud_provider: 'gcp', label: 'GCP Core Project', count: 44, pct: 31 },
    { cloud_provider: 'azure', label: 'Azure North Region', count: 30, pct: 21 },
  ],
}

export function makeTimeseries(): TimeseriesPoint[] {
  const allowed = [820, 910, 760, 1180, 1320, 1610, 1740, 1690, 1880, 2010, 1760, 1920]
  const blocked = [120, 180, 90, 260, 210, 380, 440, 360, 520, 470, 610, 540]
  const base = new Date('2026-06-06T00:00:00Z').getTime()
  return allowed.map((a, i) => ({
    t: new Date(base + i * 2 * 3600_000).toISOString(),
    allowed: a,
    blocked: blocked[i],
  }))
}

/* --------------------------------------------------------------------------
 * Decisions feed — also powers the Topology flow map and per-agent Flow tab,
 * so it spans several agents/tools with an allow/deny mix to make the Sankey
 * (and its heat path) meaningful.
 * ------------------------------------------------------------------------ */
interface AgentSeed {
  id: string
  name: string
  cloud: CloudProvider
  session: string
}
const AGENT_SEEDS: Record<'fin' | 'sup' | 'exp' | 'hr', AgentSeed> = {
  fin: { id: 'agt-7781', name: 'finance-reconciler-prod', cloud: 'aws', session: 'sess-9001' },
  sup: { id: 'agt-5521', name: 'support-triage-gcp', cloud: 'gcp', session: 'sess-9002' },
  exp: { id: 'agt-3310', name: 'data-export-prod', cloud: 'aws', session: 'sess-9003' },
  hr: { id: 'agt-8890', name: 'hr-bot-azure', cloud: 'azure', session: 'sess-9004' },
}

let decSeq = 0
function dec(
  who: keyof typeof AGENT_SEEDS,
  tool: string,
  decision: Decision,
  threat: ThreatType | null,
  trust: number,
): DecisionItem {
  const s = AGENT_SEEDS[who]
  decSeq += 1
  return {
    decision_id: `${s.session}:req-${decSeq}`,
    session_id: s.session,
    request_id: `req-${decSeq}`,
    agent_id: s.id,
    agent_name: s.name,
    cloud_provider: s.cloud,
    platform: 'sentra',
    decision,
    threat_type: threat,
    tool_name: tool,
    reason: decision === 'DENY' ? `Blocked ${tool}` : `Allowed ${tool}`,
    trust_score: trust,
    timestamp: new Date(Date.UTC(2026, 5, 6, 4, 19, Math.max(1, 58 - decSeq))).toISOString(),
  }
}

export const decisions: DecisionItem[] = [
  dec('fin', 'stripe.write', 'DENY', 'PROMPT_INJECTION', 41),
  dec('fin', 'stripe.write', 'DENY', 'POLICY_VIOLATION', 43),
  dec('fin', 'postgres.query', 'ALLOW', null, 68),
  dec('fin', 'postgres.query', 'ALLOW', null, 70),
  dec('fin', 's3.read', 'ALLOW', null, 66),
  dec('fin', 'secretsmanager.get', 'DENY', 'POLICY_VIOLATION', 58),
  dec('sup', 'bigquery.read', 'ALLOW', null, 92),
  dec('sup', 'bigquery.read', 'ALLOW', null, 91),
  dec('sup', 'bigquery.read', 'ALLOW', null, 90),
  dec('sup', 'gmail.send', 'ALLOW', null, 89),
  dec('sup', 'pubsub.publish', 'ALLOW', null, 88),
  dec('sup', 'bigquery.read', 'DENY', 'DATA_EXFILTRATION', 60),
  dec('exp', 's3.read', 'DENY', 'PII_LEAK', 55),
  dec('exp', 's3.read', 'DENY', 'PII_LEAK', 52),
  dec('exp', 's3.write', 'DENY', 'POLICY_VIOLATION', 50),
  dec('hr', 'postgres.query', 'ALLOW', null, 88),
  dec('hr', 'blob.read', 'ALLOW', null, 86),
  dec('hr', 'graph.read', 'ALLOW', null, 84),
]

/** Runtime sessions (GET /v1/sessions). `sess-9001` is currently quarantined —
 *  it maps to the blocked `finance-reconciler-prod` decisions. */
export const sessions: SessionInfo[] = [
  {
    session_id: 'sess-9001',
    user_id: 'svc-finance',
    agent_id: 'agt-7781',
    trust_score: 41,
    quarantine_status: 'quarantined',
    total_requests: 214,
    allow_count: 180,
    deny_count: 34,
    consecutive_allows: 0,
    created_at: '2026-06-06T03:40:00Z',
    last_activity: '2026-06-06T04:19:58Z',
  },
]

export const agents: AgentListItem[] = [
  {
    agent_id: 'agt-7781',
    name: 'finance-reconciler-prod',
    platform: 'sentra',
    cloud_provider: 'aws',
    status: 'active',
    trust_score_avg: 41,
    requests_total: 18230,
    requests_allowed: 17120,
    requests_denied: 1110,
    active_sessions: 4,
    last_seen: '2026-06-06T04:19:58Z',
    active_policy_id: 'pol-101', // bound → Inventory shows Detach + Update
  },
  {
    agent_id: 'agt-5521',
    name: 'support-triage-gcp',
    platform: 'sentra',
    cloud_provider: 'gcp',
    status: 'active',
    trust_score_avg: 92,
    requests_total: 44120,
    requests_allowed: 43980,
    requests_denied: 140,
    active_sessions: 11,
    last_seen: '2026-06-06T04:19:55Z',
    active_policy_id: 'pol-102',
  },
  {
    agent_id: 'agt-8890',
    name: 'hr-bot-azure',
    platform: 'bedrock',
    cloud_provider: 'azure',
    status: 'idle',
    trust_score_avg: 88,
    requests_total: 9021,
    requests_allowed: 8990,
    requests_denied: 31,
    active_sessions: 0,
    last_seen: '2026-06-06T04:10:11Z',
    active_policy_id: null, // unbound → Inventory shows Attach
  },
]

export const discoverySummary: DiscoverySummary = {
  detected: 148,
  unmanaged: 37,
  new_24h: 12,
  providers_connected: 3,
  providers_total: 3,
  last_scan: '2026-06-06T04:19:12Z',
}

export const discoveryPlatforms: ProviderScan[] = [
  { cloud_provider: 'aws', agents: 72, status: 'scanning', last_scan: '2026-06-06T04:19:12Z' },
  { cloud_provider: 'gcp', agents: 51, status: 'idle', last_scan: '2026-06-06T03:51:00Z' },
  { cloud_provider: 'azure', agents: 25, status: 'scanning', last_scan: '2026-06-06T04:18:40Z' },
]

export const discoveredAgents: DiscoveredAgent[] = [
  // not_imported: visible in the cloud scan, no registry row yet.
  { id: 'JGECQEHF9N', agent_id: null, native_resource_id: 'JGECQEHF9N', name: 'payments-router-prod', cloud_provider: 'aws', framework: 'LangChain', first_seen: '2026-06-06T02:19:00Z', risk: 'high', status: 'not_imported', last_active: null },
  // managed: imported AND validate traffic flowing.
  { id: 'arn-analytics', agent_id: 'analytics-summarizer', native_resource_id: 'arn-analytics', name: 'analytics-summarizer', cloud_provider: 'aws', framework: 'LlamaIndex', first_seen: '2026-06-05T04:19:00Z', risk: 'low', status: 'managed', last_active: '2026-06-11T11:58:00Z' },
  // imported: registry row exists, no traffic yet (SDK not wired).
  { id: 'arn-notify', agent_id: 'notify-worker-gcp', native_resource_id: 'arn-notify', name: 'notify-worker-gcp', cloud_provider: 'gcp', framework: null, first_seen: '2026-06-06T01:02:00Z', risk: 'med', status: 'imported', last_active: null },
]

/** The principal the customer trusts in their cross-account role (connections-api-spec §3). */
export const AEGION_PRINCIPAL_ARN = 'arn:aws:iam::531109575379:root'

/** Read-only, least-privilege scopes seeded onto a new AWS connection. */
export const AWS_DISCOVERY_SCOPES = ['bedrock-agent:List*', 'bedrock-agent:Get*', 'lambda:GetFunction']

export const connections: CloudConnection[] = [
  {
    id: 'conn-aws-acme',
    cloud_provider: 'aws',
    status: 'connected',
    account_ref: 'global-prod-01',
    external_id: 'ext-acme-9f3c2a',
    aegion_principal_arn: AEGION_PRINCIPAL_ARN,
    role_arn: 'arn:aws:iam::531109575379:role/AegionDiscoveryRole',
    scopes: AWS_DISCOVERY_SCOPES,
    agents_visible: 14,
    last_scan: '2026-06-10T18:31:00Z',
    connected_at: '2026-06-10T18:22:00Z',
    error: null,
  },
]

export const policies: PolicySummary[] = [
  { policy_id: 'pol-101', name: 'baseline-guardrails', status: 'active', version: 4, agent_count: 38, updated_at: '2026-06-05T22:10:00Z', policy_format: 'cedar' },
  { policy_id: 'pol-102', name: 'pii-redaction', status: 'active', version: 2, agent_count: 21, updated_at: '2026-06-05T18:40:00Z', policy_format: 'cedar' },
  { policy_id: 'pol-103', name: 'refund-limits', status: 'draft', version: 1, agent_count: 0, updated_at: '2026-06-06T03:01:00Z', policy_format: 'yaml' },
]

/** Cedar source per policy_id, returned by GET /policies/:id with include_content. */
export const policyContents: Record<string, string> = {
  'pol-101': `// @name: baseline-guardrails
// @id: pol-101
permit (
  principal in Group::"all-agents",
  action in [
    Action::"read:Postgres-fin",
    Action::"read:S3-reports"
  ],
  resource in Resource::"fin-ledger-db"
)
when {
  context.mfa == true &&
  resource.region == "us-east-1"
};`,
  'pol-102': `// @name: pii-redaction
// @id: pol-102
forbid (
  principal,
  action in [Action::"write:Logs"],
  resource
)
when {
  context.contains_pii == true
};`,
  'pol-103': `// @name: refund-limits
// @id: pol-103
forbid (
  principal in Group::"finance-team",
  action == Action::"charge:Stripe",
  resource
)
when {
  context.amount > 10000
};`,
}

export const sigmaRules: SigmaRule[] = [
  { rule_id: 'sig-001', title: 'Prompt injection — instruction override', category: 'injection', severity: 'high', status: 'enabled', match_count: 312 },
  { rule_id: 'sig-002', title: 'Jailbreak — role play bypass', category: 'jailbreak', severity: 'critical', status: 'enabled', match_count: 88 },
  { rule_id: 'sig-003', title: 'PII exfiltration via tool params', category: 'exfiltration', severity: 'high', status: 'disabled', match_count: 0 },
]

// Residual uncredentialed agents on the WS-B B1 fallback window (WS-C C2): one
// still inside its window (active), one past its deadline (expired → denied).
export const residualAgents: ResidualAgent[] = [
  {
    agent_id: 'agt-7781',
    tenant_id: 't_acme',
    first_seen_ms: Date.now() - 3_600_000, // seen 1h ago
    deadline_ms: Date.now() + 86_400_000, // ~24h left
    expired: false,
  },
  {
    agent_id: 'agt-legacy-9043',
    tenant_id: 't_acme',
    first_seen_ms: Date.now() - 700_000_000,
    deadline_ms: Date.now() - 3_600_000, // lapsed 1h ago
    expired: true,
  },
]
