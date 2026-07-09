import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import { renderWithProviders } from '../../test/renderWithProviders'
import { can } from '../../lib/rbac'
import { ROUTES } from '../routes'
import type { TenantRole } from '../../types/api'

/**
 * FX-2.2 — route-level RBAC guard for a deep-linkable mutating page. Direct test of
 * the guard's two behavioral branches (the in-page submit gate is covered separately
 * by PolicyEditorPage.gate.test.tsx):
 *   - hold a spinner while `/v1/me` loads (never flash the gated page);
 *   - redirect to the read-only overview when `can(cap)` is false.
 * This is UX-only defense-in-depth (server `require_role` is the boundary), but the
 * redirect target is asserted here so a typo/route-rename can't silently break it.
 */

const mockUseMe = vi.fn()
let role: TenantRole | undefined = 'viewer'
vi.mock('../../lib/query/useMe', () => ({
  useMe: () => mockUseMe(),
  // `useCan` returns a `can(cap)` bound to the mocked role (mirrors the real hook).
  useCan: () => (cap: Parameters<typeof can>[1]) => can(role, cap),
}))

import { RequireCan } from '../RequireCan'

function mountAt(path: string) {
  return renderWithProviders(
    <Routes>
      <Route
        path={ROUTES.policyNew}
        element={
          <RequireCan cap="policies.write">
            <div data-testid="editor">policy editor</div>
          </RequireCan>
        }
      />
      <Route path={ROUTES.overview} element={<div data-testid="overview">overview</div>} />
    </Routes>,
    { routerEntries: [path] },
  )
}

describe('RequireCan (FX-2.2 route guard)', () => {
  beforeEach(() => {
    mockUseMe.mockReset()
    role = 'viewer'
  })

  it('renders the gated page for an operator WITH the capability (editor → policies.write)', () => {
    role = 'editor'
    mockUseMe.mockReturnValue({ isLoading: false })
    mountAt(ROUTES.policyNew)
    expect(screen.getByTestId('editor')).toBeInTheDocument()
    expect(screen.queryByTestId('overview')).not.toBeInTheDocument()
  })

  it('redirects a viewer (no capability) to the overview route', () => {
    role = 'viewer'
    mockUseMe.mockReturnValue({ isLoading: false })
    mountAt(ROUTES.policyNew)
    // The redirect landed on ROUTES.overview — asserts the exact target, so a typo
    // or route rename here fails the test instead of silently mis-redirecting.
    expect(screen.getByTestId('overview')).toBeInTheDocument()
    expect(screen.queryByTestId('editor')).not.toBeInTheDocument()
  })

  it('holds a spinner while /v1/me is loading (never flashes the gated page)', () => {
    role = 'viewer'
    mockUseMe.mockReturnValue({ isLoading: true })
    mountAt(ROUTES.policyNew)
    // Neither the gated page nor the redirect target renders while role is unknown.
    expect(screen.queryByTestId('editor')).not.toBeInTheDocument()
    expect(screen.queryByTestId('overview')).not.toBeInTheDocument()
  })
})
