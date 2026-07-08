import { describe, it, expect, vi } from 'vitest'
import {
  submitOrg,
  needsOrgRedirect,
  resolveOrgUrl,
  RESOLVE_ORG_PATH,
  POST_BIND_REDIRECT,
} from '../orgEntry'
import type { MeContext } from '../../types/api'

function jsonResponse(status: number, body: unknown): Response {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: async () => body,
  } as unknown as Response
}

describe('org-first entry client (G2.12 / ADR-039)', () => {
  it('builds the resolver URL against the non-/v1 public path with encoded org', () => {
    expect(resolveOrgUrl('Acme Corp')).toBe(`${RESOLVE_ORG_PATH}?org=Acme%20Corp`)
  })

  it('hit → binds the resolved tenant_id + redirects to the console entry', async () => {
    const bind = vi.fn()
    const redirect = vi.fn()
    const fetchMock = vi.fn(async () => jsonResponse(200, { tenant_id: 't_globex' }))
    const res = await submitOrg('globex', { fetch: fetchMock, bind, redirect })

    expect(fetchMock).toHaveBeenCalledWith(resolveOrgUrl('globex'), expect.anything())
    expect(bind).toHaveBeenCalledWith('t_globex')
    expect(redirect).toHaveBeenCalledWith(POST_BIND_REDIRECT)
    expect(res).toEqual({ status: 'ok', tenantId: 't_globex', redirectedTo: POST_BIND_REDIRECT })
  })

  it('miss (404) → no bind, no redirect, friendly message (stay on org page)', async () => {
    const bind = vi.fn()
    const redirect = vi.fn()
    const fetchMock = vi.fn(async () => jsonResponse(404, { detail: 'not found' }))
    const res = await submitOrg('nope', { fetch: fetchMock, bind, redirect })

    expect(bind).not.toHaveBeenCalled()
    expect(redirect).not.toHaveBeenCalled()
    expect(res.status).toBe('not_found')
  })

  it('never advances to Cognito when the body lacks a tenant_id (fail-safe)', async () => {
    const bind = vi.fn()
    const redirect = vi.fn()
    const fetchMock = vi.fn(async () => jsonResponse(200, { not_tenant: 'x' }))
    const res = await submitOrg('weird', { fetch: fetchMock, bind, redirect })

    expect(bind).not.toHaveBeenCalled()
    expect(redirect).not.toHaveBeenCalled()
    expect(res.status).toBe('error')
  })

  it('network throw → error, no bind/redirect', async () => {
    const bind = vi.fn()
    const redirect = vi.fn()
    const fetchMock = vi.fn(async () => {
      throw new Error('offline')
    })
    const res = await submitOrg('acme', { fetch: fetchMock, bind, redirect })
    expect(res.status).toBe('error')
    expect(bind).not.toHaveBeenCalled()
  })
})

describe('needsOrgRedirect (router guard predicate)', () => {
  const me = (n: number): Pick<MeContext, 'memberships'> => ({
    memberships: Array.from({ length: n }, (_, i) => ({
      tenant_id: `t_${i}`,
      role: 'viewer' as const,
      is_primary: i === 0,
    })),
  })

  it('multi-membership + no bound tenant → redirect', () => {
    expect(needsOrgRedirect(me(2), null)).toBe(true)
  })

  it('multi-membership + bound tenant → no redirect', () => {
    expect(needsOrgRedirect(me(2), 't_0')).toBe(false)
  })

  it('single-membership → never redirects (server picks the sole membership)', () => {
    expect(needsOrgRedirect(me(1), null)).toBe(false)
  })

  it('no me (loading/absent) → no redirect', () => {
    expect(needsOrgRedirect(null, null)).toBe(false)
    expect(needsOrgRedirect(undefined, null)).toBe(false)
  })
})
