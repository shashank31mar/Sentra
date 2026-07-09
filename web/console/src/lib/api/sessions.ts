import { http } from '../http'
import type { QuarantineStatus } from '../../types/enums'
import type {
  Page,
  ReleaseResult,
  SessionDecisionsResponse,
  SessionInfo,
  SessionsResponse,
  SessionTrail,
} from '../../types/api'

export interface SessionsFilters {
  status?: QuarantineStatus
  agent_id?: string
  limit?: number
  cursor?: string
}

export const sessionsApi = {
  list: async (filters: SessionsFilters = {}): Promise<SessionsResponse> => {
    const res = await http.get<SessionsResponse>('/sessions', { ...filters })
    return { sessions: res.sessions ?? [], total: res.total ?? 0, next_token: res.next_token ?? null }
  },

  /** Cursor-paginated page of sessions for infinite loading (Quarantine console). */
  listPage: async (filters: SessionsFilters = {}): Promise<Page<SessionInfo>> => {
    const res = await http.get<SessionsResponse>('/sessions', { ...filters })
    return { items: res.sessions ?? [], total: res.total ?? 0, next_token: res.next_token ?? null }
  },

  /** Un-quarantine a session (operator override) — `DELETE /v1/quarantine/{id}`.
   *  No operator_id — the server attributes the release to the verified ctx.sub
   *  (M-G3.13, D8); a client-sent operator was dead weight. */
  release: (sessionId: string): Promise<ReleaseResult> =>
    http.del<ReleaseResult>(`/quarantine/${encodeURIComponent(sessionId)}`),

  /** Full per-request trace for a session (prompt + per-validator breadcrumbs) —
   *  `GET /v1/sessions/{id}/decisions`. Optionally narrow to one request_id. */
  decisions: async (
    sessionId: string,
    requestId?: string,
  ): Promise<SessionDecisionsResponse> => {
    const res = await http.get<SessionDecisionsResponse>(
      `/sessions/${encodeURIComponent(sessionId)}/decisions`,
      requestId ? { request_id: requestId } : undefined,
    )
    return { ...res, decisions: res.decisions ?? [] }
  },

  /** WS-D server-recomputed decision trail for ONE request (FX-1.2) —
   *  `GET /v1/sessions/{id}/trail?request_id=` (`routes.py:583`). Returns the four
   *  coverage buckets + recomputed `winning_source`/`block_point`. `request_id` is
   *  REQUIRED (the DDB PK is session-scoped — §9A.1). Guard `coverage` to `[]` so a
   *  malformed body never crashes the consumer. */
  trail: async (sessionId: string, requestId: string): Promise<SessionTrail> => {
    const res = await http.get<SessionTrail>(
      `/sessions/${encodeURIComponent(sessionId)}/trail`,
      { request_id: requestId },
    )
    return { ...res, coverage: res.coverage ?? [] }
  },
}

export type { SessionInfo }
