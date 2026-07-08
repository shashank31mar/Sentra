import { useEffect, type ReactNode } from 'react'
import { useMe } from '../lib/query/useMe'
import { getActiveTenant } from '../lib/tenant'
import { needsOrgRedirect } from '../lib/orgEntry'
import { LoadingState } from '../components/ui/states'

/** The static org-first page (NOT an SPA route — full-page navigation). */
export const ORG_PAGE_PATH = '/org.html'

/**
 * G2.12 router guard: a signed-in MULTI-membership operator with no bound tenant
 * is sent back to the org page — fail-safe, NEVER a silent primary bind (the exact
 * cross-tenant footgun ADR-039 closes). A single-membership operator is fine (the
 * server resolves the sole membership), so it renders straight through. While
 * `/v1/me` is loading we hold a spinner rather than flash the shell.
 *
 * This is defense-in-depth on the client; the server `resolve_operator_tenant`
 * + `X-Aegion-Tenant` membership check remain the authority.
 */
export function RequireBoundTenant({ children }: { children: ReactNode }) {
  const { data: me, isLoading } = useMe()
  const active = getActiveTenant()
  const redirect = needsOrgRedirect(me, active)

  useEffect(() => {
    if (redirect) window.location.assign(ORG_PAGE_PATH)
  }, [redirect])

  if (isLoading) return <LoadingState label="Loading…" />
  if (redirect) return <LoadingState label="Select your organization…" />
  return <>{children}</>
}
