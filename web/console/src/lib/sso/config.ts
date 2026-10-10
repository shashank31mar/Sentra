/**
 * SSO configuration loader (ADR-SSO).
 *
 * Reads `/auth/config.json` at startup — a static file served alongside the SPA,
 * injected at deploy time by the customer. This decouples the IdP from the build:
 * no rebuild needed to switch from Azure AD to Okta to Cognito.
 *
 * When the file is missing or unreadable, falls back to `alb-cognito` (the legacy
 * ALB-Cognito flow), so existing deployments are zero-change.
 */

export interface OidcConfig {
  /** REQUIRED — The IdP's OIDC discovery URL (serves /.well-known/openid-configuration). */
  authority: string
  /** REQUIRED — The OAuth client_id registered with the IdP. */
  client_id: string
  /** REQUIRED — Where the IdP redirects after login (must match IdP config exactly). */
  redirect_uri: string
  /** REQUIRED — Where the IdP redirects after logout. */
  post_logout_redirect_uri: string
  /** Space-separated scopes. Defaults to 'openid profile email'. */
  scope?: string
  /**
   * Maps IdP token claims → Sentra identity fields. Different IdPs use different
   * claim names (Azure AD uses `roles`, Okta uses `groups`, Keycloak uses
   * `realm_access.roles`). Dot-notation for nested claims is supported.
   */
  claims_mapping?: {
    email?: string
    name?: string
    groups?: string
    username?: string
  }
  /** Extra params sent on the authorize request (e.g. Azure AD `domain_hint`). */
  extra_authorize_params?: Record<string, string>
  /** OAuth response type. Defaults to 'code' (PKCE authorization code). */
  response_type?: string
  /** Token storage backend. Defaults to 'sessionStorage' (per-tab, cleared on close). */
  token_storage?: 'sessionStorage' | 'localStorage'
  /** Whether to silently renew tokens via hidden iframe. Defaults to true. */
  silent_renew?: boolean
  /** Whether to auto-redirect to the IdP if unauthenticated. Defaults to true. */
  auto_redirect?: boolean
}

export interface AuthConfig {
  /**
   * `alb-cognito` — legacy ALB-Cognito flow (existing behavior, zero changes).
   * `oidc`        — SPA-driven OIDC with any compliant IdP.
   */
  auth_mode: 'alb-cognito' | 'oidc'
  /** OIDC provider settings. Required when `auth_mode` is `oidc`. */
  oidc?: OidcConfig
}

const FALLBACK: AuthConfig = { auth_mode: 'alb-cognito' }

let _cached: AuthConfig | null = null

/**
 * Fetch and cache the auth config. Safe to call multiple times — the second call
 * returns the cached result. Any fetch/parse error degrades to ALB-Cognito mode
 * so an unconfigured deployment never breaks.
 */
export async function loadAuthConfig(): Promise<AuthConfig> {
  if (_cached) return _cached
  try {
    const res = await fetch('/auth/config.json', {
      headers: { Accept: 'application/json' },
      cache: 'no-cache',
    })
    if (!res.ok) {
      _cached = FALLBACK
      return _cached
    }
    const parsed = (await res.json()) as AuthConfig
    // Validate minimum required fields for OIDC mode.
    if (parsed.auth_mode === 'oidc' && (!parsed.oidc?.authority || !parsed.oidc?.client_id)) {
      console.error('[SSO] auth_mode is "oidc" but required oidc.authority / oidc.client_id missing — falling back to alb-cognito')
      _cached = FALLBACK
      return _cached
    }
    _cached = parsed
    return _cached
  } catch {
    _cached = FALLBACK
    return _cached
  }
}

/** Synchronous getter for the cached config (returns ALB-Cognito fallback if not yet loaded). */
export function getAuthConfig(): AuthConfig {
  return _cached ?? FALLBACK
}

/** Convenience check: are we in SPA-driven OIDC mode? */
export function isOidcMode(): boolean {
  return getAuthConfig().auth_mode === 'oidc'
}
