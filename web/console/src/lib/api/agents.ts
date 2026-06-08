import { http } from '../http'
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
  list: () => http.get<AgentsListResponse>('/agents', { enrich: true }),

  detail: (agentId: string) =>
    http.get<AgentDetail>(`/agents/${encodeURIComponent(agentId)}`),

  tools: (agentId: string) =>
    http.get<AgentToolsResponse>(`/agents/${encodeURIComponent(agentId)}/tools`),

  attachPolicy: (agentId: string, policyId: string) =>
    http.post<{ agent_id: string; policy_id: string; status: string; attached_at: string }>(
      `/agents/${encodeURIComponent(agentId)}/policies`,
      { policy_id: policyId },
    ),

  detachPolicy: (agentId: string, policyId: string) =>
    http.del<{ agent_id: string; policy_id: string; status: string }>(
      `/agents/${encodeURIComponent(agentId)}/policies/${encodeURIComponent(policyId)}`,
    ),
}
