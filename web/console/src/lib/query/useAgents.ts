import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { agentsApi } from '../api/agents'
import { queryKeys } from '../queryKeys'
import { useCurrentUser } from './useCurrentUser'
import type { AgentDetail, AgentListItem } from '../../types/api'

/**
 * Patch the agent's `active_policy_id` directly in the React Query cache after a
 * binding change — an OPTIMISTIC in-place update. The Inventory row (and the
 * detail page) flip instantly, with NO refetch of the expensive enriched
 * `GET /v1/agents` (per-agent ECS + CloudWatch + session scans) and no page
 * reload. The next natural refetch (navigation / window focus) reconciles.
 */
function patchAgentPolicy(qc: QueryClient, agentId: string, activePolicyId: string | null) {
  qc.setQueryData<{ agents: AgentListItem[]; total: number }>(queryKeys.agents.list(), (old) =>
    old
      ? {
          ...old,
          agents: old.agents.map((a) =>
            a.agent_id === agentId ? { ...a, active_policy_id: activePolicyId } : a,
          ),
        }
      : old,
  )
  qc.setQueryData<AgentDetail>(queryKeys.agents.detail(agentId), (old) =>
    old ? { ...old, active_policy_id: activePolicyId } : old,
  )
}

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
  const { data: user } = useCurrentUser()
  return useMutation({
    mutationFn: (policyId: string) => agentsApi.attachPolicy(agentId, policyId, user?.email),
    onSuccess: (res) => {
      // Instant in-place update (no expensive enriched refetch, no reload).
      patchAgentPolicy(qc, agentId, res.policy_id)
      // Tools (Agent Detail tab) now reflect a different policy; the policy's
      // bound-agent set changed. These are off the hot path — refetch on view.
      qc.invalidateQueries({ queryKey: queryKeys.agents.tools(agentId) })
      if (res?.policy_id) qc.invalidateQueries({ queryKey: queryKeys.policies.detail(res.policy_id) })
    },
  })
}

export function useDetachPolicy(agentId: string) {
  const qc = useQueryClient()
  const { data: user } = useCurrentUser()
  return useMutation({
    mutationFn: (policyId: string) => agentsApi.detachPolicy(agentId, policyId, user?.email),
    onSuccess: (res) => {
      // Instant in-place update → row flips to "Attach" immediately.
      patchAgentPolicy(qc, agentId, null)
      qc.invalidateQueries({ queryKey: queryKeys.agents.tools(agentId) })
      if (res?.policy_id) qc.invalidateQueries({ queryKey: queryKeys.policies.detail(res.policy_id) })
    },
  })
}
