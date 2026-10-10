import type { CurrentUser } from '../types/api'

/**
 * Auth helpers for the SOC console.
 *
 * The console sits behind an ALB `authenticate-cognito` action. There is NO REST
 * logout API: sign-out is a TOP-LEVEL navigation to the same-origin `/logout`
 * (the nginx edge clears the AWSELBAuthSessionCookie cookies and 302s through the
 * Cognito hosted-UI logout). It must NOT be a fetch — the Cognito hop is
 * cross-origin and blocked by CSP `connect-src 'self'` (see lib/http.ts).
 */

import { isOidcMode } from './sso/config'
import { oidcSignOut } from './sso/oidcManager'

const USE_MOCKS = import.meta.env.VITE_DATA_SOURCE === 'mock'

/** Same-origin sign-out path. Overridable for non-ALB hosting. */
export const LOGOUT_URL = (import.meta.env.VITE_LOGOUT_URL as string | undefined) ?? '/logout'

export function signOut(): void {
  // No ALB in local dev — bounce to the app root so the demo stays usable.
  if (USE_MOCKS) {
    window.location.assign('/')
    return
  }
  // OIDC mode: delegate to oidc-client-ts (IdP-driven logout, no Nginx needed).
  if (isOidcMode()) {
    oidcSignOut()
    return
  }
  // Legacy ALB-Cognito: top-level nav to /logout (Nginx clears cookies + 302s to Cognito).
  window.location.assign(LOGOUT_URL)
}

/** Title-case a token-ish string ("dana.reyes" → "Dana Reyes"). */
function prettify(value: string): string {
  return value
    .split(/[.\-_\s]+/)
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

/**
 * Human display name. Prefers the `name` claim; falls back to a prettified email
 * local-part, then username, then a generic label. The ALB only injects the
 * Cognito identity (email) by default, so the email path is the common one.
 */
export function displayName(user?: CurrentUser | null): string {
  const name = user?.name?.trim()
  if (name) return name
  const email = user?.email?.trim()
  if (email) return prettify(email.split('@')[0]) || email
  const username = user?.username?.trim()
  if (username) return prettify(username) || username
  return 'Account'
}

/** First Cognito group → role label; defaults to "Operator". */
export function primaryRole(user?: CurrentUser | null): string {
  const group = user?.groups?.[0]?.trim()
  return group ? prettify(group) : 'Operator'
}

/**
 * DISPLAY-ONLY, NON-AUTHORITATIVE tenant label from the email domain ("acme.io").
 *
 * ⚠️ Cosmetic header hint only. The authoritative tenant is server-derived from
 * the operator's membership (`GET /v1/me` → `useMe()`, LLD-26 WS-C C1). Never use
 * this to scope data, gate UI, or send to the API — the server resolves and
 * enforces the real tenant from the Cognito session.
 */
export function tenantLabelForDisplay(user?: CurrentUser | null): string | null {
  const email = user?.email?.trim()
  if (!email || !email.includes('@')) return null
  return email.split('@')[1] || null
}

/** Up-to-2-char monogram for the avatar; null when no identity is known. */
export function initials(user?: CurrentUser | null): string | null {
  const source = user?.name?.trim() || user?.email?.trim()
  if (!source) return null
  const base = source.includes('@') ? source.split('@')[0] : source
  const parts = base.split(/[.\-_\s]+/).filter(Boolean)
  const chars = parts.length >= 2 ? parts[0][0] + parts[1][0] : base.slice(0, 2)
  return chars.toUpperCase()
}
