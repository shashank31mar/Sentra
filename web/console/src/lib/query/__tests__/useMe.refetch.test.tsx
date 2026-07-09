import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, act, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider, focusManager } from '@tanstack/react-query'
import { useMe, useCan } from '../useMe'
import { meApi } from '../../api/me'
import type { MeContext } from '../../../types/api'

/**
 * FX-2.6 — G2.8 fail-secure demotion on window focus. `useMe` sets
 * `refetchOnWindowFocus:true`, so a demoted operator's role re-reads on tab focus and
 * a previously-shown control disappears on re-render. This drives the REAL focus
 * mechanism (TanStack `focusManager`) and asserts (a) `meApi.get` refetches on focus,
 * and (b) an admin→viewer demotion hides an admin-gated control.
 */

const me = (role: MeContext['role']): MeContext => ({
  sub: 's',
  email: 'a@acme.io',
  tenant_id: 't_0',
  role,
  is_platform: false,
  memberships: [{ tenant_id: 't_0', role, is_primary: true }],
})

function Probe() {
  useMe() // subscribe so refetchOnWindowFocus is active
  const can = useCan()
  return <div>{can('policies.delete') ? <span data-testid="admin-ctrl">delete</span> : null}</div>
}

describe('useMe window-focus demotion (FX-2.6)', () => {
  let getSpy: ReturnType<typeof vi.spyOn>
  let nowSpy: ReturnType<typeof vi.spyOn>
  let clock = 0

  beforeEach(() => {
    getSpy = vi.spyOn(meApi, 'get')
    // `useMe` uses staleTime: 5min, so a fresh query would NOT refetch on focus.
    // Control Date.now() so we can advance past staleTime and make it stale (the
    // real ≤5-min-staleness demotion window the mechanism documents).
    clock = 1_000_000
    nowSpy = vi.spyOn(Date, 'now').mockImplementation(() => clock)
  })
  afterEach(() => {
    getSpy.mockRestore()
    nowSpy.mockRestore()
    focusManager.setFocused(undefined)
  })

  it('refetches /v1/me on window focus and hides an admin control after admin→viewer demotion', async () => {
    // First read = admin (control visible); the focus-triggered refetch = viewer.
    getSpy.mockResolvedValueOnce(me('admin')).mockResolvedValue(me('viewer'))

    // Use the REAL useMe config (staleTime 5min, refetchOnWindowFocus) — this test is
    // about that config, so don't override it with a fresh QueryClient default.
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } })
    render(
      <QueryClientProvider client={client}>
        <Probe />
      </QueryClientProvider>,
    )

    // Admin control initially visible.
    expect(await screen.findByTestId('admin-ctrl')).toBeInTheDocument()
    expect(getSpy).toHaveBeenCalledTimes(1)

    // Advance past the 5-min staleTime so the focus refetch actually fires.
    clock += 6 * 60_000

    // Simulate a tab-focus event → TanStack refetches the (now-stale) focus query.
    await act(async () => {
      focusManager.setFocused(false)
      focusManager.setFocused(true)
    })

    // The refetch fired (demotion re-read) and the admin control disappears.
    await waitFor(() => expect(getSpy.mock.calls.length).toBeGreaterThan(1))
    await waitFor(() => expect(screen.queryByTestId('admin-ctrl')).not.toBeInTheDocument())
  })
})
