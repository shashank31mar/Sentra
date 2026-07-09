import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { useMe } from '../lib/query/useMe'
import { ROUTES } from './routes'
import { LoadingState } from '../components/ui/states'

/**
 * FX-2.5 — symmetric root-split confinement (lld/40 §3.1). `RequirePlatform` already
 * keeps a customer OUT of `/platform`; this is the mirror that keeps a PLATFORM
 * operator out of the customer tree: an `is_platform` operator hitting `/` or any
 * customer route is redirected to `/platform` (their exclusive root), so they never
 * mount the customer tenant shell. While `/v1/me` loads we hold a spinner (never
 * flash the customer shell). A non-platform operator renders straight through.
 */
export function RequireCustomerRoot({ children }: { children: ReactNode }) {
  const { data: me, isLoading } = useMe()

  if (isLoading) return <LoadingState label="Loading…" />
  if (me?.is_platform === true) return <Navigate to={ROUTES.platformOverview} replace />
  return <>{children}</>
}
