import * as fx from './fixtures'
import type { CloudConnection } from '../types/api'

export interface MockResponse {
  status: number
  body: unknown
}

/**
 * In-memory connection store so the Connect Account wizard behaves statefully
 * across calls within a dev session (create → set role → test → scan). Seeded
 * from fixtures; lives for the lifetime of the lazily-imported mock module.
 */
const connStore = new Map<string, CloudConnection>(fx.connections.map((c) => [c.id, { ...c }]))
let connSeq = connStore.size

function nowIso(): string {
  return new Date().toISOString()
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
    // Scalar binding (agent-policy-management T47): active_policy_id comes from
    // the fixture; the vestigial attached_policy_ids Set is gone.
    return { status: 200, body: { ...agent, framework: 'LangChain', region: 'us-east-1' } }
  }
  // Attach / detach the scalar binding (T21).
  if (m === 'POST' && /^\/agents\/[^/]+\/policies$/.test(path)) {
    const agentId = decodeURIComponent(path.split('/')[2])
    const policyId = (body as { policy_id?: string })?.policy_id ?? ''
    return { status: 200, body: { agent_id: agentId, policy_id: policyId, status: 'attached', attached_at: new Date().toISOString() } }
  }
  if (m === 'DELETE' && /^\/agents\/[^/]+\/policies\/[^/]+$/.test(path)) {
    const parts = path.split('/')
    return { status: 200, body: { agent_id: decodeURIComponent(parts[2]), policy_id: decodeURIComponent(parts[4]), status: 'detached' } }
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

  // --- Connections (powers Connect Account wizard) ---
  if (get && path === '/connections') {
    return { status: 200, body: { connections: [...connStore.values()] } }
  }
  if (m === 'POST' && path === '/connections') {
    const cloud = (body as { cloud_provider?: string })?.cloud_provider ?? 'aws'
    if (cloud !== 'aws' && cloud !== 'azure') {
      return { status: 409, body: { error: `${cloud} connections are not available yet`, error_code: 'PROVIDER_NOT_AVAILABLE' } }
    }
    connSeq += 1
    const isAzure = cloud === 'azure'
    const id = `conn-${cloud}-${connSeq}`
    const conn: CloudConnection = {
      id,
      cloud_provider: isAzure ? 'azure' : 'aws',
      status: 'connecting',
      account_ref: null,
      // Azure trusts the SP instead of a confused-deputy external id.
      external_id: isAzure ? null : `ext-${Math.random().toString(16).slice(2, 8)}`,
      aegion_principal_arn: isAzure ? null : fx.AEGION_PRINCIPAL_ARN,
      role_arn: null,
      azure_subscription_id: null,
      azure_tenant_id: null,
      azure_client_id: null,
      scopes: isAzure
        ? ['Microsoft.CognitiveServices/accounts/read', 'Microsoft.CognitiveServices/accounts/deployments/read']
        : fx.AWS_DISCOVERY_SCOPES,
      agents_visible: null,
      last_scan: null,
      connected_at: null,
      error: null,
    }
    connStore.set(id, conn)
    return { status: 201, body: conn }
  }
  if (get && /^\/connections\/[^/]+$/.test(path)) {
    const conn = connStore.get(decodeURIComponent(path.split('/')[2]))
    if (!conn) return { status: 404, body: { error: 'connection not found', error_code: 'NOT_FOUND' } }
    return { status: 200, body: conn }
  }
  if (m === 'PUT' && /^\/connections\/[^/]+$/.test(path)) {
    const conn = connStore.get(decodeURIComponent(path.split('/')[2]))
    if (!conn) return { status: 404, body: { error: 'connection not found', error_code: 'NOT_FOUND' } }
    const azure = (body as { azure?: Record<string, string> })?.azure
    if (azure) {
      conn.azure_subscription_id = azure.subscription_id ?? conn.azure_subscription_id
      conn.azure_tenant_id = azure.tenant_id ?? conn.azure_tenant_id
      conn.azure_client_id = azure.client_id ?? conn.azure_client_id
      conn.account_ref = azure.subscription_id ?? conn.account_ref
    } else {
      conn.role_arn = (body as { role_arn?: string })?.role_arn ?? conn.role_arn
    }
    return { status: 200, body: conn }
  }
  if (m === 'POST' && /^\/connections\/[^/]+\/test$/.test(path)) {
    const conn = connStore.get(decodeURIComponent(path.split('/')[2]))
    if (!conn) return { status: 404, body: { error: 'connection not found', error_code: 'NOT_FOUND' } }
    if (conn.cloud_provider === 'azure') {
      // Connected once the SP reference is attached; a client id containing
      // "fail" simulates a rejecting / under-scoped service principal.
      const attached = Boolean(conn.azure_client_id)
      const ok = attached && !/fail/i.test(conn.azure_client_id ?? '')
      if (ok) {
        conn.status = 'connected'
        conn.agents_visible = 9
        conn.connected_at = nowIso()
        conn.error = null
        return { status: 200, body: { ok: true, agents_visible: 9, message: 'Service principal OK · 9 agents visible' } }
      }
      const message = attached ? 'AuthorizationFailed: service principal lacks Reader' : 'No service principal attached'
      conn.status = 'error'
      conn.error = message
      return { status: 200, body: { ok: false, agents_visible: null, message } }
    }
    const roleArn = (body as { role_arn?: string })?.role_arn
    if (roleArn) conn.role_arn = roleArn
    // A role ARN containing "fail" simulates a rejecting trust policy.
    const ok = Boolean(conn.role_arn) && !/fail/i.test(conn.role_arn ?? '')
    if (ok) {
      conn.status = 'connected'
      conn.agents_visible = 14
      conn.connected_at = nowIso()
      conn.account_ref = conn.account_ref ?? 'global-prod-01'
      conn.error = null
      return { status: 200, body: { ok: true, agents_visible: 14, message: 'AssumeRole OK · 14 agents visible' } }
    }
    conn.status = 'error'
    conn.error = 'AccessDenied: external id mismatch'
    return { status: 200, body: { ok: false, agents_visible: null, message: 'AccessDenied: external id mismatch' } }
  }
  if (m === 'POST' && /^\/connections\/[^/]+\/scan$/.test(path)) {
    const conn = connStore.get(decodeURIComponent(path.split('/')[2]))
    if (!conn) return { status: 404, body: { error: 'connection not found', error_code: 'NOT_FOUND' } }
    if (conn.status !== 'connected') {
      return { status: 409, body: { error: 'connection is not connected', error_code: 'NOT_CONNECTED' } }
    }
    conn.last_scan = nowIso()
    return { status: 202, body: { scan_id: `scan-${Math.random().toString(16).slice(2, 6)}`, status: 'scanning', discovered_count: null } }
  }
  if (m === 'DELETE' && /^\/connections\/[^/]+$/.test(path)) {
    connStore.delete(decodeURIComponent(path.split('/')[2]))
    return { status: 204, body: undefined }
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
    // cedar-policy CT13b: mirror the live `{ policy: { metadata, content } }`
    // envelope so the client maps policy_format + the Cedar body correctly.
    const fmt = summary.policy_format ?? 'yaml'
    return {
      status: 200,
      body: {
        policy: {
          metadata: { ...summary, policy_format: fmt, s3_key: `policies/${id}/v${summary.version}.yaml` },
          content: fx.policyContents[id] ?? '',
        },
      },
    }
  }
  // Policy lifecycle writes (agent-policy-management T34).
  if (m === 'POST' && path === '/policies') {
    const b = (body as { agent_id?: string; name?: string; version?: string }) ?? {}
    const newId = `pol-${Math.floor(Math.random() * 9000 + 1000)}`
    return { status: 201, body: { policy_id: newId, version: b.version ?? '1.0.0', s3_key: `policies/${b.agent_id}/${newId}.yaml` } }
  }
  if (m === 'PATCH' && /^\/policies\/[^/]+\/status$/.test(path)) {
    const id = decodeURIComponent(path.split('/')[2])
    const status = (body as { status?: string })?.status ?? 'active'
    return { status: 200, body: { success: true, policy_id: id, status, updated_at: new Date().toISOString() } }
  }
  if (m === 'PUT' && /^\/policies\/[^/]+$/.test(path)) {
    const id = decodeURIComponent(path.split('/')[2])
    return { status: 200, body: { success: true, policy_id: id, version: '1.0.1' } }
  }
  if (m === 'DELETE' && /^\/policies\/[^/]+$/.test(path)) {
    const id = decodeURIComponent(path.split('/')[2])
    return { status: 200, body: { success: true, policy_id: id, status: 'disabled', disabled_at: new Date().toISOString() } }
  }
  if (get && path === '/sigma-rules') {
    return { status: 200, body: { rules: fx.sigmaRules, total: fx.sigmaRules.length, next_token: null } }
  }
  if (get && /^\/sigma-rules\/[^/]+\/content$/.test(path)) {
    const id = decodeURIComponent(path.split('/')[2])
    const rule = fx.sigmaRules.find((r) => r.rule_id === id)
    return {
      status: 200,
      body: {
        rule_id: id,
        title: rule?.title ?? id,
        description: 'Detects prompt-injection / jailbreak attempts in agent inputs.',
        level: rule?.severity ?? 'medium',
        status: rule?.status ?? 'enabled',
        tags: ['llm.prompt_injection', 'attack.initial_access'],
        condition: '1 of them',
        selections: [
          {
            name: 'instruction_override',
            field: 'prompt|contains',
            patterns: ['ignore previous instructions', 'disregard previous', 'forget previous instructions'],
          },
          {
            name: 'role_manipulation',
            field: 'prompt|contains',
            patterns: ['you are now', 'act as if you are', 'pretend you are'],
          },
        ],
        patterns_total: 6,
      },
    }
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
