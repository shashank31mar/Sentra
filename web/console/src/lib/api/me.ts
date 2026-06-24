import type { MeContext } from '../../types/api'
import { http } from '../http'

/**
 * Server-derived operator context (LLD-26 WS-D D3b). Unlike `/whoami` (the nginx
 * edge echo of Cognito claims used for cosmetic display), this goes through the
 * tenant-scoped `/v1` client: the server resolves tenant + role from the session
 * and the membership registry. This is the authority for role-conditional UI.
 */
const USE_MOCKS = import.meta.env.VITE_DATA_SOURCE === 'mock'

const MOCK_ME: MeContext = {
  sub: 'mock-sub',
  email: 'dana.reyes@acme.io',
  tenant_id: 't_acme',
  role: 'owner',
  is_platform: false,
  memberships: [{ tenant_id: 't_acme', role: 'owner', is_primary: true }],
}

export const meApi = {
  get: async (): Promise<MeContext> => {
    if (USE_MOCKS) return MOCK_ME
    return http.get<MeContext>('/me')
  },
}
