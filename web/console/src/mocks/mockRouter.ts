import * as fx from './fixtures'

export interface MockResponse {
  status: number
  body: unknown
}

/**
 * Code-level mock router (no service worker) — mirrors LLD-21 response shapes.
 * Used by `http.ts` only when VITE_DATA_SOURCE=mock; dynamically imported so it
 * is dropped from the production bundle.
 */
export function resolveMock(
  method: string,
  path: string,
  search: URLSearchParams,
  body?: unknown,
): MockResponse | null {
  const m = method.toUpperCase()
  const get = m === 'GET'

  // --- Metrics ---
  if (get && path === '/metrics/overview') {
    return { status: 200, body: { ...fx.overview, range: search.get('range') ?? '24h' } }
  }
  if (get && path === '/metrics/platform-distribution') {
    return { status: 200, body: fx.platformDistribution }
  }
  if (get && path === '/metrics/decisions-timeseries') {
    const range = search.get('range') ?? '24h'
    const bucket = search.get('bucket') ?? '1h'
    if (range === '30d' && bucket === '1h') {
      return {
        status: 400,
        body: { error: 'range=30d with bucket=1h exceeds 200 points', error_code: 'VALIDATION_ERROR', request_id: 'mock' },
      }
    }
    return { status: 200, body: { range, bucket, series: fx.makeTimeseries() } }
  }

  // --- Decisions ---
  if (get && path === '/decisions') {
    const decision = search.get('decision')
    const agentId = search.get('agent_id')
    const sessionId = search.get('session_id')
    let items = fx.decisions
    if (decision) items = items.filter((d) => d.decision === decision)
    if (agentId) items = items.filter((d) => d.agent_id === agentId)
    if (sessionId) items = items.filter((d) => d.session_id === sessionId)
    const limit = Number(search.get('limit') ?? 0)
    const sliced = limit > 0 ? items.slice(0, limit) : items
    return { status: 200, body: { decisions: sliced, total: items.length, next_token: null } }
  }
  if (m === 'POST' && /^\/quarantine\/.+/.test(path)) {
    return { status: 200, body: { success: true, new_status: 'quarantined' } }
  }
  if (m === 'DELETE' && /^\/quarantine\/.+/.test(path)) {
    const sessionId = decodeURIComponent(path.split('/')[2])
    return { status: 200, body: { success: true, session_id: sessionId, new_status: 'active', previous_status: 'quarantined' } }
  }

  // --- Sessions ---
  if (get && path === '/sessions') {
    const status = search.get('status')
    const items = status ? fx.sessions.filter((s) => s.quarantine_status === status) : fx.sessions
    return { status: 200, body: { sessions: items, total: items.length } }
  }
  if (m === 'POST' && /^\/decisions\/.+\/verdict$/.test(path)) {
    return {
      status: 200,
      body: {
        decision_id: decodeURIComponent(path.split('/')[2]),
        verdict: (body as { verdict?: string })?.verdict ?? 'false_positive',
        verdict_at: new Date().toISOString(),
      },
    }
  }

  // --- Agents ---
  if (get && path === '/agents') {
    return { status: 200, body: { agents: fx.agents, total: fx.agents.length } }
  }
  if (get && /^\/agents\/[^/]+$/.test(path)) {
    const id = decodeURIComponent(path.split('/')[2])
    const agent = fx.agents.find((a) => a.agent_id === id)
    if (!agent) return { status: 404, body: { error: 'agent not found', error_code: 'NOT_FOUND' } }
    return { status: 200, body: { ...agent, attached_policy_ids: ['pol-101'], framework: 'LangChain', region: 'us-east-1' } }
  }
  if (get && /^\/agents\/[^/]+\/tools$/.test(path)) {
    return {
      status: 200,
      body: {
        tools: [
          { name: 'stripe.write', operation_type: 'WRITE', allowed: false },
          { name: 'postgres.query', operation_type: 'READ', allowed: true },
        ],
        total: 2,
      },
    }
  }

  // --- Discovery (powers Import Agents onboarding) ---
  if (get && path === '/discovery/summary') return { status: 200, body: fx.discoverySummary }
  if (get && path === '/discovery/platforms') return { status: 200, body: { providers: fx.discoveryPlatforms } }
  if (get && path === '/discovery/agents') {
    return { status: 200, body: { agents: fx.discoveredAgents, total: fx.discoveredAgents.length, next_token: null } }
  }
  if (m === 'POST' && path === '/discovery/import') {
    const ids = (body as { agent_ids?: string[] })?.agent_ids ?? []
    return {
      status: 201,
      body: { imported: ids.length, agents: ids.map((id) => ({ discovery_id: id, agent_id: `agt-${id}`, status: 'managed', reason: null })) },
    }
  }

  // --- Policies / Sigma ---
  if (get && path === '/policies') {
    return { status: 200, body: { policies: fx.policies, total: fx.policies.length, next_token: null } }
  }
  if (get && /^\/policies\/[^/]+$/.test(path)) {
    const id = decodeURIComponent(path.split('/')[2])
    const summary = fx.policies.find((p) => p.policy_id === id)
    if (!summary) return { status: 404, body: { error: 'policy not found', error_code: 'NOT_FOUND' } }
    return {
      status: 200,
      body: {
        policy: {
          ...summary,
          content: fx.policyContents[id] ?? '',
          s3_key: `policies/${id}/v${summary.version}.cedar`,
        },
      },
    }
  }
  if (get && path === '/sigma-rules') {
    return { status: 200, body: { rules: fx.sigmaRules, total: fx.sigmaRules.length, next_token: null } }
  }
  if (m === 'PATCH' && /^\/sigma-rules\/.+/.test(path)) {
    return { status: 200, body: { success: true, rule_id: decodeURIComponent(path.split('/')[2]), status: (body as { status?: string })?.status ?? 'enabled' } }
  }

  // --- Logs ---
  if (get && path === '/logs') {
    return {
      status: 200,
      body: {
        logs: fx.decisions.map((d) => ({
          id: d.decision_id,
          timestamp: d.timestamp,
          session_id: d.session_id,
          agent_id: d.agent_id,
          decision: d.decision,
          threat_type: d.threat_type,
          message: d.reason ?? '',
        })),
        total: fx.decisions.length,
        next_token: null,
      },
    }
  }

  return null
}
