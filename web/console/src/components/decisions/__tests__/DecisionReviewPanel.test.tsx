import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { can } from '../../../lib/rbac'
import type { TenantRole, DecisionItem } from '../../../types/api'

let role: TenantRole = 'viewer'
vi.mock('../../../lib/query/useMe', () => ({
  useCan: () => (cap: Parameters<typeof can>[1]) => can(role, cap),
}))
vi.mock('../../../lib/query/useDecisions', () => ({
  useVerdict: () => ({ mutate: vi.fn(), isPending: false, isSuccess: false, data: undefined }),
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
  threat_type: null,
  tool_name: null,
  reason: null,
  trust_score: 40,
  timestamp: '2026-07-01T00:00:00Z',
}

import { DecisionReviewPanel } from '../DecisionReviewPanel'

describe('DecisionReviewPanel verdict gating (G2.4)', () => {
  beforeEach(() => {
    role = 'viewer'
  })

  it('editor sees the verdict controls', () => {
    role = 'editor'
    renderWithProviders(<DecisionReviewPanel item={ITEM} />)
    expect(screen.getByRole('button', { name: /False Positive/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Confirm Threat/i })).toBeInTheDocument()
  })

  it('viewer sees no verdict controls (panel renders nothing)', () => {
    role = 'viewer'
    renderWithProviders(<DecisionReviewPanel item={ITEM} />)
    expect(screen.queryByRole('button', { name: /False Positive/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Confirm/i })).not.toBeInTheDocument()
  })
})
