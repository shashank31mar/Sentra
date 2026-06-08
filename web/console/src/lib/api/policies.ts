import { http } from '../http'
import type { PolicyStatus } from '../../types/enums'
import type { Page, PolicyDetail, PolicySummary, SigmaRule } from '../../types/api'

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

  detail: (policyId: string) =>
    http.get<{ policy: PolicyDetail }>(`/policies/${encodeURIComponent(policyId)}`, {
      include_content: true,
    }),

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
