import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { can } from '../../../lib/rbac'
import type { TenantRole } from '../../../types/api'

/**
 * FX-2.2 — the PolicyEditor Save/Create submit is gated on `policies.write` (editor):
 * a viewer sees no submit control, an editor does. The route guard (RequireCan) is a
 * separate belt; this asserts the in-page render gate.
 */

let role: TenantRole = 'viewer'
vi.mock('../../../lib/query/useMe', () => ({
  useCan: () => (cap: Parameters<typeof can>[1]) => can(role, cap),
}))

vi.mock('../../../lib/query/usePolicies', () => ({
  usePolicyDetail: () => ({ data: undefined, isLoading: false, isError: false }),
  useCreatePolicy: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdatePolicy: () => ({ mutate: vi.fn(), isPending: false }),
}))

import { PolicyEditorPage } from '../PolicyEditorPage'

describe('PolicyEditorPage write gate (FX-2.2)', () => {
  beforeEach(() => {
    role = 'viewer'
  })

  it('viewer sees NO Create submit control', () => {
    role = 'viewer'
    renderWithProviders(<PolicyEditorPage />, { routerEntries: ['/policies/new'] })
    expect(screen.queryByRole('button', { name: /Create policy/i })).not.toBeInTheDocument()
    // Cancel is always available.
    expect(screen.getByRole('button', { name: /Cancel/i })).toBeInTheDocument()
  })

  it('editor sees the Create submit control', () => {
    role = 'editor'
    renderWithProviders(<PolicyEditorPage />, { routerEntries: ['/policies/new'] })
    expect(screen.getByRole('button', { name: /Create policy/i })).toBeInTheDocument()
  })
})
