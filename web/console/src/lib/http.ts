import type { ApiErrorBody } from '../types/api'
import { clearActiveTenant, getActiveTenant, tenantHeader } from './tenant'
import { ORG_PAGE_PATH } from './orgEntry'
import { isOidcMode } from './sso/config'
import { getAccessToken, oidcSignIn } from './sso/oidcManager'

/**
 * Thin fetch wrapper for the SOC console.
 *
 * SECURITY: this client NEVER sets `x-api-key`. The Usage-Plan key is injected
 * server-side — by nginx in prod, by the Vite dev proxy in dev (see vite.config.ts).
 * All requests are same-origin to `/v1`.
 */

export const API_BASE = '/v1'

const USE_MOCKS = import.meta.env.VITE_DATA_SOURCE === 'mock'

const delay = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

export class ApiException extends Error {
  readonly status: number
  readonly errorCode: string
  readonly requestId?: string

  constructor(status: number, body: Partial<ApiErrorBody>, options?: { cause?: unknown }) {
    super(body.error ?? `Request failed (${status})`, options)
    this.name = 'ApiException'
    this.status = status
    this.errorCode = body.error_code ?? 'UNKNOWN'
    this.requestId = body.request_id
  }
}

/**
 * The console sits behind an ALB `authenticate-cognito` action. When the ALB
 * auth session expires it answers our same-origin XHRs with a 302 to the
 * Cognito hosted UI (cross-origin). We MUST NOT let `fetch` follow that — the
 * cross-origin load is blocked by same-origin policy + CSP `connect-src 'self'`
 * ("Unsafe attempt to load URL … from frame"). Interactive re-auth can only
 * happen at the TOP LEVEL, so we trigger a full-page navigation instead.
 */
const REAUTH_GUARD_KEY = 'aegion:last-reauth'

function reauthenticate(): never {
  // Clear the per-tab tenant binding on session loss (ADR-039): a re-login must
  // rebind through the org-first flow, never inherit a stale tenant preference.
  clearActiveTenant()

  // OIDC mode: redirect to the IdP login page via oidc-client-ts.
  if (isOidcMode()) {
    oidcSignIn()
    throw new ApiException(401, {
      error: 'Your session has expired. Redirecting to sign in…',
      error_code: 'AUTH_EXPIRED',
    })
  }

  // ALB-Cognito mode: reload the page → ALB performs the interactive Cognito login.
  const last = Number(sessionStorage.getItem(REAUTH_GUARD_KEY) ?? 0)
  // Guard against redirect loops: auto-bounce at most once per 10s.
  if (Date.now() - last > 10_000) {
    sessionStorage.setItem(REAUTH_GUARD_KEY, String(Date.now()))
    // Reload the current SPA URL at the top level → ALB performs the
    // interactive Cognito login and restores the session cookie.
    window.location.assign(window.location.href)
  }
  throw new ApiException(401, {
    error: 'Your session has expired. Redirecting to sign in…',
    error_code: 'AUTH_EXPIRED',
  })
}

/**
 * FX-2.1 — lost-tenant-binding 403 fail-safe (lld/40 §C.4).
 *
 * When the active `X-Aegion-Tenant` preference no longer resolves to a membership
 * (a stale/corrupted `sessionStorage['aegion.activeTenant']` fails the
 * `resolve_operator_tenant` membership check — `deps.py:440`), fail SAFE: drop the
 * bad binding and bounce to the org-first page so the operator re-picks — never
 * leave them staring at a 403 they can't clear. This is DISTINCT from:
 *   - a role-403 ("you lack the role", `require_role` → "requires role >= …",
 *     `deps.py:508`), which must NOT clear the binding — it can hit a role-gated
 *     READ too (e.g. the admin-gated `GET /tenants/{id}/members`, rbac.ts:44), so the
 *     HTTP method is NOT a reliable discriminator; and
 *   - a 401/expired session (reauthenticate()).
 * We therefore key the bounce on the SERVER'S REASON (see isLostTenantBinding403),
 * gated on an active tenant being bound so a platform read (no tenant) and a
 * no-tenant read never trip it.
 */
function bounceToOrgOnLostTenant(): never {
  clearActiveTenant()
  window.location.assign(ORG_PAGE_PATH)
  throw new ApiException(403, {
    error: 'Your organization selection is no longer valid. Returning to organization selection…',
    error_code: 'TENANT_BINDING_LOST',
  })
}

