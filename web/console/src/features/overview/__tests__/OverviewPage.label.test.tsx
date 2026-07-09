import { describe, it, expect, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '../../../test/renderWithProviders'

/**
 * FX-3.2 — the Overview must NOT claim "Live"/"Streaming"/"Real-time telemetry"; the
 * data is a 15s TanStack poll. Assert the honest "near-real-time (≤15s pull)" label
 * and the ABSENCE of the misleading literals.
 */

const idle = { isLoading: false, isError: false, isFetching: false, error: null, refetch: vi.fn() }

vi.mock('../../../lib/query/useMetrics', () => ({
  useOverview: () => ({ ...idle, data: undefined }),
  usePlatformDistribution: () => ({ ...idle, data: undefined }),
  useDecisionsTimeseries: () => ({ ...idle, data: undefined }),
}))
vi.mock('../../../lib/query/useDecisions', () => ({
  useDecisions: () => ({ ...idle, data: { pages: [{ items: [], total: 0, next_token: null }] } }),
}))

import { OverviewPage } from '../OverviewPage'

describe('OverviewPage near-real-time relabel (FX-3.2)', () => {
  it('shows the near-real-time label and NO "Live"/"Streaming"/"Real-time telemetry" literal', () => {
    renderWithProviders(<OverviewPage />)
    // Honest label present (both the header pill and the chart subtitle use it).
    expect(screen.getAllByText(/near-real-time \(≤15s pull\)/).length).toBeGreaterThan(0)
    // The misleading push-implying literals are gone.
    expect(screen.queryByText(/Streaming/)).not.toBeInTheDocument()
    expect(screen.queryByText(/^Live$/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Real-time request decision telemetry/)).not.toBeInTheDocument()
  })
})
