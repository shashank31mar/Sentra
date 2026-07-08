import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { setActiveTenant, clearActiveTenant } from '../../tenant'

// Ensure real fetch path (not the mock router) — VITE_DATA_SOURCE unset in tests.
import { platformApi } from '../platform'

function okJson(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    type: 'basic',
    json: async () => body,
  } as unknown as Response
}

describe('platformApi — no X-Aegion-Tenant header (G4.2 invariant)', () => {
  const fetchSpy = vi.fn()

  beforeEach(() => {
    clearActiveTenant()
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

  it('listTenants hits /platform/tenants with NO tenant header (platform tree has no active tenant)', async () => {
    // The G4.2 invariant is structural: a platform operator has NO active tenant
    // (org-first), so tenantHeader() is empty and the fleet path is taken server-side.
    expect(setActiveTenant).toBeTypeOf('function') // (imported to document the seam)
    await platformApi.listTenants()
    const url = fetchSpy.mock.calls[0][0] as string
    expect(url).toContain('/platform/tenants')
    const headers = headersOf(0) as Record<string, string>
    expect(headers['X-Aegion-Tenant']).toBeUndefined()
  })

  it('tenantDetail encodes the id in the path', async () => {
    await platformApi.tenantDetail('t globex/1')
    const url = fetchSpy.mock.calls[0][0] as string
    expect(url).toContain('/platform/tenants/t%20globex%2F1')
  })
})
