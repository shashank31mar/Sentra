import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { http, ApiException } from '../http'
import { setActiveTenant, clearActiveTenant, getActiveTenant } from '../tenant'
import { ORG_PAGE_PATH } from '../orgEntry'

/**
 * FX-2.1 — lost-tenant-binding 403 fail-safe. A 403 whose server reason is
 * "not a member of requested tenant" (deps.py:440) — the bound `X-Aegion-Tenant` no
 * longer resolves to a membership — drops the binding + bounces to the org page. It
 * is keyed on the SERVER'S REASON, NOT the HTTP method: a role-403 ("requires role
 * >= …") must NOT clear the binding even when it lands on a role-gated GET (e.g. the
 * admin-gated `GET /tenants/{id}/members`, rbac.ts:44).
 */

function resp(status: number, body: unknown): Response {
  return {
    ok: status < 400,
    status,
    type: 'basic',
    json: async () => body,
  } as unknown as Response
}

const fetchSpy = vi.fn()
const assignSpy = vi.fn()

describe('http read-403 membership fail-safe (FX-2.1)', () => {
  beforeEach(() => {
    fetchSpy.mockReset()
    assignSpy.mockReset()
    window.sessionStorage.clear()
    vi.stubGlobal('fetch', fetchSpy)
    // window.location.assign — stub so the bounce doesn't navigate jsdom.
    Object.defineProperty(window, 'location', {
      configurable: true,
      value: { ...window.location, assign: assignSpy, href: 'http://localhost/overview' },
    })
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    clearActiveTenant()
  })

  it('a 403 on /v1/me clears the active tenant and bounces to the org page', async () => {
    setActiveTenant('t_stale')
    fetchSpy.mockResolvedValue(resp(403, { detail: 'not a member of requested tenant' }))

    await expect(http.get('/me')).rejects.toBeInstanceOf(ApiException)

    expect(getActiveTenant()).toBeNull() // binding dropped
    expect(assignSpy).toHaveBeenCalledWith(ORG_PAGE_PATH)
  })

  it('a 403 on a MUTATION (POST) does NOT clear the binding (role-403, not lost tenant)', async () => {
    setActiveTenant('t_ok')
    fetchSpy.mockResolvedValue(resp(403, { detail: 'requires role >= admin' }))

    await expect(http.post('/policies', { name: 'x' })).rejects.toBeInstanceOf(ApiException)

    expect(getActiveTenant()).toBe('t_ok') // binding preserved
    expect(assignSpy).not.toHaveBeenCalled()
  })

  // The wrong-branch regression guard: a ROLE-403 on a GET while a tenant is bound
  // (e.g. the admin-gated `GET /tenants/{id}/members`, rbac.ts:44). The old
  // method==='GET' discriminator would WRONGLY wipe the valid binding and eject the
  // operator to org selection. Keying on the server reason keeps the binding intact
  // and surfaces an honest 403. (This test FAILS if the method-based branch returns.)
  it('a ROLE-403 on a GET with a bound tenant does NOT clear the binding or bounce', async () => {
    setActiveTenant('t_ok')
    fetchSpy.mockResolvedValue(resp(403, { detail: 'requires role >= admin' }))

    await expect(http.get('/tenants/t_ok/members')).rejects.toMatchObject({
      status: 403,
    })

    expect(getActiveTenant()).toBe('t_ok') // valid binding preserved — NOT ejected
    expect(assignSpy).not.toHaveBeenCalled()
  })

  // Symmetric: a lost-tenant 403 is keyed on the reason, not the method — it fails
  // safe even on a mutation whose bound tenant went stale.
  it('a lost-tenant 403 on a MUTATION clears the binding and bounces (reason, not method)', async () => {
    setActiveTenant('t_stale')
    fetchSpy.mockResolvedValue(resp(403, { detail: 'not a member of requested tenant' }))

    await expect(http.post('/policies', { name: 'x' })).rejects.toBeInstanceOf(ApiException)

    expect(getActiveTenant()).toBeNull() // binding dropped
    expect(assignSpy).toHaveBeenCalledWith(ORG_PAGE_PATH)
  })

  // The other lost-tenant reason string (deps.py:446).
  it('a 403 "operator has no tenant membership" on a GET fails safe to the org page', async () => {
    setActiveTenant('t_stale')
    fetchSpy.mockResolvedValue(resp(403, { detail: 'operator has no tenant membership' }))

    await expect(http.get('/me')).rejects.toBeInstanceOf(ApiException)

    expect(getActiveTenant()).toBeNull()
    expect(assignSpy).toHaveBeenCalledWith(ORG_PAGE_PATH)
  })

  it('an UNRECOGNIZED 403 on a GET with a bound tenant preserves the binding (fail-safe default)', async () => {
    setActiveTenant('t_ok')
    fetchSpy.mockResolvedValue(resp(403, { detail: 'forbidden' }))

    await expect(http.get('/agents')).rejects.toBeInstanceOf(ApiException)

    expect(getActiveTenant()).toBe('t_ok') // never wipe on an unknown reason
    expect(assignSpy).not.toHaveBeenCalled()
  })

  it('a 403 READ with NO active tenant does not bounce (nothing to clear)', async () => {
    clearActiveTenant()
    fetchSpy.mockResolvedValue(resp(403, { detail: 'not a member of requested tenant' }))

    await expect(http.get('/agents')).rejects.toBeInstanceOf(ApiException)
    expect(assignSpy).not.toHaveBeenCalled()
  })
})
