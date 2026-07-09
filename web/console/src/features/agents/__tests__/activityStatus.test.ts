import { describe, it, expect } from 'vitest'
import { activityStatus, IDLE_AFTER_MS } from '../activityStatus'

/**
 * FX-1.4 — the ECS→canvas activity mapper. Fixtures use the REAL server ECS values
 * (`running`/`starting`/`stopped`/`not_found`/`unknown` — `agent_service.py`), NOT
 * the canvas enum. Critically: an `unknown` status must NEVER read as Active.
 */
describe('activityStatus (FX-1.4)', () => {
  const NOW = Date.parse('2026-07-09T12:00:00Z')
  const recent = new Date(NOW - 60_000).toISOString() // 1 min ago
  const stale = new Date(NOW - IDLE_AFTER_MS - 60_000).toISOString() // > idle window

  it('running + recent traffic → Active', () => {
    expect(activityStatus('running', recent, NOW)).toBe('Active')
  })

  it('running + NO recent traffic → Idle (service up but quiet)', () => {
    expect(activityStatus('running', stale, NOW)).toBe('Idle')
    expect(activityStatus('running', null, NOW)).toBe('Idle')
  })

  it('starting → Idle', () => {
    expect(activityStatus('starting', recent, NOW)).toBe('Idle')
  })

  it('stopped and not_found → Offline', () => {
    expect(activityStatus('stopped', recent, NOW)).toBe('Offline')
    expect(activityStatus('not_found', recent, NOW)).toBe('Offline')
  })

  it('unknown → Unknown, NEVER Active (even with recent traffic)', () => {
    expect(activityStatus('unknown', recent, NOW)).toBe('Unknown')
  })

  it("leaked DynamoDB 'active' metadata → Unknown, NEVER Active (transient ECS-probe failure)", () => {
    // agent_service.py:229-231 keeps the un-enriched agent (status='active') when the
    // per-agent ECS probe throws — that static registry value is NOT a live runtime
    // state. It must map to Unknown (fail honest), never Active, even with fresh traffic.
    expect(activityStatus('active', recent, NOW)).toBe('Unknown')
    expect(activityStatus('active', stale, NOW)).toBe('Unknown')
    expect(activityStatus('active', null, NOW)).toBe('Unknown')
  })

  it('an unexpected/garbage status falls through to Unknown, not Active', () => {
    expect(activityStatus('some_future_state', recent, NOW)).toBe('Unknown')
    expect(activityStatus(undefined, recent, NOW)).toBe('Unknown')
    expect(activityStatus(null, recent, NOW)).toBe('Unknown')
  })

  it('a malformed last_seen timestamp is treated as no recent traffic (Idle, not Active)', () => {
    expect(activityStatus('running', 'not-a-date', NOW)).toBe('Idle')
  })
})
