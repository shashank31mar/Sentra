import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { agentsApi } from '../api/agents'
import { queryKeys } from '../queryKeys'

export function useAgents() {
  return useQuery({
    queryKey: queryKeys.agents.list(),
    queryFn: () => agentsApi.list(),
  })
}

export function useAgentDetail(agentId: string) {
  return useQuery({
    queryKey: queryKeys.agents.detail(agentId),
    queryFn: () => agentsApi.detail(agentId),
    enabled: Boolean(agentId),
  })
}

export function useAgentTools(agentId: string) {
  return useQuery({
    queryKey: queryKeys.agents.tools(agentId),
    queryFn: () => agentsApi.tools(agentId),
    enabled: Boolean(agentId),
  })
}

export function useAttachPolicy(agentId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (policyId: string) => agentsApi.attachPolicy(agentId, policyId),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.agents.detail(agentId) }),
  })
}

export function useDetachPolicy(agentId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (policyId: string) => agentsApi.detachPolicy(agentId, policyId),
    onSuccess: () => qc.invalidateQueries({ queryKey: queryKeys.agents.detail(agentId) }),
  })
}
