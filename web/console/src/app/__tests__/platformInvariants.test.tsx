import { describe, it, expect } from 'vitest'
import { NAV_GROUPS, PLATFORM_NAV_GROUPS, NAV_ITEMS } from '../navConfig'
import { ROUTES } from '../routes'

/**
 * G4.8 — four structural invariants of the platform console, enforced at the
 * config level (belt-and-suspenders to the router-root RequirePlatform guard):
 *  1. no import route in the platform tree;
 *  2. no per-tenant mutation nav entry (platform nav is read-only surfaces);
 *  3. no tenant selector (asserted in TopBar.test — the switcher is deleted);
 *  4. the customer nav never links into /platform (a customer can't discover it).
 */
describe('platform console invariants (G4.8)', () => {
  const platformLinks = PLATFORM_NAV_GROUPS.flatMap((g) => g.items).map((i) => i.to)

  it('customer nav omits any /platform link', () => {
    const customerLinks = NAV_ITEMS.map((i) => i.to)
    expect(customerLinks.some((to) => to.startsWith('/platform'))).toBe(false)
  })

  it('platform nav contains no import route', () => {
    expect(platformLinks).not.toContain(ROUTES.import)
    expect(platformLinks.some((to) => to.includes('/import'))).toBe(false)
  })

  it('platform nav only exposes read-only fleet + roadmap surfaces', () => {
    expect(platformLinks.sort()).toEqual(
      [
        ROUTES.platformOverview,
        ROUTES.platformTenants,
        ROUTES.platformTopology,
        ROUTES.platformHealth,
      ].sort(),
    )
  })

  it('customer nav groups are unchanged (no platform group leaked in)', () => {
    expect(NAV_GROUPS.map((g) => g.title)).not.toContain('Fleet')
  })
})
