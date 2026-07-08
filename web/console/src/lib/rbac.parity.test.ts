import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { MIN_ROLE, RANK, PLATFORM_MIN } from './rbac'
import type { Capability, PlatformCapability } from './rbac'
import type { TenantRole } from '../types/api'

/**
 * G2.9 — client↔server RBAC parity + completeness (D3).
 *
 * Consumes `__fixtures__/role-model.json`, EMITTED BY THE BACKEND LANE (B2.1) from
 * a `require_role`/`require_platform` route walk. This is the hard cross-lane gate:
 *  (a) RANK order === fixture `rank`;
 *  (b) for every server route, the mapped client cap's MIN_ROLE === fixture min_role
 *      (or is a PlatformCapability for `platform:true` rows);
 *  (c) completeness — every fixture route is either mapped to a client cap OR
 *      explicitly allowlisted as a deliberately console-less mutation.
 *
 * If the fixture is ABSENT (backend prereq not landed) this FAILS LOUD — never
 * skips — because a silent skip re-opens the exact parity drift this gate closes.
 */

interface FixtureRoute {
  path: string
  method: string
  min_role?: TenantRole
  platform?: boolean
}
interface RoleModel {
  rank: TenantRole[]
  minRole: Record<TenantRole, number>
  routes: FixtureRoute[]
}

const FIXTURE_PATH = path.join(process.cwd(), 'src', 'lib', '__fixtures__', 'role-model.json')

function loadFixture(file = FIXTURE_PATH): RoleModel {
  if (!fs.existsSync(file)) {
    throw new Error(
      `role-model.json missing at ${file} — backend D3 generator (B2.1) not run. ` +
        `The parity gate cannot verify client↔server RBAC without it. FAIL LOUD, not skip.`,
    )
  }
  return JSON.parse(fs.readFileSync(file, 'utf-8')) as RoleModel
}

const routeKey = (r: { method: string; path: string }) => `${r.method.toUpperCase()} ${r.path}`

/**
 * Server route → client Capability. A route with a rendered console control maps
 * to a cap; the client MIN_ROLE for that cap must equal the fixture's min_role.
 */
const ROUTE_TO_CAP: Record<string, Capability> = {
  'POST /v1/agents/{agent_id}/credentials': 'credentials.write',
  'DELETE /v1/agents/{agent_id}/credentials/{kid}': 'credentials.write',
  'POST /v1/agents/{agent_id}/credentials/{kid}/rotate': 'credentials.rotate',
  'POST /v1/agents/{agent_id}/policies': 'agents.write',
  'DELETE /v1/agents/{agent_id}/policies/{policy_id}': 'agents.write',
  'POST /v1/connections': 'connections.write',
  'DELETE /v1/connections/{connection_id}': 'connections.write',
  'PUT /v1/connections/{connection_id}': 'connections.write',
  'POST /v1/connections/{connection_id}/scan': 'connections.operate',
  'POST /v1/connections/{connection_id}/test': 'connections.operate',
  'POST /v1/decisions/{decision_id}/verdict': 'decisions.verdict',
  'POST /v1/discovery/import': 'agents.write',
  'POST /v1/policies': 'policies.write',
  'DELETE /v1/policies/{policy_id}': 'policies.delete',
  'PUT /v1/policies/{policy_id}': 'policies.write',
  'PATCH /v1/policies/{policy_id}/status': 'policies.write',
  'DELETE /v1/quarantine/{session_id}': 'quarantine.manage',
  'POST /v1/quarantine/{session_id}': 'quarantine.manage',
  'DELETE /v1/tenants/{tenant_id}': 'tenant.delete',
  'PATCH /v1/tenants/{tenant_id}': 'tenant.manage',
  'POST /v1/tenants/{tenant_id}/invites': 'members.manage',
  'GET /v1/tenants/{tenant_id}/members': 'members.read',
  'DELETE /v1/tenants/{tenant_id}/members/{operator_sub}': 'members.manage',
}

/** Server `require_platform` route → client PlatformCapability. */
const ROUTE_TO_PLATFORM_CAP: Record<string, PlatformCapability> = {
  'PATCH /v1/sigma-rules/{rule_id}': 'sigma.retire',
}

/**
 * Deliberately console-LESS mutations (no rendered control) — allowlisted so the
 * completeness walk passes. MUST NEVER hold a tenant-partitioned READ (that is the
 * D10 read-side gate, backend-owned) — only mutations with no UI control today.
 */
const NO_CONSOLE_ROUTES = new Set<string>([
  'POST /v1/rollback', // roadmap; admin; no control
  'POST /v1/rollback/conversation/{conversation_id}', // roadmap; admin; no control
  'DELETE /v1/feedback/subjects/{subject_locator}', // GDPR erase; not a console control
  'GET /v1/platform/tenants', // platform read — audited server-side; mounted via platform tree, not a cap gate
  'GET /v1/platform/tenants/{tenant_id}', // platform read — audited server-side
])

describe('RBAC client↔server parity + completeness (G2.9, D3)', () => {
  it('loads the backend-emitted fixture (fails loud if absent)', () => {
    expect(() => loadFixture()).not.toThrow()
  })

  it('(a) RANK order mirrors the fixture rank + minRole', () => {
    const model = loadFixture()
    const orderedRank = [...model.rank]
    // RANK values are the index in the frozen server order.
    for (const role of orderedRank) {
      expect(RANK[role]).toBe(model.minRole[role])
    }
    expect(orderedRank).toEqual(['viewer', 'editor', 'admin', 'owner'])
  })

  it('(b) every mapped route: client MIN_ROLE === fixture min_role', () => {
    const model = loadFixture()
    for (const route of model.routes) {
      const key = routeKey(route)
      if (route.platform) {
        // platform rows: mapped to a PlatformCapability or allowlisted
        if (ROUTE_TO_PLATFORM_CAP[key]) {
          expect(PLATFORM_MIN[ROUTE_TO_PLATFORM_CAP[key]]).toBe(true)
        }
        continue
      }
      const cap = ROUTE_TO_CAP[key]
      if (!cap) continue // completeness handled below
      expect(
        MIN_ROLE[cap],
        `min_role mismatch for ${key}: client cap "${cap}"=${MIN_ROLE[cap]} vs fixture=${route.min_role}`,
      ).toBe(route.min_role)
    }
  })

  it('(c) completeness — every require_role/require_platform route is mapped or allowlisted', () => {
    const model = loadFixture()
    const unmapped: string[] = []
    for (const route of model.routes) {
      const key = routeKey(route)
      const mapped =
        (route.platform && ROUTE_TO_PLATFORM_CAP[key]) ||
        (!route.platform && ROUTE_TO_CAP[key]) ||
        NO_CONSOLE_ROUTES.has(key)
      if (!mapped) unmapped.push(key)
    }
    expect(unmapped, `unmapped server routes (map a cap or allowlist): ${unmapped.join(', ')}`).toEqual([])
  })

  it('negative: a seeded min_role mismatch (role-model.bad.json) fails the parity assertion', () => {
    const badPath = path.join(process.cwd(), 'src', 'lib', '__fixtures__', 'role-model.bad.json')
    const bad = loadFixture(badPath)
    // The bad fixture flips POST /credentials to viewer; the client cap is admin.
    let mismatchDetected = false
    for (const route of bad.routes) {
      const cap = ROUTE_TO_CAP[routeKey(route)]
      if (!cap || route.platform) continue
      if (MIN_ROLE[cap] !== route.min_role) mismatchDetected = true
    }
    expect(mismatchDetected).toBe(true)
  })
})
