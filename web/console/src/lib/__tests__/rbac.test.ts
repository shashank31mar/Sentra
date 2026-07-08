import { describe, it, expect } from 'vitest'
import { can, platformCan, roleSatisfies, MIN_ROLE, RANK } from '../rbac'
import type { Capability, PlatformCapability } from '../rbac'
import type { TenantRole } from '../../types/api'

/**
 * G2.1 — the client capability map mirrors the server `require_role` matrix. These
 * pin the new caps and prove `sigma.retire` gates on `is_platform`, not a role.
 */
describe('rbac capability map (G2.1)', () => {
  it('gates policies.delete at admin (stricter than write)', () => {
    expect(can('viewer', 'policies.delete')).toBe(false)
    expect(can('editor', 'policies.delete')).toBe(false)
    expect(can('admin', 'policies.delete')).toBe(true)
    expect(can('owner', 'policies.delete')).toBe(true)
  })

  it('gates decisions.verdict at editor', () => {
    expect(can('viewer', 'decisions.verdict')).toBe(false)
    expect(can('editor', 'decisions.verdict')).toBe(true)
  })

  it('gates connections write=admin, operate=editor', () => {
    expect(can('editor', 'connections.write')).toBe(false)
    expect(can('admin', 'connections.write')).toBe(true)
    expect(can('editor', 'connections.operate')).toBe(true)
    expect(can('viewer', 'connections.operate')).toBe(false)
  })

  it('gates quarantine.manage at admin', () => {
    expect(can('editor', 'quarantine.manage')).toBe(false)
    expect(can('admin', 'quarantine.manage')).toBe(true)
  })

  it('keeps identity.residual.read at the viewer floor', () => {
    expect(can('viewer', 'identity.residual.read')).toBe(true)
  })

  it('sigma.retire gates on is_platform, never a role', () => {
    expect(platformCan(true, 'sigma.retire')).toBe(true)
    expect(platformCan(false, 'sigma.retire')).toBe(false)
    expect(platformCan(undefined, 'sigma.retire')).toBe(false)
    expect(platformCan(null, 'sigma.retire')).toBe(false)
  })

  it('RANK is the frozen server order viewer<editor<admin<owner', () => {
    expect(RANK).toEqual({ viewer: 0, editor: 1, admin: 2, owner: 3 })
    expect(roleSatisfies('admin', 'editor')).toBe(true)
    expect(roleSatisfies('editor', 'admin')).toBe(false)
    expect(roleSatisfies(null, 'viewer')).toBe(false)
  })

  it('MIN_ROLE is an exhaustive Record<Capability,TenantRole>', () => {
    // TS-level exhaustiveness guard: this satisfies-assertion must compile.
    const _check = MIN_ROLE satisfies Record<Capability, TenantRole>
    expect(Object.keys(_check).length).toBeGreaterThanOrEqual(14)
    // No Capability is missing its role.
    for (const role of Object.values(MIN_ROLE)) {
      expect(['viewer', 'editor', 'admin', 'owner']).toContain(role)
    }
  })

  it('PlatformCapability is a distinct type (compile-time only)', () => {
    const cap: PlatformCapability = 'sigma.retire'
    expect(cap).toBe('sigma.retire')
  })
})
