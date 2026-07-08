import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { ApiException } from '../../../lib/http'
import type { UsageRollup } from '../../../types/api'

const mockUseUsage = vi.fn()
vi.mock('../../../lib/query/useUsage', () => ({
  useUsage: () => mockUseUsage(),
}))

import { UsagePage } from '../UsagePage'

describe('UsagePage (M-G3.12)', () => {
  beforeEach(() => mockUseUsage.mockReset())

  it('renders the PARTIAL banner on 404 (no fabricated totals)', () => {
    mockUseUsage.mockReturnValue({
      isLoading: false,
      isError: true,
      error: new ApiException(404, { error: 'not found', error_code: 'NOT_FOUND' }),
    })
    renderWithProviders(<UsagePage />)
    expect(screen.getByText(/Usage data not yet available/i)).toBeInTheDocument()
    // No fabricated numbers rendered.
    expect(screen.queryByText('Validations')).not.toBeInTheDocument()
  })

  it('renders the PARTIAL banner on 501', () => {
    mockUseUsage.mockReturnValue({
      isLoading: false,
      isError: true,
      error: new ApiException(501, { error: 'not implemented', error_code: 'NOT_IMPLEMENTED' }),
    })
    renderWithProviders(<UsagePage />)
    expect(screen.getByText(/Usage data not yet available/i)).toBeInTheDocument()
  })

  it('renders metered figures when the endpoint returns data', () => {
    const rollup: UsageRollup = { validations: 1234, quota: 5000, blocks: 7, agents: 3 }
    mockUseUsage.mockReturnValue({ isLoading: false, isError: false, data: rollup })
    renderWithProviders(<UsagePage />)
    expect(screen.getByText('1,234')).toBeInTheDocument()
    expect(screen.getByText('Validations')).toBeInTheDocument()
  })
})
