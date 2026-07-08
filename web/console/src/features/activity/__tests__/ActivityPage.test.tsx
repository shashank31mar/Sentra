import { describe, it, expect, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { decisionDetailPath } from '../../../app/routes'
import type { DecisionItem } from '../../../types/api'

const ITEM: DecisionItem = {
  decision_id: 'sess1:req1',
  session_id: 'sess1',
  request_id: 'req1',
  agent_id: 'a1',
  agent_name: 'Payments Agent',
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
}))

import { ActivityPage } from '../ActivityPage'

describe('ActivityPage (M-G3.2)', () => {
  it('renders the near-real-time (≤15s pull) label — no streaming', () => {
    renderWithProviders(<ActivityPage />)
    expect(screen.getByText(/near-real-time \(≤15s pull\)/i)).toBeInTheDocument()
  })

  it('row trail link uses the composite decisionDetailPath(session_id, request_id)', () => {
    renderWithProviders(<ActivityPage />)
    const link = screen.getByRole('link', { name: /View trail/i })
    expect(link).toHaveAttribute('href', decisionDetailPath('sess1', 'req1'))
    // Both ids must be in the href (composite PK), never request_id alone.
    expect(link.getAttribute('href')).toContain('sess1')
    expect(link.getAttribute('href')).toContain('req1')
  })
})
