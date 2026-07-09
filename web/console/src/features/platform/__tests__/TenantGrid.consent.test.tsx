import { describe, it, expect } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { TenantGrid } from '../TenantGrid'
import type { PlatformTenantRow } from '../../../types/api'

/**
 * FX-3.5 — the list route omits `platform_read_consent`, so an absent value means
 * UNKNOWN, not "required". A governance console must not falsely show "consent
 * required" for every tenant. Only an explicit `false` is "required".
 */

const base = (over: Partial<PlatformTenantRow>): PlatformTenantRow => ({
  tenant_id: over.tenant_id ?? 't_acme',
  display_name: over.display_name ?? 'Acme',
  plan: 'enterprise',
  status: 'active',
  identity_mode: 'enforce',
  created_at: '2026-01-01',
  ...over,
})

describe('TenantGrid consent column honesty (FX-3.5)', () => {
  it('renders "unknown" (neutral) when platform_read_consent is absent — NOT "required"', () => {
    renderWithProviders(<TenantGrid rows={[base({})]} />) // no platform_read_consent key
    expect(screen.getByText('unknown')).toBeInTheDocument()
    expect(screen.queryByText('required')).not.toBeInTheDocument()
  })

  it('renders "required" only for an explicit false', () => {
    renderWithProviders(<TenantGrid rows={[base({ platform_read_consent: false })]} />)
    expect(screen.getByText('required')).toBeInTheDocument()
    expect(screen.queryByText('unknown')).not.toBeInTheDocument()
  })

  it('renders "granted" for an explicit true', () => {
    renderWithProviders(<TenantGrid rows={[base({ platform_read_consent: true })]} />)
    expect(screen.getByText('granted')).toBeInTheDocument()
  })
})
