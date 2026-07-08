import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { can } from '../../../lib/rbac'
import type { TenantRole, SessionInfo } from '../../../types/api'

let role: TenantRole = 'viewer'
vi.mock('../../../lib/query/useMe', () => ({
  useCan: () => (cap: Parameters<typeof can>[1]) => can(role, cap),
}))

const SESSION: SessionInfo = {
  session_id: 'sess_abc',
  user_id: 'u1',
  agent_id: 'agent_1',
  trust_score: 22,
  quarantine_status: 'quarantined',
  total_requests: 12,
  allow_count: 4,
  deny_count: 8,
  consecutive_allows: 0,
  created_at: '2026-07-01T00:00:00Z',
  last_activity: '2026-07-01T01:00:00Z',
}

vi.mock('../../../lib/query/useSessions', () => ({
  useInfiniteSessions: () => ({
    data: { pages: [{ items: [SESSION], total: 1, next_token: null }] },
    isLoading: false,
    isError: false,
    error: null,
    hasNextPage: false,
    isFetchingNextPage: false,
    fetchNextPage: vi.fn(),
    refetch: vi.fn(),
  }),
  useReleaseQuarantine: () => ({ mutate: vi.fn(), isPending: false }),
}))

// DecisionTrace fetches on expand — stub it out (not under test here).
vi.mock('../../../components/decisions/DecisionTrace', () => ({
  DecisionTrace: () => null,
}))

import { QuarantinePage } from '../QuarantinePage'

describe('QuarantinePage release gating (G2.3)', () => {
  beforeEach(() => {
    role = 'viewer'
  })

  it('admin sees the Unquarantine release control', () => {
    role = 'admin'
    renderWithProviders(<QuarantinePage />)
    expect(screen.getByRole('button', { name: /Unquarantine/i })).toBeInTheDocument()
  })

  it('viewer sees no release control but the session row still lists', () => {
    role = 'viewer'
    renderWithProviders(<QuarantinePage />)
    expect(screen.queryByRole('button', { name: /Unquarantine/i })).not.toBeInTheDocument()
    expect(screen.getByText('sess_abc')).toBeInTheDocument()
  })

  it('editor also sees no release control (release is admin-only)', () => {
    role = 'editor'
    renderWithProviders(<QuarantinePage />)
    expect(screen.queryByRole('button', { name: /Unquarantine/i })).not.toBeInTheDocument()
  })
})
