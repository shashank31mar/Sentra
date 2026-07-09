import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { setActiveTenant, clearActiveTenant } from '../../../lib/tenant'
import type { MetricsOverview, DecisionsTimeseries, PlatformTenantsResponse } from '../../../types/api'

/**
 * FX-1.5 (G4.5) — the Fleet Overview binds the fleet KPI grid + fleet
 * allowed/blocked timeseries above the tenant grid. This is the named-but-absent
 * acceptance test. It also proves the fleet metric calls send NO `X-Aegion-Tenant`
 * header even when a tenant is ambiently bound (the FX-2.3 code-enforced invariant),
 * by asserting against the real fetch path.
 */

const OVERVIEW: MetricsOverview = {
  range: '24h',
  threats_blocked: 1234,
  threats_blocked_delta_pct: 5,
  attack_categories: 7,
  active_agents: 42,
  clouds: 3,
  trust_score: 88,
  trust_status: 'healthy',
  agents_below_threshold: 2,
  requests_total: 90000,
  avg_latency_ms: 120,
  quarantined: 3,
  false_positive_pct: null,
}

const TIMESERIES: DecisionsTimeseries = {
  range: '24h',
  bucket: '1h',
  series: [{ t: '2026-07-09T00:00:00Z', allowed: 100, blocked: 4 }],
}

const TENANTS: PlatformTenantsResponse = {
  count: 1,
  tenants: [
    { tenant_id: 't_acme', display_name: 'Acme', plan: 'enterprise', status: 'active', identity_mode: 'enforce', created_at: '2026-01-01' },
  ],
}

// Chart.js needs a canvas jsdom lacks — stub the chart component.
vi.mock('../../../components/charts/AllowedVsBlockedChart', () => ({
  AllowedVsBlockedChart: () => <div data-testid="fleet-chart" />,
}))

function okJson(body: unknown): Response {
  return { ok: true, status: 200, type: 'basic', json: async () => body } as unknown as Response
}

const fetchSpy = vi.fn()

import { FleetOverviewPage } from '../FleetOverviewPage'

describe('FleetOverviewPage fleet metrics (FX-1.5 / G4.5)', () => {
  beforeEach(() => {
    fetchSpy.mockReset()
    fetchSpy.mockImplementation((url: string) => {
      if (url.includes('/metrics/overview')) return Promise.resolve(okJson(OVERVIEW))
      if (url.includes('/metrics/decisions-timeseries')) return Promise.resolve(okJson(TIMESERIES))
      if (url.includes('/platform/tenants')) return Promise.resolve(okJson(TENANTS))
      return Promise.resolve(okJson({}))
    })
    vi.stubGlobal('fetch', fetchSpy)
    // Ambiently bind a tenant to prove the fleet calls STILL omit the header.
    setActiveTenant('t_should_be_ignored')
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    clearActiveTenant()
  })

  it('renders the fleet KPI grid + allowed/blocked chart from the fleet-mode endpoints', async () => {
    renderWithProviders(<FleetOverviewPage />)
    // KPI tile from the fleet overview (the hero "threats blocked" number).
    expect(await screen.findByText('1,234')).toBeInTheDocument()
    // Fleet chart mounted.
    expect(await screen.findByTestId('fleet-chart')).toBeInTheDocument()
  })

  it('sends NO X-Aegion-Tenant header on the fleet metric calls (FX-2.3 code-enforced)', async () => {
    renderWithProviders(<FleetOverviewPage />)
    await screen.findByText('1,234')
    const metricCalls = fetchSpy.mock.calls.filter((c) => String(c[0]).includes('/metrics/'))
    expect(metricCalls.length).toBeGreaterThan(0)
    for (const call of metricCalls) {
      const headers = (call[1]?.headers ?? {}) as Record<string, string>
      expect(headers['X-Aegion-Tenant']).toBeUndefined()
    }
  })
})
