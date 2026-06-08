import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { decisionsApi, type DecisionsFilters } from '../api/decisions'
import type { QuarantineRequest, VerdictRequest } from '../../types/api'
import { queryKeys } from '../queryKeys'

/** Live Threats feed — infinite (cursor) + polled. */
export function useDecisions(filters: Omit<DecisionsFilters, 'cursor'> = {}) {
  return useInfiniteQuery({
    queryKey: queryKeys.decisions.list(filters),
    queryFn: ({ pageParam }) => decisionsApi.list({ ...filters, cursor: pageParam }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_token ?? undefined,
    refetchInterval: 15_000,
  })
}

export function useQuarantine() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ sessionId, body }: { sessionId: string; body: QuarantineRequest }) =>
      decisionsApi.quarantine(sessionId, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['decisions'] }),
  })
}

export function useVerdict() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ decisionId, body }: { decisionId: string; body: VerdictRequest }) =>
      decisionsApi.verdict(decisionId, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['decisions'] }),
  })
}
