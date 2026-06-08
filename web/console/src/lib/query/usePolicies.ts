import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { policiesApi, sigmaApi, type PoliciesFilters } from '../api/policies'
import { queryKeys } from '../queryKeys'

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

export function useSigmaRules(filters: { category?: string; severity?: string; enabled?: boolean } = {}) {
  return useInfiniteQuery({
    queryKey: queryKeys.sigma.list(filters),
    queryFn: ({ pageParam }) => sigmaApi.list({ ...filters, cursor: pageParam }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_token ?? undefined,
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
