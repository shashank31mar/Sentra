import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '../../../test/renderWithProviders'
import type { PlatformTenantsResponse } from '../../../types/api'

/**
 * FX-1.5 (green≠correct gap) — the ranked strips are computed via
 * rankByBlocks/rankByDenyRate over the LOADED PAGE only (FLEET_PAGE_SIZE=50,
 * cursor-paged). When the fleet spans more than one server page, labelling the
 * strip "Top tenants …" is misleading (it's top-of-page, not top-of-fleet). This
 * test pins the honest behaviour: page-local label + a scope note when paged, and
 * the fleet-wide label with NO note when the whole fleet fits one page.
 */

let response: PlatformTenantsResponse = { count: 0, tenants: [] }

vi.mock('../../../lib/query/usePlatform', () => ({
  useFleetTenants: () => ({
    data: response,
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  }),
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

function tenant(id: string, blocks: number, denyRate: number): PlatformTenantsResponse['tenants'][number] {
  return {
    tenant_id: id,
    display_name: id,
    plan: 'enterprise',
    status: 'active',
    identity_mode: 'enforce',
    created_at: '2026-01-01',
    blocks_24h: blocks,
    deny_rate: denyRate,
  }
}

describe('FleetOverviewPage rank scope (FX-1.5 green≠correct)', () => {
  beforeEach(() => {
    response = { count: 0, tenants: [] }
  })

  it('labels the strip page-local + shows a scope note when the fleet is server-paged', () => {
    // A next cursor means there are more pages → the ranked page is NOT the fleet.
    response = {
      count: 120,
      cursor: 'CURSOR_P2',
      tenants: [tenant('t_1', 10, 0.5), tenant('t_2', 5, 0.2)],
    }
    renderWithProviders(<FleetOverviewPage />)
    // Honest page-local label — NOT "Top tenants …".
    expect(screen.getByText(/Top on page 1 by blocks/i)).toBeInTheDocument()
    expect(screen.getByText(/Top on page 1 by DENY rate/i)).toBeInTheDocument()
    expect(screen.queryByText(/^Top tenants by blocks/i)).not.toBeInTheDocument()
    // The scope caveat appears (once per strip).
    expect(screen.getAllByText(/Ranked within this page/i).length).toBe(2)
  })

  it('uses the fleet-wide label and NO scope note when the whole fleet fits one page', () => {
    // No cursor + page 1 → the loaded rows ARE the whole fleet → ranking is fleet-wide.
    response = {
      count: 2,
      tenants: [tenant('t_1', 10, 0.5), tenant('t_2', 5, 0.2)],
    }
    renderWithProviders(<FleetOverviewPage />)
    expect(screen.getByText(/^Top tenants by blocks \(24h\)/i)).toBeInTheDocument()
    expect(screen.getByText(/^Top tenants by DENY rate/i)).toBeInTheDocument()
    expect(screen.queryByText(/Ranked within this page/i)).not.toBeInTheDocument()
  })
})
