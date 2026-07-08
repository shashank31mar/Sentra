import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { can } from '../../../lib/rbac'
import type { TenantRole } from '../../../types/api'
import type { PolicySummary } from '../../../types/api'

// Drive useCan() off a settable role using the REAL capability map.
let role: TenantRole = 'viewer'
vi.mock('../../../lib/query/useMe', () => ({
  useCan: () => (cap: Parameters<typeof can>[1]) => can(role, cap),
}))

const POLICY: PolicySummary = {
  policy_id: 'pol_1',
  name: 'Refund Cap',
  status: 'active',
  version: 1,
  agent_count: 3,
  updated_at: '2026-07-01T00:00:00Z',
  created_by: 'dana',
  policy_format: 'cedar',
}

const infinite = <T,>(items: T[]) => ({
  data: { pages: [{ items, total: items.length, next_token: null }] },
  isLoading: false,
  isError: false,
  error: null,
  refetch: vi.fn(),
})

vi.mock('../../../lib/query/usePolicies', () => ({
  usePolicies: () => infinite([POLICY]),
  useSigmaRules: () => infinite([]),
  useSigmaRuleContent: () => ({ data: null, isLoading: false, isError: false }),
  useToggleSigmaRule: () => ({ mutate: vi.fn(), isPending: false }),
  useSetPolicyStatus: () => ({ mutate: vi.fn(), isPending: false }),
  useDeletePolicy: () => ({ mutate: vi.fn(), isPending: false }),
}))

import { PolicyLibraryPage } from '../PolicyLibraryPage'

describe('PolicyLibraryPage RBAC gating (G2.2)', () => {
  beforeEach(() => {
    role = 'viewer'
  })

  it('viewer sees none of New/Edit/Disable/Delete', () => {
    role = 'viewer'
    renderWithProviders(<PolicyLibraryPage />)
    expect(screen.queryByRole('button', { name: /New Policy/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit' })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Disable|Enable/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
    // Read still works — the policy row renders.
    expect(screen.getByText('Refund Cap')).toBeInTheDocument()
  })

  it('editor sees New/Edit/Disable but NOT Delete', () => {
    role = 'editor'
    renderWithProviders(<PolicyLibraryPage />)
    expect(screen.getByRole('button', { name: /New Policy/i })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Edit' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Disable' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Delete' })).not.toBeInTheDocument()
  })

  it('admin sees Delete', () => {
    role = 'admin'
    renderWithProviders(<PolicyLibraryPage />)
    expect(screen.getByRole('button', { name: 'Delete' })).toBeInTheDocument()
  })
})
