import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import { renderWithProviders } from '../../../test/renderWithProviders'
import type { PlatformTenantDetail } from '../../../types/api'

/**
 * FX-3.6 — the platform tenant detail renders the computed quota HEADROOM
 * (`quotaHeadroom`) instead of dumping raw `JSON.stringify(t.quota)`. When the usage
 * is present it shows the used%, and when the limit is unknown it says "unknown"
 * (never fabricates a number).
 */

const mockUseTenantDetail = vi.fn()
vi.mock('../../../lib/query/usePlatform', () => ({
  useTenantDetail: (id: string) => mockUseTenantDetail(id),
}))

import { TenantDetailPage } from '../TenantDetailPage'

const detail = (over: Partial<PlatformTenantDetail>): PlatformTenantDetail => ({
  tenant_id: 't_globex',
  display_name: 'Globex',
  status: 'active',
  plan: 'enterprise',
  identity_mode: 'enforce',
  quota: { monthly_validations: 1000 },
  platform_read_consent: true,
  members: [],
  decisions_24h: 250,
  ...over,
})

function mount() {
  return renderWithProviders(
    <Routes>
      <Route path="/platform/tenants/:tenantId" element={<TenantDetailPage />} />
    </Routes>,
    { routerEntries: ['/platform/tenants/t_globex'] },
  )
}

describe('TenantDetailPage quota headroom (FX-3.6)', () => {
  beforeEach(() => mockUseTenantDetail.mockReset())

  it('renders the computed headroom % (used vs limit), not raw JSON', () => {
    mockUseTenantDetail.mockReturnValue({ data: detail({}), isLoading: false, isError: false })
    mount()
    // 250 / 1000 = 25.0% used.
    expect(screen.getByText('Headroom used')).toBeInTheDocument()
    expect(screen.getByText('25.0%')).toBeInTheDocument()
    // No raw JSON dump of the quota bag.
    expect(screen.queryByText(/"monthly_validations"/)).not.toBeInTheDocument()
  })

  it('shows "unknown" when the limit is not a usable number (never fabricates)', () => {
    mockUseTenantDetail.mockReturnValue({
      data: detail({ quota: {}, decisions_24h: 250 }),
      isLoading: false,
      isError: false,
    })
    mount()
    expect(screen.getByText('unknown')).toBeInTheDocument()
  })
})
