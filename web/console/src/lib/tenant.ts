/**
 * Active-tenant binding for multi-membership operators (LLD-26 WS-C C1, ADR-039
 * org-first). The console is tenant-blind by default: the server resolves the
 * operator's tenant from their Cognito session. A multi-tenant operator (Sentra
 * admin / partner) binds a tenant at login (org-first, G2.12) which rides the
 * `X-Aegion-Tenant` header — which the server **validates against their membership
 * set** before honoring (403 if not a member). The tenant is therefore NEVER a
 * trusted client parameter: this is a *preference*, not an authorization.
 *
 * ADR-039: the binding lives in **`sessionStorage` (per-tab)** — not `localStorage`
 * — so a partner operator's org selection is scoped to the tab and cleared on tab
 * close, never riding along a stale other-tenant value into a new session. Held as
 * module state too so the http layer can attach the header synchronously.
 * Empty ⇒ no header ⇒ server uses the sole membership (single-tenant) OR, for a
 * multi-membership operator, the org page rebinds (G2.12) — never a silent primary.
 */
/**
 * The per-tab ADR-039 storage key. This module is the storage AUTHORITY (the only
 * place the console reads/writes it). `public/org.html` re-declares the same string
 * inline as `TENANT_KEY` (it can't import this module — it loads no bundle); the
 * `orgEntry.parity.test.ts` gate asserts the two stay in lockstep against this
 * exported constant, so a change on one side without the other fails the suite.
 */
export const ACTIVE_TENANT_STORAGE_KEY = 'aegion.activeTenant'
const STORAGE_KEY = ACTIVE_TENANT_STORAGE_KEY

let _active: string | null = readInitial()
const listeners = new Set<() => void>()

function readInitial(): string | null {
  try {
    return window.sessionStorage.getItem(STORAGE_KEY) || null
  } catch {
    return null
  }
}

/** The header value to send (or null to omit and let the server pick). */
export function getActiveTenant(): string | null {
  return _active
}

export function setActiveTenant(tenantId: string | null): void {
  _active = tenantId || null
  try {
    if (_active) window.sessionStorage.setItem(STORAGE_KEY, _active)
    else window.sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    /* private mode / disabled storage — module state still works for the session */
  }
  listeners.forEach((fn) => fn())
}

/** Clear the per-tab binding (called on reauthenticate/logout — see http.ts). */
export function clearActiveTenant(): void {
  setActiveTenant(null)
}

/** Subscribe to binding changes (used by the React store binding). Returns an unsubscribe. */
export function subscribeActiveTenant(fn: () => void): () => void {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

/** Header map for the http layer — omitted entirely when no explicit tenant is set. */
export function tenantHeader(): Record<string, string> {
  return _active ? { 'X-Aegion-Tenant': _active } : {}
}
