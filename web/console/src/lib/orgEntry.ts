import { setActiveTenant } from './tenant'
import type { MeContext } from '../types/api'

/**
 * Org-first entry client contract (ADR-039 / D14, G2.12).
 *
 * MIRRORS the inline script in `public/org.html` — that page is standalone static
 * HTML (it must load NO hashed `/assets/*` bundle, which would 401 under the
 * priority-10 Cognito auth rule), so it can't import this module and re-implements
 * the flow inline. The two are held in lockstep by the `orgEntry.parity.test.ts`
 * gate, which reads `public/org.html`, extracts its inline `<script>`, and asserts
 * the load-bearing invariants match this module + the shared storage key exported
 * from `tenant.ts` (`ACTIVE_TENANT_STORAGE_KEY`): same resolve endpoint
 * (`RESOLVE_ORG_PATH`), same post-bind redirect (`POST_BIND_REDIRECT`), stash-only-
 * `tenant_id` (never the typed name), and the 404-vs-non-ok branch distinction.
 * Change one side without the other and that test fails. This module is the
 * canonical, unit-tested source of the resolve→stash→redirect behavior, reused by
 * the SPA router guard (`needsOrgRedirect`).
 *
 * Flow: unauth operator types an org name → GET `/public/resolve-org?org=…` (a
 * NON-`/v1` public path, exempt from the deny rule) → on hit, stash the resolved
 * `tenant_id` into `sessionStorage` (never the typed name) and redirect to the
 * console entry (the ALB intercepts with Cognito); on miss (404), stay put with a
 * friendly message and stash nothing (never advance with an empty binding).
 */

/** The public resolver path (non-`/v1`; nginx injects the api-key server-side). */
export const RESOLVE_ORG_PATH = '/public/resolve-org'

/** Where to bounce after a successful bind — the ALB Cognito-gates this route. */
export const POST_BIND_REDIRECT = '/overview'

/** Only `tenant_id` is echoed by the resolver — never the typed name or any counts. */
export interface ResolveOrgResponse {
  tenant_id: string
}

export interface SubmitOrgDeps {
  fetch: typeof fetch
  /** Bind the resolved tenant (defaults to the real sessionStorage-backed setter). */
  bind?: (tenantId: string) => void
  /** Full-page navigation (defaults to `window.location.assign`). */
  redirect?: (url: string) => void
}

export type SubmitOrgResult =
  | { status: 'ok'; tenantId: string; redirectedTo: string }
  | { status: 'not_found'; message: string }
  | { status: 'error'; message: string }

const NOT_FOUND_MSG = 'org not found — check spelling'
const ERROR_MSG = 'sign-in temporarily unavailable — try again'

export function resolveOrgUrl(org: string): string {
  return `${RESOLVE_ORG_PATH}?org=${encodeURIComponent(org.trim())}`
}

/**
 * Resolve an org name → bind + redirect (hit) or return a friendly miss/error.
 * Pure w.r.t. injected deps so `orgEntry.test.ts` can assert the branches without
 * touching the real network / storage / location.
 */
export async function submitOrg(org: string, deps: SubmitOrgDeps): Promise<SubmitOrgResult> {
  const name = org.trim()
  if (!name) return { status: 'error', message: ERROR_MSG }

  const bind = deps.bind ?? setActiveTenant
  const redirect = deps.redirect ?? ((url: string) => window.location.assign(url))

  let res: Response
  try {
    res = await deps.fetch(resolveOrgUrl(name), {
      method: 'GET',
      headers: { Accept: 'application/json' },
    })
  } catch {
    return { status: 'error', message: ERROR_MSG }
  }

  // Miss → stay, stash nothing, never advance to Cognito with an empty binding.
  if (res.status === 404) return { status: 'not_found', message: NOT_FOUND_MSG }
  if (!res.ok) return { status: 'error', message: ERROR_MSG }

  let data: unknown
  try {
    data = await res.json()
  } catch {
    return { status: 'error', message: ERROR_MSG }
  }

  // Validate the untrusted body: only a non-empty string tenant_id is honored.
  const tenantId =
    data && typeof data === 'object' && typeof (data as ResolveOrgResponse).tenant_id === 'string'
      ? (data as ResolveOrgResponse).tenant_id.trim()
      : ''
  if (!tenantId) return { status: 'error', message: ERROR_MSG }

  bind(tenantId)
  redirect(POST_BIND_REDIRECT)
  return { status: 'ok', tenantId, redirectedTo: POST_BIND_REDIRECT }
}

/**
 * Router guard predicate (G2.12): a signed-in MULTI-membership operator with no
 * bound tenant must be routed back to the org page — NEVER silently bound to a
 * primary. A single-membership operator needs no binding (the server picks the
 * sole membership), so it never redirects (no redirect-loop).
 */
export function needsOrgRedirect(
  me: Pick<MeContext, 'memberships'> | undefined | null,
  activeTenant: string | null,
): boolean {
  if (!me) return false
  const memberships = me.memberships ?? []
  return memberships.length > 1 && !activeTenant
}
