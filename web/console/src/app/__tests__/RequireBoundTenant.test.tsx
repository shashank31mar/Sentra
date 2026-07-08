import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { renderWithProviders } from '../../test/renderWithProviders'
import type { MeContext } from '../../types/api'
import { setActiveTenant, clearActiveTenant } from '../../lib/tenant'

const mockUseMe = vi.fn()
vi.mock('../../lib/query/useMe', () => ({
  useMe: () => mockUseMe(),
}))

import { RequireBoundTenant, ORG_PAGE_PATH } from '../RequireBoundTenant'

const me = (memberships: number): MeContext => ({
  sub: 's',
  email: 'a@acme.io',
  tenant_id: 't_0',
  role: 'viewer',
  is_platform: false,
  memberships: Array.from({ length: memberships }, (_, i) => ({
    tenant_id: `t_${i}`,
    role: 'viewer' as const,
    is_primary: i === 0,
  })),
})

let assignSpy: ReturnType<typeof vi.fn>

describe('RequireBoundTenant (G2.12 fail-safe redirect)', () => {
  beforeEach(() => {
    mockUseMe.mockReset()
    clearActiveTenant()
    window.sessionStorage.clear()
    assignSpy = vi.fn()
    // jsdom does not implement navigation — stub assign.
    Object.defineProperty(window, 'location', {
      value: { ...window.location, assign: assignSpy },
      writable: true,
    })
  })

  afterEach(() => {
    clearActiveTenant()
  })

  it('single-membership operator renders through (no redirect)', () => {
    mockUseMe.mockReturnValue({ data: me(1), isLoading: false })
    renderWithProviders(
      <RequireBoundTenant>
        <div data-testid="shell">shell</div>
      </RequireBoundTenant>,
    )
    expect(screen.getByTestId('shell')).toBeInTheDocument()
    expect(assignSpy).not.toHaveBeenCalled()
  })

  it('multi-membership with a bound tenant renders through', () => {
    setActiveTenant('t_1')
    mockUseMe.mockReturnValue({ data: me(2), isLoading: false })
    renderWithProviders(
      <RequireBoundTenant>
        <div data-testid="shell">shell</div>
      </RequireBoundTenant>,
    )
    expect(screen.getByTestId('shell')).toBeInTheDocument()
    expect(assignSpy).not.toHaveBeenCalled()
  })

  it('multi-membership with NO bound tenant redirects to the org page (never renders shell)', async () => {
    mockUseMe.mockReturnValue({ data: me(2), isLoading: false })
    renderWithProviders(
      <RequireBoundTenant>
        <div data-testid="shell">shell</div>
      </RequireBoundTenant>,
    )
    expect(screen.queryByTestId('shell')).not.toBeInTheDocument()
    await waitFor(() => expect(assignSpy).toHaveBeenCalledWith(ORG_PAGE_PATH))
  })

  it('while /v1/me is loading, holds a spinner (does not flash the shell)', () => {
    mockUseMe.mockReturnValue({ data: undefined, isLoading: true })
    renderWithProviders(
      <RequireBoundTenant>
        <div data-testid="shell">shell</div>
      </RequireBoundTenant>,
    )
    expect(screen.queryByTestId('shell')).not.toBeInTheDocument()
  })
})
