import { http } from '../http'
import type { ResidualAgentsResponse } from '../../types/api'

export const identityApi = {
  // Agents in the active tenant currently on the WS-B B1 legacy-fallback window
  // (uncredentialed, enforce-flipped, on borrowed time). Server scopes the list
  // to the operator's tenant; read-only.
  listResidual: () => http.get<ResidualAgentsResponse>('/identity/residual-agents'),
}
