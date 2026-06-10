import { http } from '../http'
import type { PolicyStatus } from '../../types/enums'
import type {
  CrossCloudDependency,
  Page,
  PolicyDetailView,
  PolicySummary,
  SentraPolicyRule,
  SigmaRule,
} from '../../types/api'

const toNum = (v: unknown): number | null => {
  const n = Number(v)
  return Number.isFinite(n) ? n : null
}
const asArr = <T,>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : [])

export interface PoliciesFilters {
  agent_id?: string
  status?: PolicyStatus
  limit?: number
  cursor?: string
}

interface PoliciesResponse {
  policies: PolicySummary[]
  total: number
  next_token: string | null
}

interface SigmaRulesResponse {
  rules: SigmaRule[]
  total: number
  next_token: string | null
}

export const policiesApi = {
  list: async (filters: PoliciesFilters): Promise<Page<PolicySummary>> => {
    const res = await http.get<PoliciesResponse>('/policies', { ...filters })
    return { items: res.policies, total: res.total, next_token: res.next_token }
  },

  /** Normalize the `{ policy: { metadata, content } }` envelope into a flat, page-ready view.
   *  The summary fields live under `metadata`; the policy itself (Sentra agent policy) under
   *  `content`. */
  detail: async (policyId: string): Promise<PolicyDetailView> => {
    const res = await http.get<{ policy?: { metadata?: Record<string, unknown>; content?: unknown } }>(
      `/policies/${encodeURIComponent(policyId)}`,
      { include_content: true },
    )
    const p = res.policy ?? {}
    const m = (p.metadata ?? {}) as Record<string, unknown>
    const c = (p.content && typeof p.content === 'object' ? p.content : {}) as Record<string, unknown>
    const pick = (...vals: unknown[]) => vals.find((v) => v !== undefined && v !== null) ?? null
    return {
      policy_id: String(pick(m.policy_id, c.policy_id, policyId)),
      name: String(pick(m.name, c.name, policyId)),
      status: (pick(m.status, c.status, 'active') as PolicyStatus),
      version: String(pick(m.version, c.version, '') ?? ''),
      agent_id: (pick(m.agent_id, c.agent_id) as string | null),
      platform: (pick(c.platform) as string | null),
      cloud_region: (pick(c.cloud_region) as string | null),
      schema_version: (pick(c.schema_version, m.schema_version) as string | null),
      allowed_tools: asArr<string>(c.allowed_tools),
      rules: asArr<SentraPolicyRule>(c.policies),
      cross_cloud_dependencies: asArr<CrossCloudDependency>(c.cross_cloud_dependencies),
      max_calls_per_minute: toNum(c.max_calls_per_minute),
      created_by: (pick(m.created_by, c.created_by) as string | null),
      updated_at: (pick(m.updated_at, m.created_at, c.created_at) as string | null),
      content_hash: (pick(m.content_hash) as string | null),
      s3_key: (pick(m.s3_key) as string | null),
      match_count_24h: toNum(m.match_count_24h),
      content: p.content ?? null,
    }
  },

  create: (body: { name: string; content: string }) =>
    http.post<{ policy_id: string; version: number; s3_key: string }>('/policies', body),

  update: (policyId: string, body: { content: string }) =>
    http.put<{ policy_id: string; version: number }>(
      `/policies/${encodeURIComponent(policyId)}`,
      body,
    ),

  remove: (policyId: string) =>
    http.del<{ success: boolean; status: string }>(
      `/policies/${encodeURIComponent(policyId)}`,
    ),
}

export const sigmaApi = {
  list: async (
    filters: { category?: string; severity?: string; enabled?: boolean; limit?: number; cursor?: string },
  ): Promise<Page<SigmaRule>> => {
    const res = await http.get<SigmaRulesResponse>('/sigma-rules', { ...filters })
    return { items: res.rules, total: res.total, next_token: res.next_token }
  },

  setStatus: (ruleId: string, status: 'enabled' | 'disabled') =>
    http.patch<{ success: boolean; rule_id: string; status: string }>(
      `/sigma-rules/${encodeURIComponent(ruleId)}`,
      { status },
    ),
}
