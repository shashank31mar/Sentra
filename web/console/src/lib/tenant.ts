/**
 * Active-tenant selection for multi-membership operators (LLD-26 WS-C C1).
 *
 * The console is tenant-blind by default: the server resolves the operator's
 * tenant from their Cognito session (the `is_primary` membership). A multi-tenant
 * operator (Sentra admin, or a partner managing several customers) can switch via
 * the `X-Aegion-Tenant` header — which the server **validates against their
 * membership set** before honoring (403 if not a member). The tenant is therefore
 * NEVER a trusted client parameter: this is a *preference*, not an authorization.
 *
 * Held here (module state + localStorage) so the http layer can attach the header
 * and the switcher can read/update it. Empty ⇒ no header ⇒ server uses the primary.
 */
const STORAGE_KEY = 'aegion:active-tenant'

let _active: string | null = readInitial()
const listeners = new Set<() => void>()

function readInitial(): string | null {
  try {
    return window.localStorage.getItem(STORAGE_KEY) || null
  } catch {
    return null
  }
}

/** The header value to send (or null to omit and let the server pick primary). */
export function getActiveTenant(): string | null {
  return _active
}

export function setActiveTenant(tenantId: string | null): void {
  _active = tenantId || null
  try {
    if (_active) window.localStorage.setItem(STORAGE_KEY, _active)
    else window.localStorage.removeItem(STORAGE_KEY)
  } catch {
    /* private mode / disabled storage — module state still works for the session */
  }
  listeners.forEach((fn) => fn())
}

/** Subscribe to switches (used by the React store binding). Returns an unsubscribe. */
export function subscribeActiveTenant(fn: () => void): () => void {
  listeners.add(fn)
  return () => listeners.delete(fn)
}

/** Header map for the http layer — omitted entirely when no explicit tenant is set. */
export function tenantHeader(): Record<string, string> {
  return _active ? { 'X-Aegion-Tenant': _active } : {}
}
