import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { discoveryApi, type DiscoveryAgentsFilters } from '../api/discovery'
import { queryKeys } from '../queryKeys'

export function useDiscoverySummary() {
  return useQuery({
    queryKey: queryKeys.discovery.summary(),
    queryFn: () => discoveryApi.summary(),
  })
}

export function useDiscoveryPlatforms() {
  return useQuery({
    queryKey: queryKeys.discovery.platforms(),
    queryFn: () => discoveryApi.platforms(),
  })
}

export function useDiscoveredAgents(filters: Omit<DiscoveryAgentsFilters, 'cursor'> = {}) {
  return useInfiniteQuery({
    queryKey: queryKeys.discovery.agents(filters),
    queryFn: ({ pageParam }) => discoveryApi.agents({ ...filters, cursor: pageParam }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_token ?? undefined,
  })
}

export function useImportAgents() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ agentIds, enforcementMode }: { agentIds: string[]; enforcementMode?: import('../../types/enums').EnforcementMode }) =>
      discoveryApi.import(agentIds, enforcementMode),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['discovery'] })
      qc.invalidateQueries({ queryKey: ['agents'] })
    },
  })
}
