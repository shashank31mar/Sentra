import { describe, it, expect } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { TenantGrid } from '../TenantGrid'
import { platformTenantDetailPath } from '../../../app/routes'
import type { PlatformTenantRow } from '../../../types/api'

const base = (over: Partial<PlatformTenantRow>): PlatformTenantRow => ({
  tenant_id: over.tenant_id ?? 't_acme',
  display_name: over.display_name ?? 'Acme',
  plan: 'enterprise',
  status: 'active',
  identity_mode: 'enforce',
  created_at: '2026-01-01',
  ...over,
})

describe('TenantGrid (G4.3)', () => {
  it('renders the 6-col ranked shape when metrics are absent (no metric columns)', () => {
    renderWithProviders(<TenantGrid rows={[base({})]} />)
    expect(screen.getByText('Consent')).toBeInTheDocument()
    // Metric column headers not present in degraded shape.
    expect(screen.queryByText('Blocks 24h')).not.toBeInTheDocument()
    expect(screen.getByText('Acme')).toBeInTheDocument()
  })

  it('renders metric columns when the optional fields are present', () => {
    renderWithProviders(<TenantGrid rows={[base({ blocks_24h: 12, agents: 4 })]} />)
    expect(screen.getByText('Blocks 24h')).toBeInTheDocument()
    expect(screen.getByText('Agents')).toBeInTheDocument()
  })

  it('rows link to the platform tenant-detail path', () => {
    renderWithProviders(<TenantGrid rows={[base({ tenant_id: 't_globex', display_name: 'Globex' })]} />)
    // The row is clickable → navigates to the detail path. We assert the path builder.
    expect(platformTenantDetailPath('t_globex')).toBe('/platform/tenants/t_globex')
    expect(screen.getByText('Globex')).toBeInTheDocument()
  })

  it('virtualizes rows when server paging (cursor) is present', () => {
    const rows = Array.from({ length: 200 }, (_, i) => base({ tenant_id: `t_${i}`, display_name: `Tenant ${i}` }))
    renderWithProviders(<TenantGrid rows={rows} virtualized />)
    // Virtualization contract: the scroller mounts with a full-height spacer that
    // reserves space for ALL rows (200 × 52px), while the DOM holds FAR FEWER than
    // 200 rendered rows — a non-virtualized table would render all 200 <tr>s and no
    // spacer. (In jsdom, with no real viewport, the window is small/empty; the point
    // is that it is NOT the full set.)
    const scroller = screen.getByTestId('tenant-grid-virtual')
    expect(scroller).toBeInTheDocument()
    const spacer = scroller.firstElementChild as HTMLElement
    expect(spacer.style.height).toBe(`${rows.length * 52}px`)
    const rendered = screen.queryAllByTestId('tenant-grid-row')
    expect(rendered.length).toBeLessThan(rows.length)
  })

  it('renders no mutation control (read-only invariant)', () => {
    renderWithProviders(<TenantGrid rows={[base({})]} />)
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })
})
