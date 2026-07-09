import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Routes, Route } from 'react-router-dom'
import { renderWithProviders } from '../../../test/renderWithProviders'
import type { PolicyDetailView } from '../../../types/api'

/**
 * FX-3.3 — Policy Detail Cedar tab renders the COMPILED body only when present.
 * When there is no compiled Cedar, the Cedar tab degrades to a PARTIAL panel —
 * NEVER a client-fabricated `permit(...)/forbid(...)` body. YAML stays the default.
 */

const mockDetail = vi.fn()
vi.mock('../../../lib/query/usePolicies', () => ({
  usePolicyDetail: () => mockDetail(),
}))

import { PolicyDetailPage } from '../PolicyDetailPage'

const base = (over: Partial<PolicyDetailView>): PolicyDetailView => ({
  policy_id: 'pol_1',
  name: 'Refund Cap',
  status: 'active',
  version: '1',
  agent_id: 'agt-1',
  platform: null,
  cloud_region: null,
  schema_version: 'v1',
  allowed_tools: ['refund'],
  allowed_agents: [],
  rules: [{ policy_id: 'r1', name: 'deny big', action: 'DENY', severity: 'high' }],
  cross_cloud_dependencies: [],
  max_calls_per_minute: 30,
  max_refund_amount: 500,
  created_by: 'dana',
  updated_at: '2026-07-01T00:00:00Z',
  content_hash: null,
  s3_key: null,
  match_count_24h: 0,
  content: { allowed_tools: ['refund'] },
  policy_format: 'yaml',
  cedar_content: null,
  generator_version: null,
  ...over,
})

function mount() {
  return renderWithProviders(
    <Routes>
      <Route path="/policies/:policyId" element={<PolicyDetailPage />} />
    </Routes>,
    { routerEntries: ['/policies/pol_1'] },
  )
}

describe('PolicyDetailPage Cedar/JSON PARTIAL degrade (FX-3.3)', () => {
  beforeEach(() => mockDetail.mockReset())

  it('renders the COMPILED Cedar body verbatim when cedar_content is present', async () => {
    mockDetail.mockReturnValue({
      data: base({
        policy_format: 'cedar',
        cedar_content: 'permit ( principal, action, resource ) when { context.ok };',
      }),
      isLoading: false,
      isError: false,
    })
    mount()
    // Switch to the Cedar tab.
    await userEvent.click(screen.getByRole('button', { name: 'CEDAR' }))
    expect(screen.queryByTestId('cedar-partial')).not.toBeInTheDocument()
    expect(screen.getByText(/context\.ok/)).toBeInTheDocument()
  })

  it('shows a PARTIAL panel (no fabricated permit/forbid) when there is no compiled Cedar', async () => {
    mockDetail.mockReturnValue({
      data: base({ policy_format: 'yaml', cedar_content: null }),
      isLoading: false,
      isError: false,
    })
    mount()
    await userEvent.click(screen.getByRole('button', { name: 'CEDAR' }))
    expect(screen.getByTestId('cedar-partial')).toBeInTheDocument()
    // The synthetic projection must NOT be rendered as the enforced policy.
    expect(screen.queryByText(/^permit \(/)).not.toBeInTheDocument()
    expect(screen.queryByText(/forbid \(/)).not.toBeInTheDocument()
  })
})
