import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { can } from '../../../lib/rbac'
import type { DecisionItem, TenantRole } from '../../../types/api'

/**
 * FX-3.1 — the per-detector facet options are DERIVED from the API's `winning_source`
 * values on the loaded rows (never a FE constant). When NO row carries the field
 * (backend field-add absent) the facet ships PARTIAL/disabled — no crash, no
 * hardcoded source list.
 */

let role: TenantRole = 'admin'
vi.mock('../../../lib/query/useMe', () => ({
  useCan: () => (cap: Parameters<typeof can>[1]) => can(role, cap),
}))

let items: DecisionItem[] = []
vi.mock('../../../lib/query/useDecisions', () => ({
  useDecisions: () => ({
    data: { pages: [{ items, total: items.length, next_token: null }] },
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

const base = (over: Partial<DecisionItem>): DecisionItem => ({
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

describe('ThreatsPage per-detector facet (FX-3.1)', () => {
  beforeEach(() => {
    role = 'admin'
  })

  it('derives facet options from the response winning_source values', () => {
    items = [
      base({ decision_id: 'd1', winning_source: 'sentra.sigma' }),
      base({ decision_id: 'd2', winning_source: 'sentra.policy' }),
      base({ decision_id: 'd3', winning_source: 'sentra.sigma' }),
    ]
    renderWithProviders(<ThreatsPage />)
    const facet = screen.getByRole('combobox', { name: /deciding source/i })
    expect(facet).toBeInTheDocument()
    // Options reflect the DISTINCT API values (Sigma, Policy), not a FE constant.
    const optionText = Array.from(facet.querySelectorAll('option')).map((o) => o.textContent)
    expect(optionText).toContain('Sigma')
    expect(optionText).toContain('Policy')
    // No fabricated source that wasn't in the data (e.g. ML Classifier).
    expect(optionText).not.toContain('Ml Classifier')
  })

  it('degrades to a PARTIAL/disabled facet (no crash) when winning_source is absent', () => {
    items = [base({ decision_id: 'd1' }), base({ decision_id: 'd2' })] // no winning_source
    renderWithProviders(<ThreatsPage />)
    expect(screen.queryByRole('combobox', { name: /deciding source/i })).not.toBeInTheDocument()
    expect(screen.getByTestId('source-facet-partial')).toBeInTheDocument()
    // Rows still render — no crash, no fabricated facet.
    expect(screen.getAllByText('Agent One').length).toBeGreaterThan(0)
  })

  // FXR-3 — selecting a deciding source actually FILTERS the rows (the green≠correct
  // gap: prior tests only checked option-derivation + PARTIAL degrade, never that the
  // predicate at ThreatsPage.tsx:102-104 filters). Reverting/inverting that predicate
  // must turn THIS test red.
  it('filters the rows to the selected winning_source (only sigma rows render)', async () => {
    items = [
      base({ decision_id: 'd1', winning_source: 'sentra.sigma', agent_name: 'Sigma Agent A' }),
      base({ decision_id: 'd2', winning_source: 'sentra.sigma', agent_name: 'Sigma Agent B' }),
      base({ decision_id: 'd3', winning_source: 'sentra.policy', agent_name: 'Policy Agent' }),
    ]
    renderWithProviders(<ThreatsPage />)

    // Before filtering: all three agents are visible + loaded count is 3.
    expect(screen.getByText('Sigma Agent A')).toBeInTheDocument()
    expect(screen.getByText('Policy Agent')).toBeInTheDocument()
    expect(screen.getByText(/3 loaded/)).toBeInTheDocument()

    const facet = screen.getByRole('combobox', { name: /deciding source/i })
    await userEvent.selectOptions(facet, 'sentra.sigma')

    // After selecting Sigma: only the two sigma rows remain; the policy row is gone.
    expect(screen.getByText('Sigma Agent A')).toBeInTheDocument()
    expect(screen.getByText('Sigma Agent B')).toBeInTheDocument()
    expect(screen.queryByText('Policy Agent')).not.toBeInTheDocument()
    // The loaded-count label updates to reflect the filtered set.
    expect(screen.getByText(/2 loaded/)).toBeInTheDocument()
  })

  // FXR-4 — the sourceLabel formatter title-cases a MULTI-token source
  // (`sentra.ml_classifier` → 'Ml Classifier'), not just single words.
  it('formats a multi-word winning_source as title-case in the facet options', () => {
    items = [
      base({ decision_id: 'd1', winning_source: 'sentra.ml_classifier' }),
      base({ decision_id: 'd2', winning_source: 'sentra.sigma' }),
    ]
    renderWithProviders(<ThreatsPage />)
    const facet = screen.getByRole('combobox', { name: /deciding source/i })
    const optionText = Array.from(within(facet).getAllByRole('option')).map((o) => o.textContent)
    expect(optionText).toContain('Ml Classifier') // multi-token title-case
    expect(optionText).toContain('Sigma')
  })
})
