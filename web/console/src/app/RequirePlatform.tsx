import type { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { useMe } from '../lib/query/useMe'
import { ROUTES } from './routes'
import { LoadingState } from '../components/ui/states'

/**
 * G4.1 — router-root guard for the platform (cross-tenant) tree.
 *
 * Gates on the operator's `is_platform` boolean — NOT a Capability/role (a tenant
 * `owner` is NOT a platform operator). FAIL-SECURE: any non-`true` value (false AND
 * absent) redirects to the customer overview, so a hand-typed `/platform` URL by a
 * customer never mounts a platform view. The `/v1/me` mock falls back to
 * `is_platform:false`, so a `/v1/me` outage correctly denies the tree rather than
 * exposing it. While `/v1/me` is loading we hold a spinner (never flash the tree).
 */
export function RequirePlatform({ children }: { children: ReactNode }) {
  const { data: me, isLoading } = useMe()

  if (isLoading) return <LoadingState label="Loading…" />
  if (me?.is_platform !== true) return <Navigate to={ROUTES.overview} replace />
  return <>{children}</>
}