/**
 * Positively identify a *lost-tenant-binding* 403 from the server's reason so the
 * binding is wiped ONLY when we're confident the active tenant is the problem.
 * `resolve_operator_tenant` raises "not a member of requested tenant" (deps.py:440)
 * / "operator has no tenant membership" (deps.py:446) when the bound `X-Aegion-Tenant`
 * no longer resolves to a membership. A role-403 ("requires role >= …", deps.py:508)
 * — which ALSO occurs on role-gated READs (rbac.ts:44) — deliberately does NOT match,
 * so it is surfaced as an honest 403 and never ejects an operator with a valid binding.
 *
 * Fail-safe by construction: an unrecognized 403 does NOT match → the binding is
 * preserved and the caller sees the real 403, never a wrongful eject to org selection.
 */
const LOST_TENANT_403_RE = /not a member of requested tenant|no tenant membership/i

function isLostTenantBinding403(body: Partial<ApiErrorBody>): boolean {
  return LOST_TENANT_403_RE.test(body.error ?? '')
}

/** Per-request http options that are NOT part of the fetch `RequestInit`. */
export interface RequestOptions {
  /**
   * FX-2.3 — code-enforce that this request never attaches `X-Aegion-Tenant`, even
   * if a tenant is ambiently bound. Platform (cross-tenant) calls set this so the
   * fleet-scope invariant holds by construction, not by the luck of a platform
   * operator happening to have no active tenant.
   */
  omitTenant?: boolean
}

export type QueryValue = string | number | boolean | null | undefined

/** Build a query string, omitting null/undefined/empty values. */
export function buildQuery(params?: Record<string, QueryValue>): string {
  if (!params) return ''
  const sp = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === '') continue
    sp.append(key, String(value))
  }
  const qs = sp.toString()
  return qs ? `?${qs}` : ''
}

/** "CODE: message" — the controller embeds the machine code in the detail string
 *  (e.g. "PROVIDER_NOT_AVAILABLE: …", "NOT_CONNECTED: …", "VALIDATION_ERROR: …"). */
const CODED_DETAIL_RE = /^([A-Z][A-Z0-9_]+):\s*([\s\S]+)$/

/**
 * Normalize the controller's error bodies into our {@link ApiErrorBody} envelope.
 *
 * The security-controller (FastAPI) has no global error handler, so error
 * responses come back as `{ detail }` in one of three shapes:
 *  - a string, sometimes `"CODE: message"` (connections domain — routes.py);
 *  - a custom dict `{ success, error, error_type, … }` (app/exceptions.py);
 *  - a list of pydantic errors (422 RequestValidationError).
 * It may also already be the LLD §11.1 envelope `{ error, error_code, request_id }`
 * (e.g. the Vite dev proxy / mock router). This collapses all of them so toasts
 * and ErrorState show the real message + code instead of a generic "Request failed".
 */
export function normalizeErrorBody(raw: unknown): Partial<ApiErrorBody> {
  if (raw == null) return {}
  if (typeof raw === 'string') return { error: raw }
  if (typeof raw !== 'object') return {}
  const obj = raw as Record<string, unknown>

  // Already our envelope (mock router / dev proxy passthrough).
  if (typeof obj.error === 'string') {
    return {
      error: obj.error,
      error_code: (obj.error_code as string) ?? (obj.error_type as string),
      request_id: obj.request_id as string | undefined,
    }
  }

  const detail = obj.detail
  if (typeof detail === 'string') {
    const m = CODED_DETAIL_RE.exec(detail)
    return m ? { error: m[2], error_code: m[1] } : { error: detail }
  }
  if (Array.isArray(detail)) {
    // FastAPI 422 — join the per-field messages.
    const msg = detail
      .map((e) => (e && typeof e === 'object' ? (e as { msg?: string }).msg : String(e)))
      .filter(Boolean)
      .join('; ')
    return { error: msg || 'Validation error', error_code: 'VALIDATION_ERROR' }
  }
  if (detail && typeof detail === 'object') {
    const d = detail as Record<string, unknown>
    return {
      error: (d.error as string) ?? (d.message as string),
      error_code: d.error_type as string | undefined,
      request_id: d.request_id as string | undefined,
    }
  }
  return {}
}

