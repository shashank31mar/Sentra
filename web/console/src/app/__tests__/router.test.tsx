import { describe, it, expect } from 'vitest'
import { ROUTES } from '../routes'

/**
 * M-G3.0 (integ) — the four new/promoted paths are registered under the customer
 * shell with the correct patterns. (Full lazy-mount is exercised by each page's own
 * test; here we pin the route contract so a link built by ActivityPage resolves.)
 */
describe('router route contract (M-G3.0)', () => {
  it('registers activity / decisionDetail(composite) / sessionDetail / usage', () => {
    expect(ROUTES.activity).toBe('/activity')
    expect(ROUTES.decisionDetail).toBe('/decisions/:sessionId/:requestId')
    expect(ROUTES.sessionDetail).toBe('/sessions/:sessionId')
    expect(ROUTES.usage).toBe('/usage')
  })
})
