import type {
  AgentListItem,
  DecisionItem,
  DiscoveredAgent,
  DiscoverySummary,
  MetricsOverview,
  PlatformDistribution,
  PolicySummary,
  ProviderScan,
  SigmaRule,
  TimeseriesPoint,
} from '../types/api'

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

export const decisions: DecisionItem[] = [
  {
    decision_id: 'sess-9001:req-1',
    session_id: 'sess-9001',
    request_id: 'req-1',
    agent_id: 'agt-7781',
    agent_name: 'finance-reconciler-prod',
    cloud_provider: 'aws',
    platform: 'sentra',
    decision: 'DENY',
    threat_type: 'PROMPT_INJECTION',
    tool_name: 'stripe.write',
    reason: 'Blocked write to Stripe API · injection',
    trust_score: 41,
    timestamp: '2026-06-06T04:19:58Z',
  },
  {
    decision_id: 'sess-9002:req-3',
    session_id: 'sess-9002',
    request_id: 'req-3',
    agent_id: 'agt-5521',
    agent_name: 'support-triage-gcp',
    cloud_provider: 'gcp',
    platform: 'sentra',
    decision: 'ALLOW',
    threat_type: null,
    tool_name: 'bigquery.read',
    reason: 'Allowed read BigQuery · verified',
    trust_score: 92,
    timestamp: '2026-06-06T04:19:55Z',
  },
  {
    decision_id: 'sess-9003:req-2',
    session_id: 'sess-9003',
    request_id: 'req-2',
    agent_id: 'agt-3310',
    agent_name: 'data-export-prod',
    cloud_provider: 'aws',
    platform: 'bedrock',
    decision: 'DENY',
    threat_type: 'PII_LEAK',
    tool_name: 's3.read',
    reason: 'Blocked read S3 · PII denied',
    trust_score: 55,
    timestamp: '2026-06-06T04:19:46Z',
  },
  {
    decision_id: 'sess-9004:req-7',
    session_id: 'sess-9004',
    request_id: 'req-7',
    agent_id: 'agt-8890',
    agent_name: 'hr-bot-azure',
    cloud_provider: 'azure',
    platform: 'sentra',
    decision: 'ALLOW',
    threat_type: null,
    tool_name: 'postgres.query',
    reason: 'Allowed query Postgres · auth OK',
    trust_score: 88,
    timestamp: '2026-06-06T04:19:42Z',
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
  { id: 'disc-001', name: 'payments-router-prod', cloud_provider: 'aws', framework: 'LangChain', first_seen: '2026-06-06T02:19:00Z', risk: 'high', status: 'unmanaged' },
  { id: 'disc-004', name: 'analytics-summarizer', cloud_provider: 'aws', framework: 'LlamaIndex', first_seen: '2026-06-05T04:19:00Z', risk: 'low', status: 'managed' },
  { id: 'disc-009', name: 'notify-worker-gcp', cloud_provider: 'gcp', framework: null, first_seen: '2026-06-06T01:02:00Z', risk: 'med', status: 'unmanaged' },
]

export const policies: PolicySummary[] = [
  { policy_id: 'pol-101', name: 'baseline-guardrails', status: 'active', version: 4, agent_count: 38, updated_at: '2026-06-05T22:10:00Z' },
  { policy_id: 'pol-102', name: 'pii-redaction', status: 'active', version: 2, agent_count: 21, updated_at: '2026-06-05T18:40:00Z' },
  { policy_id: 'pol-103', name: 'refund-limits', status: 'draft', version: 1, agent_count: 0, updated_at: '2026-06-06T03:01:00Z' },
]

export const sigmaRules: SigmaRule[] = [
  { rule_id: 'sig-001', title: 'Prompt injection — instruction override', category: 'injection', severity: 'high', status: 'enabled', match_count: 312 },
  { rule_id: 'sig-002', title: 'Jailbreak — role play bypass', category: 'jailbreak', severity: 'critical', status: 'enabled', match_count: 88 },
  { rule_id: 'sig-003', title: 'PII exfiltration via tool params', category: 'exfiltration', severity: 'high', status: 'disabled', match_count: 0 },
]
