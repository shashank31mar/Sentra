import { http } from '../http'
import type { PlatformTenantsResponse, PlatformTenantDetail } from '../../types/api'

/**
 * Platform (cross-tenant) API client — M-G4.
 *
 * INVARIANT: these calls MUST NOT attach `X-Aegion-Tenant`. `http.request` adds
 * `tenantHeader()` automatically, but a platform operator has NO active tenant
 * (org-first, M-G2) so the header is absent and the server's `_operator_read_scope`
 * takes the fleet path (`tenant_id=None`) + server-side audit. Never set an active
 * tenant in the platform tree, and never reach a tenant's data via the break-glass
 * `X-Aegion-Tenant` header — metadata drill-down uses the `/platform/tenants/{id}`
 * path param only (a different, non-forensic contract).
 */
export const platformApi = {
  listTenants: (params?: { limit?: number; cursor?: string; sort?: string; filter?: string }) =>
    http.get<PlatformTenantsResponse>('/platform/tenants', params),

  tenantDetail: (id: string) =>
    http.get<PlatformTenantDetail>(`/platform/tenants/${encodeURIComponent(id)}`),
}
