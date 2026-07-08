import { useQuery } from '@tanstack/react-query'
import { platformApi } from '../api/platform'
import { queryKeys } from '../queryKeys'

export interface FleetTenantsParams {
  limit?: number
  cursor?: string
  sort?: string
  filter?: string
}

/** Fleet tenant grid (`GET /v1/platform/tenants`). Server auto-scopes fleet. */
export function useFleetTenants(params: FleetTenantsParams = {}) {
  return useQuery({
    queryKey: queryKeys.platform.tenants({ ...params }),
    queryFn: () => platformApi.listTenants(params),
  })
}

/**
 * Per-tenant metadata drill-down (`GET /v1/platform/tenants/{id}`). `retry:false`
 * so a 403 (consent required, PRE-G4-c) or 404 (not found) surfaces immediately as
 * a first-class empty state — never a retry storm + repeated DENY audit rows.
 */
export function useTenantDetail(id: string) {
  return useQuery({
    queryKey: queryKeys.platform.tenantDetail(id),
    queryFn: () => platformApi.tenantDetail(id),
    enabled: Boolean(id),
    retry: false,
  })
}
