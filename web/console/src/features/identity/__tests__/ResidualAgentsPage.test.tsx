import { describe, it, expect, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '../../../test/renderWithProviders'
import type { ResidualAgent } from '../../../types/api'

const AGENT: ResidualAgent = {
  agent_id: 'ag_res_1',
  tenant_id: 't_acme',
  first_seen_ms: Date.now() - 60_000,
  deadline_ms: Date.now() + 3_600_000,
  expired: false,
}

vi.mock('../../../lib/query/useResidualAgents', () => ({
  useResidualAgents: () => ({
    data: { tenant_id: 't_acme', residual_agents: [AGENT], count: 1 },
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  }),
}))

import { ResidualAgentsPage } from '../ResidualAgentsPage'

/**
 * G2.7 — the residual-agents page is a read-only viewer-floor view. It must render
 * the list for any role and expose NO mutating control (no "retire" — that route
 * does not exist server-side; it's a WS-N/roadmap prerequisite, not WS-G).
 */
describe('ResidualAgentsPage read floor (G2.7)', () => {
  it('renders the residual list with no mutation control', () => {
    renderWithProviders(<ResidualAgentsPage />)
    expect(screen.getByText('ag_res_1')).toBeInTheDocument()
    // No mutating control anywhere (no retire/onboard button).
    expect(screen.queryByRole('button', { name: /retire|onboard|delete|remove/i })).not.toBeInTheDocument()
  })
})
