import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../../../test/renderWithProviders'
import type { FleetTenantsParams } from '../../../lib/query/usePlatform'
import type { PlatformTenantsResponse } from '../../../types/api'

/**
 * FX-3.4 — the Fleet grid sends `limit`/`cursor`/`sort` and advances the cursor so
 * the fleet is not silently truncated to page 1. Asserts the pager passes the
 * next-page cursor to the query and a sort change re-queries with the sort param.
 */

const seenParams: FleetTenantsParams[] = []
const RESP: PlatformTenantsResponse = {
  count: 120,
  cursor: 'CURSOR_P2',
  tenants: [
    { tenant_id: 't_1', display_name: 'Tenant 1', plan: 'enterprise', status: 'active', identity_mode: 'enforce', created_at: '2026-01-01' },
  ],
}

vi.mock('../../../lib/query/usePlatform', () => ({
  useFleetTenants: (params: FleetTenantsParams) => {
    seenParams.push(params)
    return { data: RESP, isLoading: false, isError: false, error: null, refetch: vi.fn() }
  },
}))

const idle = { isLoading: false, isError: false, error: null, refetch: vi.fn() }
vi.mock('../../../lib/query/useMetrics', () => ({
  useFleetOverview: () => ({ ...idle, data: undefined }),
  useFleetDecisionsTimeseries: () => ({ ...idle, data: { series: [] } }),
}))
vi.mock('../../../components/charts/AllowedVsBlockedChart', () => ({
  AllowedVsBlockedChart: () => <div data-testid="fleet-chart" />,
}))

import { FleetOverviewPage } from '../FleetOverviewPage'

describe('FleetOverviewPage paging (FX-3.4)', () => {
  beforeEach(() => {
    seenParams.length = 0
  })

  it('sends limit + sort on first load (no cursor on page 1)', () => {
    renderWithProviders(<FleetOverviewPage />)
    const first = seenParams[0]
    expect(first.limit).toBe(50)
    expect(first.sort).toBe('blocks_24h')
    expect(first.cursor).toBeUndefined()
  })

  it('advancing the pager re-queries with the next-page cursor', async () => {
    renderWithProviders(<FleetOverviewPage />)
    seenParams.length = 0
    await userEvent.click(screen.getByRole('button', { name: /Next/i }))
    // A later render carried the server-returned cursor.
    expect(seenParams.some((p) => p.cursor === 'CURSOR_P2')).toBe(true)
  })

  it('changing the sort re-queries with the new sort param (and resets to page 1)', async () => {
    renderWithProviders(<FleetOverviewPage />)
    seenParams.length = 0
    await userEvent.click(screen.getByRole('button', { name: 'Trust' }))
    const after = seenParams[seenParams.length - 1]
    expect(after.sort).toBe('trust')
    expect(after.cursor).toBeUndefined() // reset to first page on sort change
  })
})
