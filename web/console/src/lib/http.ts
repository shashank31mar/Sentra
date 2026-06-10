import type { ApiErrorBody } from '../types/api'

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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
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
    let body: Partial<ApiErrorBody> = {}
    try {
      body = (await res.json()) as Partial<ApiErrorBody>
    } catch {
      /* non-JSON error body */
    }
    throw new ApiException(res.status, body)
  }

  if (res.status === 204) return undefined as T
  return (await res.json()) as T
}

export const http = {
  get: <T>(path: string, params?: Record<string, QueryValue>) =>
    request<T>(`${path}${buildQuery(params)}`),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body ? JSON.stringify(body) : undefined }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PUT', body: body ? JSON.stringify(body) : undefined }),
  patch: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PATCH', body: body ? JSON.stringify(body) : undefined }),
  del: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
}
