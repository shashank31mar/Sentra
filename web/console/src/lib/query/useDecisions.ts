import { useInfiniteQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { decisionsApi, type DecisionsFilters } from '../api/decisions'
import type { QuarantineRequest, VerdictRequest } from '../../types/api'
import { queryKeys } from '../queryKeys'

/** Live Threats feed — infinite (cursor) + polled.
 *
 * `refetchInterval` defaults to 15s (the live Threats feed). Callers that
 * accumulate many pages (e.g. the Topology map) pass `false` to disable polling,
 * since re-polling every loaded page on a timer is wasteful for a static map. */
export function useDecisions(
  filters: Omit<DecisionsFilters, 'cursor'> = {},
  options?: { refetchInterval?: number | false },
) {
  return useInfiniteQuery({
    queryKey: queryKeys.decisions.list(filters),
    queryFn: ({ pageParam }) => decisionsApi.list({ ...filters, cursor: pageParam }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_token ?? undefined,
    refetchInterval: options?.refetchInterval ?? 15_000,
  })
}

export function useQuarantine() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ sessionId, body }: { sessionId: string; body: QuarantineRequest }) =>
      decisionsApi.quarantine(sessionId, body),
    onSuccess: () => {
      // Refresh the decision feed and the sessions list so quarantine status
      // surfaces wherever a session is shown (Threat Explorer, Quarantine).
      qc.invalidateQueries({ queryKey: ['decisions'] })
      qc.invalidateQueries({ queryKey: ['sessions'] })
    },
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
