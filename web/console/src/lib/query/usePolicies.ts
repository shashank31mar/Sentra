import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { policiesApi, sigmaApi, type PoliciesFilters } from '../api/policies'
import { queryKeys } from '../queryKeys'
import { useCurrentUser } from './useCurrentUser'
import type { MetricsRange } from '../../types/enums'
import type { PolicyCreateRequest } from '../../types/api'

export function usePolicies(filters: Omit<PoliciesFilters, 'cursor'> = {}) {
  return useInfiniteQuery({
    queryKey: queryKeys.policies.list(filters),
    queryFn: ({ pageParam }) => policiesApi.list({ ...filters, cursor: pageParam }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_token ?? undefined,
  })
}

export function usePolicyDetail(policyId: string) {
  return useQuery({
    queryKey: queryKeys.policies.detail(policyId),
    queryFn: () => policiesApi.detail(policyId),
    enabled: Boolean(policyId),
  })
}

export function useSigmaRules(
  filters: { category?: string; severity?: string; enabled?: boolean; range?: MetricsRange } = {},
) {
  return useInfiniteQuery({
    queryKey: queryKeys.sigma.list(filters),
    queryFn: ({ pageParam }) => sigmaApi.list({ ...filters, cursor: pageParam }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_token ?? undefined,
  })
}

export function useSigmaRuleContent(ruleId: string | null) {
  return useQuery({
    queryKey: queryKeys.sigma.content(ruleId ?? ''),
    queryFn: () => sigmaApi.content(ruleId as string),
    enabled: Boolean(ruleId),
  })
}

export function useToggleSigmaRule() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ ruleId, status }: { ruleId: string; status: 'enabled' | 'disabled' }) =>
      sigmaApi.setStatus(ruleId, status),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['sigma-rules'] }),
  })
}

/* ---- Policy lifecycle mutations (agent-policy-management T32) ----
 * A policy change can flip every bound agent's `active_policy_id`, so each
 * success invalidates both the `policies` and `agents` query buckets. */

export function useCreatePolicy() {
  const qc = useQueryClient()
  const { data: user } = useCurrentUser()
  return useMutation({
    mutationFn: (body: PolicyCreateRequest) => policiesApi.create(body, user?.email),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['policies'] }),
  })
}

export function useUpdatePolicy(policyId: string) {
  const qc = useQueryClient()
  const { data: user } = useCurrentUser()
  return useMutation({
    mutationFn: (body: Omit<PolicyCreateRequest, 'version'>) =>
      policiesApi.update(policyId, body, user?.email),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['policies'] })
      qc.invalidateQueries({ queryKey: ['agents'] }) // content changed for all bound agents
    },
  })
}

export function useDeletePolicy() {
  const qc = useQueryClient()
  const { data: user } = useCurrentUser()
  return useMutation({
    mutationFn: (policyId: string) => policiesApi.remove(policyId, user?.email),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['policies'] })
      qc.invalidateQueries({ queryKey: ['agents'] })
    },
  })
}

export function useSetPolicyStatus() {
  const qc = useQueryClient()
  const { data: user } = useCurrentUser()
  return useMutation({
    mutationFn: ({ policyId, status }: { policyId: string; status: 'active' | 'disabled' }) =>
      policiesApi.setStatus(policyId, status, user?.email),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['policies'] })
      qc.invalidateQueries({ queryKey: ['agents'] }) // status flips every bound agent's active_policy_id
    },
  })
}
