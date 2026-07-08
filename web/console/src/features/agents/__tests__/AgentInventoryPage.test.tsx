import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { can } from '../../../lib/rbac'
import type { TenantRole, AgentListItem } from '../../../types/api'

let role: TenantRole = 'viewer'
vi.mock('../../../lib/query/useMe', () => ({
  useCan: () => (cap: Parameters<typeof can>[1]) => can(role, cap),
}))

const UNBOUND: AgentListItem = {
  agent_id: 'ag_1',
  name: 'Payments Agent',
  platform: 'bedrock',
  cloud_provider: 'aws',
  status: 'active',
  trust_score_avg: 88,
  requests_total: 100,
  requests_allowed: 90,
  requests_denied: 10,
  active_sessions: 2,
  last_seen: '2026-07-01T00:00:00Z',
  active_policy_id: null,
}
const BOUND: AgentListItem = { ...UNBOUND, agent_id: 'ag_2', name: 'Telecom Agent', active_policy_id: 'pol_9' }

vi.mock('../../../lib/query/useAgents', () => ({
  useAgents: () => ({
    data: { agents: [UNBOUND, BOUND], total: 2 },
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  }),
  useDetachPolicy: () => ({ mutate: vi.fn(), isPending: false }),
}))

import { AgentInventoryPage } from '../AgentInventoryPage'

describe('AgentInventoryPage attach/detach gating (G2.5)', () => {
  beforeEach(() => {
    role = 'viewer'
  })

  it('editor sees Attach Policy + Detach', () => {
    role = 'editor'
    renderWithProviders(<AgentInventoryPage />)
    expect(screen.getByRole('button', { name: /Attach Policy/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Detach' })).toBeInTheDocument()
  })

  it('viewer sees no attach/detach but rows still list + navigable', () => {
    role = 'viewer'
    renderWithProviders(<AgentInventoryPage />)
    expect(screen.queryByRole('button', { name: /Attach Policy/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Detach' })).not.toBeInTheDocument()
    expect(screen.getByText('Payments Agent')).toBeInTheDocument()
  })
})
