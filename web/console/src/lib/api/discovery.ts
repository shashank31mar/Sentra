import { http } from '../http'
import type { CloudProvider, DiscoveryStatus, EnforcementMode, Risk } from '../../types/enums'
import type {
  DiscoveredAgent,
  DiscoverySummary,
  ImportResponse,
  Page,
  ProviderScan,
} from '../../types/api'

export interface DiscoveryAgentsFilters {
  cloud_provider?: CloudProvider
  framework?: string
  risk?: Risk
  status?: DiscoveryStatus
  since?: string
  /** Scope the review table to a just-connected account (connections-api-spec §5).
   *  Forward-compat: accepted by the controller; a no-op filter in the P0
   *  policy-derived read-model. */
  connection_id?: string
  limit?: number
  cursor?: string
}

interface DiscoveryAgentsResponse {
  agents: DiscoveredAgent[]
  total: number
  next_token: string | null
}

export const discoveryApi = {
  summary: () => http.get<DiscoverySummary>('/discovery/summary'),

  platforms: () => http.get<{ providers: ProviderScan[] }>('/discovery/platforms'),

  agents: async (filters: DiscoveryAgentsFilters): Promise<Page<DiscoveredAgent>> => {
    const res = await http.get<DiscoveryAgentsResponse>('/discovery/agents', { ...filters })
    return { items: res.agents, total: res.total, next_token: res.next_token }
  },

  // NOTE: POST /v1/discovery/scan is NOT exposed by WS-21 in P0 (descoped) —
  // do not call it; the Discovery "trigger scan" button stays disabled.

  // WS-21 D2: body is { agent_ids, enforcement_mode? } (default monitor). No policy_template_id in P0.
  import: (agentIds: string[], enforcementMode?: EnforcementMode) =>
    http.post<ImportResponse>('/discovery/import', {
      agent_ids: agentIds,
      ...(enforcementMode ? { enforcement_mode: enforcementMode } : {}),
    }),
}