async function request<T>(path: string, init?: RequestInit, opts?: RequestOptions): Promise<T> {
  // Code-level mock adapter (no service worker). In prod, VITE_DATA_SOURCE is
  // unset so USE_MOCKS is false and this branch never runs — the mockRouter is
  // emitted as a lazy chunk but never fetched (no fixtures reach users).
  if (USE_MOCKS) {
    const [rawPath, qs] = path.split('?')
    const { resolveMock } = await import('../mocks/mockRouter')
    const parsedBody = typeof init?.body === 'string' ? JSON.parse(init.body) : undefined
    const mock = resolveMock(init?.method ?? 'GET', rawPath, new URLSearchParams(qs), parsedBody)
    if (mock) {
      await delay(120)
      if (mock.status >= 400) {
        throw new ApiException(mock.status, mock.body as Partial<ApiErrorBody>)
      }
      return (mock.status === 204 ? undefined : mock.body) as T
    }
    // Unmatched in mock mode → fall through to real fetch.
  }

  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      ...init,
      // `manual` surfaces the ALB's cross-origin login 302 as an opaque
      // redirect (status 0) instead of attempting the blocked cross-origin
      // load. We then re-auth at the top level. See reauthenticate().
      redirect: 'manual',
      headers: {
        Accept: 'application/json',
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        // OIDC mode: attach the access token as a Bearer header (the backend
        // verifies it against the IdP's JWKS). ALB-Cognito: the cookie rides
        // along automatically — no Authorization header needed.
        ...(isOidcMode() && getAccessToken() ? { Authorization: `Bearer ${getAccessToken()}` } : {}),
        // Active-tenant switch for multi-membership operators (LLD-26 WS-C).
        // Server-validated against membership; omitted when no explicit tenant.
        // FX-2.3: a platform (cross-tenant) call passes `omitTenant` so the header
        // is dropped by CODE even when a tenant is ambiently bound — the fleet-scope
        // invariant no longer relies on the operator happening to have no tenant.
        ...(opts?.omitTenant ? {} : tenantHeader()),
        ...init?.headers,
      },
    })
  } catch (cause) {
    throw new ApiException(
      0,
      { error: 'Network error — could not reach the API.', error_code: 'NETWORK_ERROR' },
      { cause },
    )
  }

  // ALB auth session expired:
  //  - page-style rule → 302 to Cognito, surfaced here as an opaque redirect;
  //  - /v1* deny rule   → a clean 401 from the ALB (no JSON body).
  // Either way, interactive re-auth must happen at the top level.
  if (res.type === 'opaqueredirect' || res.status === 0 || res.status === 401) {
    reauthenticate()
  }

  if (!res.ok) {
    let raw: unknown
    try {
      raw = await res.json()
    } catch {
      /* non-JSON error body */
    }
    const body = normalizeErrorBody(raw)

    // FX-2.1: a *lost-tenant-binding* 403 — the bound `X-Aegion-Tenant` no longer
    // resolves to a membership (deps.py:440/446) — fails SAFE: drop the stale binding
    // + bounce to the org page. We key on the SERVER'S REASON, not the HTTP method: a
    // role-403 ("requires role >= …") can hit a role-gated READ too (e.g. the
    // admin-gated `GET /tenants/{id}/members`, rbac.ts:44), and wiping a valid binding
    // there would wrongly eject the operator — so a role-403 stays an honest 403
    // (handled by the MutationCache degrade for writes). Gated on an active tenant
    // being bound; `omitTenant` (platform reads) and no-tenant reads never trip this.
    if (
      res.status === 403 &&
      !opts?.omitTenant &&
      getActiveTenant() &&
      isLostTenantBinding403(body)
    ) {
      bounceToOrgOnLostTenant()
    }
    throw new ApiException(res.status, body)
  }

  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const http = {
  get: <T>(path: string, params?: Record<string, QueryValue>, opts?: RequestOptions) =>
    request<T>(`${path}${buildQuery(params)}`, undefined, opts),
  post: <T>(path: string, body?: unknown, headers?: Record<string, string>, opts?: RequestOptions) =>
    request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined, headers }, opts),
  put: <T>(path: string, body?: unknown, headers?: Record<string, string>, opts?: RequestOptions) =>
    request<T>(path, { method: 'PUT', body: body ? JSON.stringify(body) : undefined, headers }, opts),
  patch: <T>(path: string, body?: unknown, headers?: Record<string, string>, opts?: RequestOptions) =>
    request<T>(path, { method: 'PATCH', body: body ? JSON.stringify(body) : undefined, headers }, opts),
  del: <T>(path: string, headers?: Record<string, string>, opts?: RequestOptions) =>
    request<T>(path, { method: 'DELETE', headers }, opts),
}

/** Build an `X-Operator-Email` header map (omitted when no operator is known).
 *  agent-policy-management §9: all writes attribute the operator. */
export const operatorHeader = (email?: string | null): Record<string, string> =>
  email ? { 'X-Operator-Email': email } : {}
