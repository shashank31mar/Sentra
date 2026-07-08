import { describe, it, expect } from 'vitest'
import { decisionDetailPath, sessionDetailPath, usagePath, ROUTES } from '../routes'

/**
 * M-G3.0 — the decision-detail path is the COMPOSITE PK (sessionId + requestId,
 * routes.py:554 keys `{session_id}#{request_id}`), each segment URL-encoded.
 */
describe('route path builders (M-G3.0)', () => {
  it('builds decisionDetailPath with encoded session + request ids', () => {
    expect(decisionDetailPath('s 1', 'r/2')).toBe('/decisions/s%201/r%2F2')
  })

  it('decisionDetail route pattern carries BOTH params (not requestId alone)', () => {
    expect(ROUTES.decisionDetail).toBe('/decisions/:sessionId/:requestId')
  })

  it('builds sessionDetailPath + usagePath', () => {
    expect(sessionDetailPath('sess-a')).toBe('/sessions/sess-a')
    expect(usagePath()).toBe('/usage')
  })
})
