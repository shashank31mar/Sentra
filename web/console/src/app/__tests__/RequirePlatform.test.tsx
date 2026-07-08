import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import { renderWithProviders } from '../../test/renderWithProviders'
import type { MeContext } from '../../types/api'

const mockUseMe = vi.fn()
vi.mock('../../lib/query/useMe', () => ({
  useMe: () => mockUseMe(),
}))

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

function mountAt(path: string) {
  return renderWithProviders(
    <Routes>
      <Route
        path="/platform"
        element={
          <RequirePlatform>
            <div data-testid="platform-tree">platform</div>
          </RequirePlatform>
        }
      />
      <Route path="/" element={<div data-testid="overview">overview</div>} />
    </Routes>,
    { routerEntries: [path] },
  )
}

describe('RequirePlatform (G4.1 fail-secure)', () => {
  beforeEach(() => mockUseMe.mockReset())

  it('renders the platform tree when is_platform === true', () => {
    mockUseMe.mockReturnValue({ data: me({ is_platform: true }), isLoading: false })
    mountAt('/platform')
    expect(screen.getByTestId('platform-tree')).toBeInTheDocument()
  })

  it('redirects a non-platform operator to overview', () => {
    mockUseMe.mockReturnValue({ data: me({ is_platform: false }), isLoading: false })
    mountAt('/platform')
    expect(screen.queryByTestId('platform-tree')).not.toBeInTheDocument()
    expect(screen.getByTestId('overview')).toBeInTheDocument()
  })

  it('treats an ABSENT is_platform as denied (fail-secure)', () => {
    const noFlag = me({}) as MeContext
    // Simulate a /v1/me shape missing the field entirely.
    delete (noFlag as Partial<MeContext>).is_platform
    mockUseMe.mockReturnValue({ data: noFlag, isLoading: false })
    mountAt('/platform')
    expect(screen.queryByTestId('platform-tree')).not.toBeInTheDocument()
    expect(screen.getByTestId('overview')).toBeInTheDocument()
  })

  it('shows loading while /v1/me is pending (does not flash the tree)', () => {
    mockUseMe.mockReturnValue({ data: undefined, isLoading: true })
    mountAt('/platform')
    expect(screen.queryByTestId('platform-tree')).not.toBeInTheDocument()
    expect(screen.queryByTestId('overview')).not.toBeInTheDocument()
  })
})
