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
 *   admin  — CRUD agents/policies/members/credentials (no delete tenant)
 *   editor — import + policy CRUD; rotate credentials; read members
 *   viewer — read-only
 */
const RANK: Record<TenantRole, number> = { viewer: 0, editor: 1, admin: 2, owner: 3 }

/** Capabilities the UI gates on. */
export type Capability =
  | 'agents.write' // import / edit agents
  | 'policies.write' // create/edit/delete policies
  | 'credentials.rotate'
  | 'credentials.write' // register / revoke
  | 'members.read'
  | 'members.manage'
  | 'tenant.delete'

const MIN_ROLE: Record<Capability, TenantRole> = {
  'agents.write': 'editor',
  'policies.write': 'editor',
  'credentials.rotate': 'editor',
  'credentials.write': 'admin',
  'members.read': 'editor',
  'members.manage': 'admin',
  'tenant.delete': 'owner',
}

export function roleSatisfies(have: TenantRole | undefined | null, need: TenantRole): boolean {
  if (!have) return false
  return RANK[have] >= RANK[need]
}

/** Whether a role may perform a capability (render gate only). */
export function can(role: TenantRole | undefined | null, cap: Capability): boolean {
  return roleSatisfies(role, MIN_ROLE[cap])
}
