import { http } from '../http'
import type { CloudProvider, Decision, ThreatType } from '../../types/enums'
import type {
  DecisionItem,
  Page,
  QuarantineRequest,
  VerdictRequest,
  VerdictResult,
} from '../../types/api'

export interface DecisionsFilters {
  since?: string
  until?: string
  agent_id?: string
  decision?: Decision
  threat_type?: ThreatType
  cloud_provider?: CloudProvider
  limit?: number
  cursor?: string
}

interface DecisionsResponse {
  decisions: DecisionItem[]
  total: number
  next_token: string | null
}

export const decisionsApi = {
  list: async (filters: DecisionsFilters): Promise<Page<DecisionItem>> => {
    const res = await http.get<DecisionsResponse>('/decisions', { ...filters })
    return { items: res.decisions, total: res.total, next_token: res.next_token }
  },

  /** Operator quarantine override (LLD §4). */
  quarantine: (sessionId: string, body: QuarantineRequest) =>
    http.post<{ success: boolean; new_status: string }>(
      `/quarantine/${encodeURIComponent(sessionId)}`,
      body,
    ),

  /** FP/FN human verdict (LLD §12.3). */
  verdict: (decisionId: string, body: VerdictRequest) =>
    http.post<VerdictResult>(
      `/decisions/${encodeURIComponent(decisionId)}/verdict`,
      body,
    ),
}
