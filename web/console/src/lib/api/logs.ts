import { http } from '../http'
import type { Decision, ThreatType } from '../../types/enums'
import type { LogEntry, Page } from '../../types/api'

export interface LogsFilters {
  since?: string
  until?: string
  session_id?: string
  agent_id?: string
  decision?: Decision
  threat_type?: ThreatType
  limit?: number
  cursor?: string
}

interface LogsResponse {
  logs: LogEntry[]
  total: number
  next_token: string | null
}

export interface ConversationTimelineNode {
  id: string
  agent_id: string
  decision: Decision
  message: string
  timestamp: string
  children: ConversationTimelineNode[]
}

export interface ConversationTimeline {
  timeline: ConversationTimelineNode[]
  statistics: Record<string, number>
}

export const logsApi = {
  list: async (filters: LogsFilters): Promise<Page<LogEntry>> => {
    const res = await http.get<LogsResponse>('/logs', { ...filters })
    return { items: res.logs, total: res.total, next_token: res.next_token }
  },

  conversation: (conversationId: string) =>
    http.get<ConversationTimeline>(
      `/logs/conversation/${encodeURIComponent(conversationId)}`,
    ),
}
