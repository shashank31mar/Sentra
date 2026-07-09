import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import { renderWithProviders } from '../../test/renderWithProviders'
import type { MeContext } from '../../types/api'

/**
 * FX-2.5 — symmetric root-split confinement. `RequireCustomerRoot` sends an
 * `is_platform` operator hitting a customer route to `/platform`; `RequirePlatform`
 * (existing behavior, kept) sends a customer operator off `/platform`.
 */

const mockUseMe = vi.fn()
vi.mock('../../lib/query/useMe', () => ({
  useMe: () => mockUseMe(),
}))

import { RequireCustomerRoot } from '../RequireCustomerRoot'
import { RequirePlatform } from '../RequirePlatform'

const me = (over: Partial<MeContext>): MeContext => ({
  sub: 's',
  email: 'a@acme.io',
  tenant_id: 't_0',
  role: 'owner',
  is_platform: false,
  memberships: [{ tenant_id: 't_0', role: 'owner', is_primary: true }],
  ...over,
})

function mount(path: string) {
  return renderWithProviders(
    <Routes>
      <Route
        path="/overview"
        element={
          <RequireCustomerRoot>
            <div data-testid="customer-tree">overview</div>
          </RequireCustomerRoot>
        }
      />
      <Route
        path="/platform"
        element={
          <RequirePlatform>
            <div data-testid="platform-tree">platform</div>
          </RequirePlatform>
        }
      />
    </Routes>,
    { routerEntries: [path] },
  )
}

describe('platform confinement (FX-2.5)', () => {
  beforeEach(() => mockUseMe.mockReset())

  it('an is_platform operator at /overview is redirected to /platform', () => {
    mockUseMe.mockReturnValue({ data: me({ is_platform: true }), isLoading: false })
    mount('/overview')
    expect(screen.queryByTestId('customer-tree')).not.toBeInTheDocument()
    expect(screen.getByTestId('platform-tree')).toBeInTheDocument()
  })

  it('a customer operator at /overview stays on the customer tree', () => {
    mockUseMe.mockReturnValue({ data: me({ is_platform: false }), isLoading: false })
    mount('/overview')
    expect(screen.getByTestId('customer-tree')).toBeInTheDocument()
  })

  it('a customer operator at /platform is still redirected off it (existing behavior kept)', () => {
    mockUseMe.mockReturnValue({ data: me({ is_platform: false }), isLoading: false })
    mount('/platform')
    expect(screen.queryByTestId('platform-tree')).not.toBeInTheDocument()
    // RequirePlatform redirects to ROUTES.overview ('/') which isn't mounted here;
    // the point is the platform tree is NOT shown.
  })
})
