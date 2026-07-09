import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { setActiveTenant, clearActiveTenant } from '../../tenant'
import { platformApi } from '../platform'

/**
 * FX-2.3 — the platformApi `X-Aegion-Tenant` invariant is now CODE-ENFORCED, not
 * environmental. The old test was circular: it `clearActiveTenant()`d then asserted
 * absence (proving nothing about enforcement). This SETS an active tenant and asserts
 * platformApi STILL sends no tenant header — the `{ omitTenant: true }` code path.
 */

function okJson(body: unknown): Response {
  return { ok: true, status: 200, type: 'basic', json: async () => body } as unknown as Response
}

describe('platformApi tenant-header invariant is code-enforced (FX-2.3)', () => {
  const fetchSpy = vi.fn()

  beforeEach(() => {
    window.sessionStorage.clear()
    fetchSpy.mockReset()
    fetchSpy.mockResolvedValue(okJson({ count: 0, tenants: [] }))
    vi.stubGlobal('fetch', fetchSpy)
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    clearActiveTenant()
  })

  function headersOf(call: number): Record<string, string> {
    const init = fetchSpy.mock.calls[call]?.[1] as RequestInit
    return (init?.headers ?? {}) as Record<string, string>
  }

  it('listTenants sends NO X-Aegion-Tenant EVEN WITH an active tenant bound', async () => {
    // The non-circular assertion: a tenant IS ambiently bound…
    setActiveTenant('t_acme')
    await platformApi.listTenants()
    // …yet the platform call still omits the header (code-enforced omitTenant).
    expect(headersOf(0)['X-Aegion-Tenant']).toBeUndefined()
  })

  it('tenantDetail also omits the header with an active tenant bound', async () => {
    setActiveTenant('t_globex')
    await platformApi.tenantDetail('t_target')
    const url = fetchSpy.mock.calls[0][0] as string
    expect(url).toContain('/platform/tenants/t_target')
    expect(headersOf(0)['X-Aegion-Tenant']).toBeUndefined()
  })

  it('a NON-platform call (control) DOES send the header — proving the omit is specific', async () => {
    // Sanity: prove the header machinery works, so the omit above is meaningful and
    // not a test that would pass even if tenantHeader() were globally broken.
    const { http } = await import('../../http')
    setActiveTenant('t_acme')
    await http.get('/agents')
    expect(headersOf(0)['X-Aegion-Tenant']).toBe('t_acme')
  })
})
