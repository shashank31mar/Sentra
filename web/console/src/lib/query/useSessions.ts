import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { sessionsApi, type SessionsFilters } from '../api/sessions'
import { queryKeys } from '../queryKeys'

/** Sessions list — polled, used by the Quarantine console. */
export function useSessions(filters: SessionsFilters = {}) {
  return useQuery({
    queryKey: queryKeys.sessions.list({ ...filters }),
    queryFn: () => sessionsApi.list(filters),
    refetchInterval: 15_000,
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
    mutationFn: ({ sessionId, operatorId }: { sessionId: string; operatorId?: string }) =>
      sessionsApi.release(sessionId, operatorId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['sessions'] })
      qc.invalidateQueries({ queryKey: ['decisions'] })
      qc.invalidateQueries({ queryKey: ['metrics'] })
    },
  })
}
