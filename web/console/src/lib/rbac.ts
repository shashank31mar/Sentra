import type { TenantRole } from '../types/api'

/**
 * Client-side RBAC mirror (LLD-26 §5.4 / §6.3).
 *
 * IMPORTANT: this gates *rendering* only, so a viewer never sees a control they
 * can't use. It is NEVER the authorization boundary — every mutation is still
 * authorized server-side by `require_role`, so a tampered client gains nothing.
 *
 * Mirrors the server matrix exactly:
 *   owner  — everything incl. delete tenant
 *   admin  — CRUD agents/policies/members/credentials; read members; delete policy;
 *            manage quarantine + connections write; update tenant (no delete tenant)
 *   editor — import + policy create/edit; rotate credentials; verdict; connection test/scan
 *   viewer — read-only
 */
const RANK: Record<TenantRole, number> = { viewer: 0, editor: 1, admin: 2, owner: 3 }

/** Capabilities the UI gates on. Each maps 1:1 to a server `require_role` route
 *  (see the G2.9 parity test + `role-model.json`). */
export type Capability =
  | 'agents.write' // import / edit agents
  | 'policies.write' // create/edit policies (editor)
  | 'policies.delete' // delete a policy (admin — server is stricter than write)
  | 'credentials.rotate'
  | 'credentials.write' // register / revoke
  | 'members.read'
  | 'members.manage'
  | 'tenant.delete'
  | 'tenant.manage' // PATCH /tenants/{id} update (admin)
  | 'decisions.verdict' // POST /decisions/{id}/verdict (editor)
  | 'quarantine.manage' // POST + DELETE /quarantine/{id} (admin)
  | 'connections.write' // POST/PUT/DELETE /connections (admin)
  | 'connections.operate' // POST /connections/{id}/{test,scan} (editor)
  | 'identity.residual.read' // view the WS-B fallback-window residual-agent list

// Exhaustive: adding a Capability member without a MIN_ROLE entry fails `tsc -b`.
const MIN_ROLE: Record<Capability, TenantRole> = {
  'agents.write': 'editor',
  'policies.write': 'editor',
  'policies.delete': 'admin',
  'credentials.rotate': 'editor',
  'credentials.write': 'admin',
  // Server `GET /tenants/{id}/members` is admin-gated (role-model.json / G2.9
  // parity) — mirror it exactly; do not relax to editor.
  'members.read': 'admin',
  'members.manage': 'admin',
  'tenant.delete': 'owner',
  'tenant.manage': 'admin',
  'decisions.verdict': 'editor',
  'quarantine.manage': 'admin',
  'connections.write': 'admin',
  'connections.operate': 'editor',
  // Read-only operational view; the backend lets any role see it (it's their own
  // tenant's residual agents). viewer is the floor.
  'identity.residual.read': 'viewer',
}

/**
 * Platform-only capability — gated on the operator's `is_platform` boolean, NOT a
 * `TenantRole`. Kept OUT of the `Capability` union deliberately (§5.1): it has no
 * valid `MIN_ROLE[cap]` and would break the exhaustive tenant-role map. Mirrors the
 * server `require_platform` routes (e.g. `PATCH /sigma-rules/{id}`).
 */
export type PlatformCapability = 'sigma.retire'

// Every platform capability requires `is_platform === true`. Kept as an explicit
// map so a future platform cap is added deliberately (parity test walks it).
export const PLATFORM_MIN: Record<PlatformCapability, true> = {
  'sigma.retire': true,
}

export function roleSatisfies(have: TenantRole | undefined | null, need: TenantRole): boolean {
  if (!have) return false
  return RANK[have] >= RANK[need]
}

/** Whether a role may perform a capability (render gate only). */
export function can(role: TenantRole | undefined | null, cap: Capability): boolean {
  return roleSatisfies(role, MIN_ROLE[cap])
}

/** Whether the operator may perform a platform capability (render gate only).
 *  Gates on `is_platform`; a tenant `owner`/`admin` is NOT a platform operator. */
export function platformCan(isPlatform: boolean | undefined | null, cap: PlatformCapability): boolean {
  return isPlatform === true && PLATFORM_MIN[cap] === true
}

// Re-exported for the G2.9 parity test (asserts MIN_ROLE == role-model.json).
export { MIN_ROLE, RANK }
