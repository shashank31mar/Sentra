import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { FleetTopologyPage } from '../FleetTopologyPage'
import { SystemHealthPage } from '../SystemHealthPage'

/**
 * G4.7 — the roadmap platform pages render a roadmap badge + "sample data" marker
 * and make ZERO network calls (a live fetch to a nonexistent /v1/topology or
 * per-region health route would surface a spurious 404).
 */
describe('platform roadmap pages (G4.7)', () => {
  const fetchSpy = vi.fn()
  beforeEach(() => {
    fetchSpy.mockReset()
    fetchSpy.mockResolvedValue({ ok: true, status: 200, json: async () => ({}) } as Response)
    vi.stubGlobal('fetch', fetchSpy)
  })
  afterEach(() => vi.unstubAllGlobals())

  it('FleetTopology renders a roadmap badge + sample marker and makes no fetch', () => {
    renderWithProviders(<FleetTopologyPage />)
    expect(screen.getByText('Roadmap')).toBeInTheDocument()
    expect(screen.getByText(/Sample data/i)).toBeInTheDocument()
    expect(fetchSpy).not.toHaveBeenCalled()
  })

  it('SystemHealth renders a roadmap badge + sample marker and makes no fetch', () => {
    renderWithProviders(<SystemHealthPage />)
    expect(screen.getByText('Roadmap')).toBeInTheDocument()
    expect(screen.getByText(/Sample data/i)).toBeInTheDocument()
    expect(fetchSpy).not.toHaveBeenCalled()
  })
})
