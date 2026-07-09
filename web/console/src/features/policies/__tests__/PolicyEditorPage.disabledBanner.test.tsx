import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Routes, Route } from 'react-router-dom'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { can } from '../../../lib/rbac'
import { ApiException } from '../../../lib/http'
import type { PolicyDetailView, TenantRole } from '../../../types/api'

/**
 * FXR-1 — the PolicyEditor "This policy is disabled. Enable it first." banner must fire
 * ONLY for the genuine disabled-policy 403 (server: "Cannot update disabled policy.
 * Enable it first.", policy_service.py:521) — NOT for a role-403 ("requires role >=
 * editor", deps.py:509) or a membership-403, which the old bare `status===403` branch
 * wrongly mislabeled as "disabled". For a role/membership 403 the page shows NO banner
 * (the global MutationCache bridge already surfaces the one sanitized toast).
 */

let role: TenantRole = 'editor'
vi.mock('../../../lib/query/useMe', () => ({
  useCan: () => (cap: Parameters<typeof can>[1]) => can(role, cap),
}))

const detail: PolicyDetailView = {
  policy_id: 'pol-1',
  name: 'payments-guardrails',
  status: 'active',
  version: '1.0.0',
  agent_id: 'payment-agent',
  platform: null,
  cloud_region: null,
  schema_version: 'v1',
  allowed_tools: ['query_orders'],
  allowed_agents: [],
  rules: [{ policy_id: 'rule-1', name: 'r', severity: 'medium', action: 'ALLOW' } as never],
  cross_cloud_dependencies: [],
  max_calls_per_minute: 30,
  max_refund_amount: null,
  created_by: null,
  updated_at: null,
  content_hash: null,
  s3_key: null,
  match_count_24h: null,
  content: null,
  policy_format: 'yaml',
  cedar_content: null,
  generator_version: null,
}

const updateMutate = vi.fn()
vi.mock('../../../lib/query/usePolicies', () => ({
  usePolicyDetail: () => ({ data: detail, isLoading: false, isError: false }),
  useCreatePolicy: () => ({ mutate: vi.fn(), isPending: false }),
  useUpdatePolicy: () => ({
    // Route the mutation's onError to the injected error for the test.
    mutate: (_body: unknown, opts: { onError?: (e: unknown) => void }) => updateMutate(opts),
    isPending: false,
  }),
}))

import { PolicyEditorPage } from '../PolicyEditorPage'

function mountEdit() {
  return renderWithProviders(
    <Routes>
      <Route path="/policies/:policyId/edit" element={<PolicyEditorPage />} />
    </Routes>,
    { routerEntries: ['/policies/pol-1/edit'] },
  )
}

async function submitWith(err: unknown) {
  updateMutate.mockImplementation((opts: { onError?: (e: unknown) => void }) => opts.onError?.(err))
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: /Save changes/i }))
}

describe('PolicyEditorPage disabled-policy banner keying (FXR-1)', () => {
  beforeEach(() => {
    role = 'editor'
    updateMutate.mockReset()
  })

  it('shows the "disabled" banner ONLY for the disabled-policy 403 reason', async () => {
    mountEdit()
    await submitWith(new ApiException(403, { error: 'Cannot update disabled policy. Enable it first.', error_code: 'FORBIDDEN' }))
    await waitFor(() =>
      expect(screen.getByText(/This policy is disabled\. Enable it first\./i)).toBeInTheDocument(),
    )
  })

  it('does NOT show the "disabled" banner for a role-403 (requires role >= editor)', async () => {
    mountEdit()
    await submitWith(new ApiException(403, { error: 'requires role >= editor', error_code: 'FORBIDDEN' }))
    // No misleading "disabled" banner — the global bridge surfaces the sanitized toast.
    await new Promise((r) => setTimeout(r, 0))
    expect(screen.queryByText(/This policy is disabled/i)).not.toBeInTheDocument()
  })

  it('does NOT show the "disabled" banner for a membership-403', async () => {
    mountEdit()
    await submitWith(new ApiException(403, { error: 'not a member of requested tenant', error_code: 'FORBIDDEN' }))
    await new Promise((r) => setTimeout(r, 0))
    expect(screen.queryByText(/This policy is disabled/i)).not.toBeInTheDocument()
  })

  it('still shows a specific banner for a 409 conflict (unchanged behavior)', async () => {
    mountEdit()
    await submitWith(new ApiException(409, { error: 'exists', error_code: 'CONFLICT' }))
    await waitFor(() =>
      expect(screen.getByText(/already exists\. Edit it instead\./i)).toBeInTheDocument(),
    )
  })
})
