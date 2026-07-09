import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { can } from '../../../lib/rbac'
import type { DecisionItem, TenantRole } from '../../../types/api'

/**
 * #4 — the threat_type facet is a SERVER-side filter: selecting a type must pass
 * `threat_type` into the useDecisions() server filters (backend `?threat_type=`),
 * so an analyst gets the WHOLE matching set via the cursor, NOT just loaded rows.
 * This test asserts the filter reaches the server call (the winning_source facet,
 * by contrast, filters client-side and never touches the server args).
 */

let role: TenantRole = 'admin'
vi.mock('../../../lib/query/useMe', () => ({
  useCan: () => (cap: Parameters<typeof can>[1]) => can(role, cap),
}))

// Capture the filters useDecisions is invoked with (the server-side contract under test).
const decisionsFilters = vi.fn()
let items: DecisionItem[] = []
vi.mock('../../../lib/query/useDecisions', () => ({
  useDecisions: (filters: unknown) => {
    decisionsFilters(filters)
    return {
      data: { pages: [{ items, total: items.length, next_token: null }] },
      isLoading: false,
      isError: false,
      error: null,
      hasNextPage: false,
      isFetchingNextPage: false,
      fetchNextPage: vi.fn(),
      refetch: vi.fn(),
    }
  },
  useQuarantine: () => ({ mutate: vi.fn(), isPending: false, variables: undefined }),
}))
vi.mock('../../../lib/query/useSessions', () => ({
  useSessions: () => ({ data: { sessions: [], total: 0 } }),
}))

import { ThreatsPage } from '../ThreatsPage'

const row = (over: Partial<DecisionItem>): DecisionItem => ({
  decision_id: over.decision_id ?? 'sess1:req1',
  session_id: 'sess1',
  request_id: 'req1',
  agent_id: 'a1',
  agent_name: 'Agent One',
  cloud_provider: 'aws',
  platform: null,
  decision: 'DENY',
  threat_type: 'PROMPT_INJECTION',
  tool_name: 'refund',
  reason: 'blocked',
  trust_score: 40,
  timestamp: '2026-07-01T00:00:00Z',
  ...over,
})

describe('ThreatsPage threat_type facet (#4 — server-side)', () => {
  beforeEach(() => {
    role = 'admin'
    items = [row({ decision_id: 'd1' })]
    decisionsFilters.mockClear()
  })

  it('renders a threat-type facet with the enum options', () => {
    renderWithProviders(<ThreatsPage />)
    const facet = screen.getByRole('combobox', { name: /filter by threat type/i })
    expect(facet).toBeInTheDocument()
    const optionText = Array.from(facet.querySelectorAll('option')).map((o) => o.textContent)
    expect(optionText).toContain('All threat types')
    expect(optionText).toContain('Prompt Injection')
    expect(optionText).toContain('Data Exfiltration')
  })

  it('does NOT send threat_type until a type is chosen (default = all)', () => {
    renderWithProviders(<ThreatsPage />)
    // Initial call: decision=DENY default, no threat_type.
    const last = decisionsFilters.mock.calls.at(-1)?.[0] as Record<string, unknown>
    expect(last).not.toHaveProperty('threat_type')
  })

  it('SERVER-side: selecting a threat type passes threat_type into the useDecisions filters', async () => {
    renderWithProviders(<ThreatsPage />)
    const facet = screen.getByRole('combobox', { name: /filter by threat type/i })
    await userEvent.selectOptions(facet, 'DATA_EXFILTRATION')
    // The page must RE-QUERY the server with threat_type — not filter client-side.
    const last = decisionsFilters.mock.calls.at(-1)?.[0] as Record<string, unknown>
    expect(last).toMatchObject({ threat_type: 'DATA_EXFILTRATION' })
  })

  it('clearing back to All removes threat_type from the server filters', async () => {
    renderWithProviders(<ThreatsPage />)
    const facet = screen.getByRole('combobox', { name: /filter by threat type/i })
    await userEvent.selectOptions(facet, 'JAILBREAK')
    expect((decisionsFilters.mock.calls.at(-1)?.[0] as Record<string, unknown>)).toMatchObject({
      threat_type: 'JAILBREAK',
    })
    await userEvent.selectOptions(facet, '__all__')
    expect((decisionsFilters.mock.calls.at(-1)?.[0] as Record<string, unknown>)).not.toHaveProperty(
      'threat_type',
    )
  })
})
