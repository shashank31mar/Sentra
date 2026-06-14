import { http, operatorHeader } from '../http'
import type { AgentDetail, AgentListItem, AgentTool } from '../../types/api'

interface AgentsListResponse {
  agents: AgentListItem[]
  total: number
}

interface AgentToolsResponse {
  tools: AgentTool[]
  total: number
}

export const agentsApi = {
  // Agent Inventory shows ONLY Managed agents — those with observed /v1/validate
  // traffic (feature §8.1). Imported-but-silent agents live in the Import tab.
  list: () => http.get<AgentsListResponse>('/agents', { enrich: true, managed_only: true }),

  detail: (agentId: string) =>
    http.get<AgentDetail>(`/agents/${encodeURIComponent(agentId)}`),

  tools: (agentId: string) =>
    http.get<AgentToolsResponse>(`/agents/${encodeURIComponent(agentId)}/tools`),

  attachPolicy: (agentId: string, policyId: string, operatorEmail?: string | null) =>
    http.post<{ agent_id: string; policy_id: string; status: string; attached_at: string }>(
      `/agents/${encodeURIComponent(agentId)}/policies`,
      { policy_id: policyId },
      operatorHeader(operatorEmail),
    ),

  detachPolicy: (agentId: string, policyId: string, operatorEmail?: string | null) =>
    http.del<{ agent_id: string; policy_id: string; status: string }>(
      `/agents/${encodeURIComponent(agentId)}/policies/${encodeURIComponent(policyId)}`,
      operatorHeader(operatorEmail),
    ),
}
