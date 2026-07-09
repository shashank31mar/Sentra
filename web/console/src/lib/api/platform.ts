import { http } from '../http'
import type { PlatformTenantsResponse, PlatformTenantDetail } from '../../types/api'

/**
 * Platform (cross-tenant) API client — M-G4.
 *
 * INVARIANT (FX-2.3): these calls MUST NOT attach `X-Aegion-Tenant`. Enforced by
 * CODE — every call passes `{ omitTenant: true }`, so the http layer drops the
 * header even if a tenant is ambiently bound. The server's `_operator_read_scope`
 * then takes the fleet path (`tenant_id=None`) + server-side audit. (Previously the
 * invariant held only *because* a platform operator happened to have no active
 * tenant — luck, not enforcement.) Never reach a tenant's data via the break-glass
 * `X-Aegion-Tenant` header — metadata drill-down uses the `/platform/tenants/{id}`
 * path param only (a different, non-forensic contract).
 */
const PLATFORM_OPTS = { omitTenant: true } as const

export const platformApi = {
  listTenants: (params?: { limit?: number; cursor?: string; sort?: string; filter?: string }) =>
    http.get<PlatformTenantsResponse>('/platform/tenants', params, PLATFORM_OPTS),

  tenantDetail: (id: string) =>
    http.get<PlatformTenantDetail>(
      `/platform/tenants/${encodeURIComponent(id)}`,
      undefined,
      PLATFORM_OPTS,
    ),
}
