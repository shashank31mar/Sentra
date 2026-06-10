import { buildQuery, http } from '../http'
import type { QuarantineStatus } from '../../types/enums'
import type {
  Page,
  ReleaseResult,
  SessionDecisionsResponse,
  SessionInfo,
  SessionsResponse,
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

  /** Un-quarantine a session (operator override) — `DELETE /v1/quarantine/{id}`. */
  release: (sessionId: string, operatorId = 'operator'): Promise<ReleaseResult> =>
    http.del<ReleaseResult>(
      `/quarantine/${encodeURIComponent(sessionId)}${buildQuery({ operator_id: operatorId })}`,
    ),

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
}

export type { SessionInfo }
