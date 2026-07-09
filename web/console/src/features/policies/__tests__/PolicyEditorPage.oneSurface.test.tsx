import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import type { ReactElement, ReactNode } from 'react'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { queryClient } from '../../../app/queryClient'
import { ToastProvider } from '../../../components/ui/Toast'
import { ApiException } from '../../../lib/http'
import { queryKeys } from '../../../lib/queryKeys'
import { can } from '../../../lib/rbac'
import type { PolicyDetailView, TenantRole } from '../../../types/api'

/**
 * FXR-1 (green≠correct gap) — a genuine disabled-policy 403 must surface ONE surface,
 * not two. The prior test (`PolicyEditorPage.disabledBanner.test.tsx`) mocks
 * `useUpdatePolicy` directly and calls `opts.onError` itself, BYPASSING the real
 * singleton client / MutationCache — so it can only observe the page banner and is
 * structurally blind to (a) whether the global `MutationCache.onError` bridge ALSO
 * fires a sanitized toast for the same 403, and (b) whether it spuriously invalidates
 * the `['auth','context']` operator-context query (treating a resource-state refusal
 * as an auth-degrade).
 *
 * This test drives the REAL page through the PRODUCTION singleton `queryClient` (real
 * `useUpdatePolicy` → `policiesApi.update` rejecting a 403 → the live
 * `MutationCache.onError` bridge) + a REAL `ToastProvider`, mocking only the api seam.
 * It asserts:
 *   - disabled-policy 403 → ONLY the "Enable it first" banner (NO bridge toast, NO
 *     auth-context invalidation) — the "one surface, not two" contract; AND
 *   - a role-403 → NO banner + exactly ONE sanitized bridge toast + auth-context
 *     IS invalidated (a real demotion). This is the CONTROL that proves the fix
 *     discriminates the two reasons rather than blanket-excluding all 403s.
 */

let role: TenantRole = 'editor'
vi.mock('../../../lib/query/useMe', () => ({
  useCan: () => (cap: Parameters<typeof can>[1]) => can(role, cap),
}))

vi.mock('../../../lib/query/useCurrentUser', () => ({
  useCurrentUser: () => ({ data: { email: 'op@acme.io', name: 'Op', username: 'op', groups: [] } }),
}))

const DETAIL: PolicyDetailView = {
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

const updatePolicy = vi.fn()
vi.mock('../../../lib/api/policies', () => ({
  policiesApi: {
    detail: async () => DETAIL,
    update: (...a: unknown[]) => updatePolicy(...a),
  },
}))
// PolicyEditor imports agentsApi (attach on create); never called on the edit path.
vi.mock('../../../lib/api/agents', () => ({
  agentsApi: { attachPolicy: vi.fn() },
}))

function mount(ui: ReactElement, entries: string[]) {
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <MemoryRouter initialEntries={entries}>{children}</MemoryRouter>
        </ToastProvider>
      </QueryClientProvider>
    )
  }
  return render(ui, { wrapper: Wrapper })
}

async function mountEditAndSubmit(err: unknown) {
  const { PolicyEditorPage } = await import('../PolicyEditorPage')
  updatePolicy.mockRejectedValue(err)
  const user = userEvent.setup()
  mount(
    <Routes>
      <Route path="/policies/:policyId/edit" element={<PolicyEditorPage />} />
    </Routes>,
    ['/policies/pol-1/edit'],
  )
  await screen.findByRole('button', { name: /Save changes/i })
  await user.click(screen.getByRole('button', { name: /Save changes/i }))
  await waitFor(() => expect(updatePolicy).toHaveBeenCalled())
}

beforeEach(() => {
  role = 'editor'
  queryClient.clear()
  vi.clearAllMocks()
})
afterEach(() => queryClient.clear())

describe('FXR-1 — PolicyEditor disabled-policy 403 shows ONE surface, not two (singleton bridge)', () => {
  it('disabled-policy 403 → ONLY the banner: NO bridge toast, NO auth-context invalidation', async () => {
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
    await mountEditAndSubmit(
      new ApiException(403, { error: 'Cannot update disabled policy. Enable it first.', error_code: 'FORBIDDEN' }),
    )

    // Surface 1 (the ONLY one): the actionable page banner.
    await waitFor(() =>
      expect(screen.getByText(/This policy is disabled\. Enable it first\./i)).toBeInTheDocument(),
    )

    // Surface 2 must NOT appear: the global MutationCache bridge must not toast a
    // disabled-policy 403 (it is a resource-state refusal, not an auth-degrade).
    await new Promise((r) => setTimeout(r, 20))
    expect(screen.queryByText(/You no longer have permission/i)).not.toBeInTheDocument()
    // The generic bridge fallback message must also be absent.
    expect(screen.queryAllByRole('status')).toHaveLength(0)

    // And it must NOT spuriously invalidate the operator context (a needless role re-read).
    const invalidatedAuthContext = invalidateSpy.mock.calls.some((c) => {
      const key = (c[0] as { queryKey?: unknown[] } | undefined)?.queryKey
      return JSON.stringify(key) === JSON.stringify(queryKeys.auth.context())
    })
    expect(invalidatedAuthContext).toBe(false)
  })

  it('CONTROL: a role-403 → NO banner + exactly ONE bridge toast + auth-context IS invalidated', async () => {
    const invalidateSpy = vi.spyOn(queryClient, 'invalidateQueries')
    await mountEditAndSubmit(
      new ApiException(403, { error: 'requires role >= editor', error_code: 'FORBIDDEN' }),
    )

    // A role-403 is a genuine auth-degrade: no misleading "disabled" banner …
    await new Promise((r) => setTimeout(r, 20))
    expect(screen.queryByText(/This policy is disabled/i)).not.toBeInTheDocument()
    // … exactly ONE sanitized bridge toast (the ApiException message) …
    const toasts = await screen.findAllByRole('status')
    expect(toasts).toHaveLength(1)
    expect(toasts[0]).toHaveTextContent('requires role >= editor')
    // … and the operator context IS re-read (the fail-secure demotion path).
    const invalidatedAuthContext = invalidateSpy.mock.calls.some((c) => {
      const key = (c[0] as { queryKey?: unknown[] } | undefined)?.queryKey
      return JSON.stringify(key) === JSON.stringify(queryKeys.auth.context())
    })
    expect(invalidatedAuthContext).toBe(true)
  })
})
