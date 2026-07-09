import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { platformCan } from '../../../lib/rbac'
import type { PolicySummary, SigmaRule } from '../../../types/api'

/**
 * FX-1.1 — the Sigma enable/disable toggle is a FLEET-GLOBAL kill-switch gated
 * server-side on `require_platform` (`PATCH /sigma-rules/{id}`). The client render
 * gate must HIDE it for a non-platform operator (`usePlatformCan('sigma.retire')`)
 * — a tenant admin must not see a control they can't use. This test FAILS if the
 * toggle renders for a non-platform operator, or if it stops firing for a platform one.
 */

// Drive usePlatformCan() off a settable is_platform flag through the REAL platform map.
let isPlatform = false
// useCan is unused here (no policy write controls exercised) but the page calls it.
vi.mock('../../../lib/query/useMe', () => ({
  useCan: () => () => false,
  usePlatformCan: () => (cap: Parameters<typeof platformCan>[1]) => platformCan(isPlatform, cap),
}))

const RULE: SigmaRule = {
  rule_id: 'sig_1',
  title: 'Instruction Override',
  category: 'prompt_injection',
  severity: 'high',
  status: 'enabled',
  match_count: 12,
}

const toggleMutate = vi.fn()

const infinite = <T,>(items: T[]) => ({
  data: { pages: [{ items, total: items.length, next_token: null }] },
  isLoading: false,
  isError: false,
  error: null,
  refetch: vi.fn(),
})

vi.mock('../../../lib/query/usePolicies', () => ({
  usePolicies: () => infinite([] as PolicySummary[]),
  useSigmaRules: () => infinite([RULE]),
  useSigmaRuleContent: () => ({ data: null, isLoading: false, isError: false }),
  useToggleSigmaRule: () => ({ mutate: toggleMutate, isPending: false }),
  useSetPolicyStatus: () => ({ mutate: vi.fn(), isPending: false }),
  useDeletePolicy: () => ({ mutate: vi.fn(), isPending: false }),
}))

import { PolicyLibraryPage } from '../PolicyLibraryPage'

describe('PolicyLibraryPage — Sigma toggle platform gate (FX-1.1)', () => {
  beforeEach(() => {
    isPlatform = false
    toggleMutate.mockReset()
  })

  it('HIDES the enable/disable toggle for a non-platform operator', () => {
    isPlatform = false
    renderWithProviders(<PolicyLibraryPage />)
    // The rule still lists (read is allowed)…
    expect(screen.getByText('Instruction Override')).toBeInTheDocument()
    // …but the toggle (and its column header) are absent.
    expect(screen.queryByRole('button', { name: /Disable rule|Enable rule/ })).not.toBeInTheDocument()
    expect(screen.queryByText('Enabled')).not.toBeInTheDocument()
  })

  it('SHOWS the toggle for a platform operator and fires toggle.mutate', async () => {
    isPlatform = true
    renderWithProviders(<PolicyLibraryPage />)
    const btn = screen.getByRole('button', { name: /Disable rule/ })
    expect(btn).toBeInTheDocument()
    await userEvent.click(btn)
    expect(toggleMutate).toHaveBeenCalledWith({ ruleId: 'sig_1', status: 'disabled' })
  })
})
