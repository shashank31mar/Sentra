import { describe, it, expect } from 'vitest'
import * as authModule from '../auth'
import { tenantLabelForDisplay } from '../auth'

/**
 * G1.1 — the cosmetic email-domain tenant label is display-only (FR-13.1). It is
 * renamed `tenantOf` → `tenantLabelForDisplay` and the old symbol is GONE (no
 * compat alias) so the G1.2 lint guard can never be side-stepped through it.
 */
describe('tenantLabelForDisplay (FR-13.1 cosmetic label)', () => {
  it('returns the email domain for display', () => {
    expect(tenantLabelForDisplay({ email: 'alice@acme.io', name: null, username: null, groups: [] })).toBe(
      'acme.io',
    )
  })

  it('returns null when there is no usable domain', () => {
    expect(tenantLabelForDisplay({ email: null, name: null, username: null, groups: [] })).toBeNull()
    expect(tenantLabelForDisplay({ email: 'noatsign', name: null, username: null, groups: [] })).toBeNull()
    expect(tenantLabelForDisplay(null)).toBeNull()
    expect(tenantLabelForDisplay(undefined)).toBeNull()
  })

  it('no longer exports the old tenantOf symbol', () => {
    expect((authModule as Record<string, unknown>).tenantOf).toBeUndefined()
  })
})
