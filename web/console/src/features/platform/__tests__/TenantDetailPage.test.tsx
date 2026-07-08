import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { ApiException } from '../../../lib/http'
import type { PlatformTenantDetail } from '../../../types/api'

const mockUseTenantDetail = vi.fn()
vi.mock('../../../lib/query/usePlatform', () => ({
  useTenantDetail: (id: string) => mockUseTenantDetail(id),
}))

import { TenantDetailPage } from '../TenantDetailPage'

const DETAIL: PlatformTenantDetail = {
  tenant_id: 't_globex',
  display_name: 'Globex',
  status: 'active',
  plan: 'enterprise',
  identity_mode: 'enforce',
  quota: { monthly_validations: 1000 },
  platform_read_consent: true,
  members: [{ operator_sub: 'sub-1', role: 'owner' }],
}

function mount() {
  return renderWithProviders(
    <Routes>
      <Route path="/platform/tenants/:tenantId" element={<TenantDetailPage />} />
    </Routes>,
    { routerEntries: ['/platform/tenants/t_globex'] },
  )
}

describe('TenantDetailPage (G4.6)', () => {
  beforeEach(() => mockUseTenantDetail.mockReset())

  it('renders the registry + members roster read-only', () => {
    mockUseTenantDetail.mockReturnValue({ data: DETAIL, isLoading: false, isError: false })
    mount()
    expect(screen.getByText('Globex')).toBeInTheDocument()
    expect(screen.getByText('sub-1')).toBeInTheDocument()
    // No mutation control (no member add/remove, no consent toggle).
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('renders the consent-required empty state on 403 (distinct from 404)', () => {
    mockUseTenantDetail.mockReturnValue({
      isLoading: false,
      isError: true,
      error: new ApiException(403, { error: 'platform_read_consent not granted', error_code: 'CONSENT_REQUIRED' }),
    })
    mount()
    expect(screen.getByText(/Consent required/i)).toBeInTheDocument()
  })

  it('renders the not-found state on 404 (distinct from 403)', () => {
    mockUseTenantDetail.mockReturnValue({
      isLoading: false,
      isError: true,
      error: new ApiException(404, { error: 'tenant not found', error_code: 'NOT_FOUND' }),
    })
    mount()
    expect(screen.getByText(/Tenant not found/i)).toBeInTheDocument()
    expect(screen.queryByText(/Consent required/i)).not.toBeInTheDocument()
  })
})
