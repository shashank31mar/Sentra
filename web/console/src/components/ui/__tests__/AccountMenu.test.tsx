import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../../../test/renderWithProviders'
import type { CurrentUser } from '../../../types/api'

// Mock the cosmetic identity hook the menu reads (/whoami claims).
const mockUseCurrentUser = vi.fn()
vi.mock('../../../lib/query/useCurrentUser', () => ({
  useCurrentUser: () => mockUseCurrentUser(),
}))

import { AccountMenu } from '../AccountMenu'

function setUser(user: CurrentUser | null) {
  mockUseCurrentUser.mockReturnValue({ data: user, isLoading: false })
}

describe('AccountMenu tenant chip (G1.1)', () => {
  beforeEach(() => mockUseCurrentUser.mockReset())

  it('renders the cosmetic tenant chip from tenantLabelForDisplay', async () => {
    setUser({ email: 'bob@globex.com', name: null, username: null, groups: [] })
    renderWithProviders(<AccountMenu />)
    await userEvent.click(screen.getByRole('button', { name: 'Account menu' }))
    // The email-domain label rides through as the chip text inside the dropdown.
    expect(screen.getByText('globex.com')).toBeInTheDocument()
  })

  it('omits the chip when no domain is resolvable', async () => {
    setUser({ email: null, name: 'No Domain', username: null, groups: [] })
    renderWithProviders(<AccountMenu />)
    await userEvent.click(screen.getByRole('button', { name: 'Account menu' }))
    expect(screen.queryByText('globex.com')).not.toBeInTheDocument()
  })
})
