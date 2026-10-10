import type { CurrentUser } from '../../types/api'
import { isOidcMode, getAuthConfig } from '../sso/config'
import { getOidcUser } from '../sso/oidcManager'
import { mapOidcClaims } from '../sso/claims'

/**
 * Current-operator identity.
 *
 * In OIDC mode: resolved from the ID token claims (no server call needed).
 * In ALB-Cognito mode: served same-origin by the console nginx at `/whoami`,
 * which echoes the ALB-injected Cognito claims (`x-amzn-oidc-identity`).
 * Every failure mode degrades to an unknown (but non-throwing) identity.
 */

const USE_MOCKS = import.meta.env.VITE_DATA_SOURCE === 'mock'

const MOCK_USER: CurrentUser = {
  email: 'dana.reyes@acme.io',
  name: 'Dana Reyes',
  username: 'dana.reyes',
  groups: ['administrator'],
}

const UNKNOWN: CurrentUser = { email: null, name: null, username: null, groups: [] }

interface WhoamiResponse {
  email?: string | null
  name?: string | null
  username?: string | null
  groups?: string[] | null
}

export const authApi = {
  me: async (): Promise<CurrentUser> => {
    if (USE_MOCKS) return MOCK_USER

    // OIDC mode: identity comes from the ID token, not /whoami.
    if (isOidcMode()) {
      try {
        const user = await getOidcUser()
        if (!user?.profile) return UNKNOWN
        const config = getAuthConfig()
        return mapOidcClaims(
          user.profile as unknown as Record<string, unknown>,
          config.oidc?.claims_mapping,
        )
      } catch {
        return UNKNOWN
      }
    }

    // ALB-Cognito mode: /whoami (Nginx echoes ALB-injected headers).
    try {
      const res = await fetch('/whoami', {
        headers: { Accept: 'application/json' },
        // Surface the ALB's session-expired 302 as an opaque redirect instead of
        // chasing the blocked cross-origin Cognito load — the main /v1 client
        // owns interactive re-auth (see lib/http.ts).
        redirect: 'manual',
      })
      if (!res.ok || res.type === 'opaqueredirect' || res.status === 0) return UNKNOWN
      const body = (await res.json()) as WhoamiResponse
      return {
        email: body.email?.trim() || null,
        name: body.name?.trim() || null,
        username: body.username?.trim() || null,
        groups: Array.isArray(body.groups) ? body.groups : [],
      }
    } catch {
      return UNKNOWN
    }
  },
}
