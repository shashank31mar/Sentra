import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { sessionsApi, type SessionsFilters } from '../api/sessions'
import { queryKeys } from '../queryKeys'

/** Sessions list — polled, single page (used by the Threat Explorer to flag quarantined ids). */
export function useSessions(filters: SessionsFilters = {}) {
  return useQuery({
    queryKey: queryKeys.sessions.list({ ...filters }),
    queryFn: () => sessionsApi.list(filters),
    refetchInterval: 15_000,
  })
}

/** Infinite (cursor) sessions — the Quarantine console pages through all matching sessions. */
export function useInfiniteSessions(filters: Omit<SessionsFilters, 'cursor'> = {}) {
  return useInfiniteQuery({
    queryKey: ['sessions', 'infinite', { ...filters }],
    queryFn: ({ pageParam }) => sessionsApi.listPage({ ...filters, cursor: pageParam }),
    initialPageParam: undefined as string | undefined,
    getNextPageParam: (last) => last.next_token ?? undefined,
    refetchInterval: 30_000,
  })
}

/** Per-request decision trace for a session (prompt + validator breadcrumbs). Lazy: only fetched
 *  when `enabled` (e.g. a row is expanded). */
export function useSessionDecisions(sessionId: string, requestId?: string, enabled = true) {
  return useQuery({
    queryKey: ['sessions', 'trace', sessionId, requestId ?? null],
    queryFn: () => sessionsApi.decisions(sessionId, requestId),
    enabled: enabled && !!sessionId,
    staleTime: 30_000,
  })
}

/** Un-quarantine mutation — invalidates sessions, decisions, and overview metrics. */
export function useReleaseQuarantine() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ sessionId }: { sessionId: string }) => sessionsApi.release(sessionId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sessions'] })
      qc.invalidateQueries({ queryKey: ['decisions'] })
      qc.invalidateQueries({ queryKey: ['metrics'] })
    },
  })
}
