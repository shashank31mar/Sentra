import { describe, it, expect, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '../../../test/renderWithProviders'

// AccountMenu reads the cosmetic identity hook — stub it so TopBar mounts cleanly.
vi.mock('../../../lib/query/useCurrentUser', () => ({
  useCurrentUser: () => ({ data: null, isLoading: false }),
}))

import { TopBar } from '../TopBar'

/**
 * G2.10 — the in-session TenantSwitcher is deleted; the TopBar must mount with no
 * tenant-switcher control anywhere (tenant is bound org-first at login, ADR-039).
 */
describe('TopBar (G2.10 — no tenant switcher)', () => {
  it('renders without a Switch-tenant control', () => {
    renderWithProviders(<TopBar onMenuClick={() => {}} />)
    expect(screen.queryByRole('button', { name: /switch tenant/i })).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/switch tenant/i)).not.toBeInTheDocument()
    // The bar itself still renders (breadcrumb search etc.).
    expect(screen.getByRole('button', { name: /Account menu/i })).toBeInTheDocument()
  })
})
