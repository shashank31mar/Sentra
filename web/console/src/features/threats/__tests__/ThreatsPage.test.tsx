import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { can } from '../../../lib/rbac'
import type { TenantRole, DecisionItem } from '../../../types/api'

let role: TenantRole = 'viewer'
vi.mock('../../../lib/query/useMe', () => ({
  useCan: () => (cap: Parameters<typeof can>[1]) => can(role, cap),
}))

const ITEM: DecisionItem = {
  decision_id: 'sess1:req1',
  session_id: 'sess1',
  request_id: 'req1',
  agent_id: 'a1',
  agent_name: 'Agent One',
  cloud_provider: 'aws',
  platform: null,
  decision: 'DENY',
  threat_type: 'prompt_injection',
  tool_name: 'refund',
  reason: 'blocked',
  trust_score: 40,
  timestamp: '2026-07-01T00:00:00Z',
}

vi.mock('../../../lib/query/useDecisions', () => ({
  useDecisions: () => ({
    data: { pages: [{ items: [ITEM], total: 1, next_token: null }] },
    isLoading: false,
    isError: false,
    error: null,
    hasNextPage: false,
    isFetchingNextPage: false,
    fetchNextPage: vi.fn(),
    refetch: vi.fn(),
  }),
  useQuarantine: () => ({ mutate: vi.fn(), isPending: false, variables: undefined }),
}))
vi.mock('../../../lib/query/useSessions', () => ({
  useSessions: () => ({ data: { sessions: [], total: 0 } }),
}))

import { ThreatsPage } from '../ThreatsPage'

describe('ThreatsPage quarantine gating (G2.4)', () => {
  beforeEach(() => {
    role = 'viewer'
  })

  it('admin sees the inline Quarantine control', () => {
    role = 'admin'
    renderWithProviders(<ThreatsPage />)
    expect(screen.getByRole('button', { name: /Quarantine/i })).toBeInTheDocument()
  })

  it('viewer sees no Quarantine control but the decision row still renders', () => {
    role = 'viewer'
    renderWithProviders(<ThreatsPage />)
    expect(screen.queryByRole('button', { name: /Quarantine/i })).not.toBeInTheDocument()
    expect(screen.getByText('Agent One')).toBeInTheDocument()
  })
})
