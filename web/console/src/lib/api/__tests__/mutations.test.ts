import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { decisionsApi } from '../decisions'
import { sessionsApi } from '../sessions'

/**
 * M-G3.13 (D8) — the verdict / quarantine / release calls must send NO
 * `operator_id`: the server attributes the operator from the verified `ctx.sub`,
 * never a spoofable client field. These assert the wire bodies/paths are clean.
 */
describe('mutation bodies omit operator_id (M-G3.13)', () => {
  const fetchSpy = vi.fn()
  beforeEach(() => {
    fetchSpy.mockReset()
    fetchSpy.mockResolvedValue({ ok: true, status: 200, type: 'basic', json: async () => ({}) } as Response)
    vi.stubGlobal('fetch', fetchSpy)
  })
  afterEach(() => vi.unstubAllGlobals())

  function bodyOf(call: number): Record<string, unknown> {
    const init = fetchSpy.mock.calls[call]?.[1] as RequestInit
    return init?.body ? (JSON.parse(init.body as string) as Record<string, unknown>) : {}
  }

  it('verdict body has verdict+reason and NO operator_id', async () => {
    await decisionsApi.verdict('s1:r1', { verdict: 'false_positive', reason: 'review' })
    const body = bodyOf(0)
    expect(body).toEqual({ verdict: 'false_positive', reason: 'review' })
    expect(body).not.toHaveProperty('operator_id')
  })

  it('quarantine body has reason and NO operator_id', async () => {
    await decisionsApi.quarantine('s1', { reason: 'review' })
    const body = bodyOf(0)
    expect(body).toEqual({ reason: 'review' })
    expect(body).not.toHaveProperty('operator_id')
  })

  it('release DELETE path carries no operator_id query param', async () => {
    await sessionsApi.release('s1')
    const url = fetchSpy.mock.calls[0][0] as string
    expect(url).toContain('/quarantine/s1')
    expect(url).not.toContain('operator_id')
  })
})
