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

/**
 * A single session's `SessionInfo` for the forensics summary header (FX-1.3).
 *
 * There is NO single-session GET (`GET /v1/sessions/{id}` does not exist — do not
 * invent it), so this reuses the tenant-scoped `sessionsApi.list` and selects the
 * matching row client-side. Returns `{ session, isLoading, isError }`; `session` is
 * `null` when the id is not in the returned window (the header then honestly renders
 * a "session not in the current window" note rather than fabricating counts).
 */
export function useSessionInfo(sessionId: string) {
  const q = useSessions({ limit: 200 })
  const session = (q.data?.sessions ?? []).find((s) => s.session_id === sessionId) ?? null
  return { session, isLoading: q.isLoading, isError: q.isError, error: q.error }
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

/** WS-D server-recomputed decision trail for one request (FX-1.2) —
 *  `GET /v1/sessions/{id}/trail`. `retry:false` so a 404/501 (endpoint absent on an
 *  older stack) surfaces immediately as the PARTIAL fallback instead of retry-storming. */
export function useSessionTrail(sessionId: string, requestId: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.sessions.trail(sessionId, requestId),
    queryFn: () => sessionsApi.trail(sessionId, requestId),
    enabled: enabled && !!sessionId && !!requestId,
    staleTime: 30_000,
    retry: false,
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
