import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { useMe, useCan } from '../lib/query/useMe'
import { ROUTES } from './routes'
import { LoadingState } from '../components/ui/states'
import type { Capability } from '../lib/rbac'

/**
 * FX-2.2 — route-level RBAC render-gate for a deep-linkable mutating page (e.g. the
 * PolicyEditor, reachable by URL). A viewer who deep-links a write route is bounced
 * to the read-only overview instead of mounting a form they can't submit. FAIL-SECURE:
 * while `/v1/me` loads we hold a spinner (never flash the gated page); a missing role
 * (`can()` false) redirects. This is UX-only defense-in-depth — the server
 * `require_role` on the mutation remains the boundary; a tampered client gains nothing.
 */
export function RequireCan({ cap, children }: { cap: Capability; children: ReactNode }) {
  const { isLoading } = useMe()
  const can = useCan()

  if (isLoading) return <LoadingState label="Loading…" />
  if (!can(cap)) return <Navigate to={ROUTES.overview} replace />
  return <>{children}</>
}
