import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import type { ReactElement, ReactNode } from 'react'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter, Routes, Route } from 'react-router-dom'
import { queryClient } from '../../app/queryClient'
import { ToastProvider } from '../../components/ui/Toast'
import { ApiException } from '../../lib/http'
import { can } from '../../lib/rbac'
import type {
  AgentListItem,
  CloudConnection,
  DiscoveredAgent,
  PolicySummary,
  SessionInfo,
  TenantRole,
} from '../../types/api'

/**
 * FXR-1 (green≠correct gap) — the 403-defer guard (`if (!isAuthDegrade403(e))`) is
 * applied at NINE real production `onError` sites across six pages, but the only prior
 * coverage was `queryClient.doubleToast.test.tsx`, which drives SYNTHETIC
 * Guarded/Unguarded buttons — not the real pages. The existing page tests
 * (ConnectAccountPage/AgentInventoryPage) mock the mutation hooks with `vi.fn()` and
 * never fire `onError`. Reverting any real page's guard would leave the whole suite
 * green — the exact green≠correct gap the sentinel flagged.
 *
 * These tests close it: each REAL page is mounted through the PRODUCTION singleton
 * `queryClient` (so its `MutationCache.onError` → `handleAuthDegrade` bridge is LIVE)
 * + a REAL `ToastProvider` (which registers the toast bridge on mount). Only the
 * `lib/api/*` seam is stubbed — the real query + mutation hooks run. We trigger the
 * real mutation control, let it 403, and assert EXACTLY ONE toast (the bridge's
 * sanitized message; the page defers). Reverting a page's `isAuthDegrade403` guard
 * makes that page also fire its own toast → TWO toasts → `toHaveLength(1)` turns red.
 * The CONTROL test at the bottom mounts an unguarded handler through the SAME singleton
 * and asserts TWO, proving the guarded assertions are load-bearing, not vacuous.
 */

let role: TenantRole = 'admin'
vi.mock('../../lib/query/useMe', () => ({
  useCan: () => (cap: Parameters<typeof can>[1]) => can(role, cap),
  usePlatformCan: () => () => true,
}))

vi.mock('../../lib/query/useCurrentUser', () => ({
  useCurrentUser: () => ({ data: { email: 'op@acme.io', name: 'Op', username: 'op', groups: [] } }),
}))

// ---- API seam stubs: each mutating call rejects a 403; reads resolve. ----
const forbidden = () =>
  new ApiException(403, { error: 'You no longer have permission.', error_code: 'FORBIDDEN' })

const attachPolicy = vi.fn(async () => {
  throw forbidden()
})
const detachPolicy = vi.fn(async () => {
  throw forbidden()
})
vi.mock('../../lib/api/agents', () => ({
  agentsApi: {
    list: async () => ({ agents: AGENTS, total: AGENTS.length }),
    detail: async () => ({}),
    tools: async () => ({ tools: [], total: 0 }),
    attachPolicy: () => attachPolicy(),
    detachPolicy: () => detachPolicy(),
  },
}))

const setPolicyStatus = vi.fn(async () => {
  throw forbidden()
})
const deletePolicy = vi.fn(async () => {
  throw forbidden()
})
vi.mock('../../lib/api/policies', () => ({
  policiesApi: {
    list: async () => ({ items: POLICIES, total: POLICIES.length, next_token: null }),
    setStatus: () => setPolicyStatus(),
    remove: () => deletePolicy(),
  },
  sigmaApi: {
    list: async () => ({ items: [], total: 0, next_token: null }),
  },
}))

const createConnection = vi.fn(async () => {
  throw forbidden()
})
const setAzureCreds = vi.fn(async () => {
  throw forbidden()
})
vi.mock('../../lib/api/connections', () => ({
  connectionsApi: {
    list: async () => ({ connections: [] as CloudConnection[] }),
    get: async () => AZURE_CONNECTION,
    create: () => createConnection(),
    scan: async () => ({ scan_id: 's', status: 'queued', discovered_count: null }),
    setAzureCredentials: () => setAzureCreds(),
    test: async () => ({ ok: true, agents_visible: 1, message: 'ok' }),
    remove: async () => undefined,
  },
}))

const importAgents = vi.fn(async () => {
  throw forbidden()
})
vi.mock('../../lib/api/discovery', () => ({
  discoveryApi: {
    summary: async () => ({ detected: 1, unmanaged: 1, new_24h: 0, providers_connected: 1, providers_total: 3, last_scan: null }),
    platforms: async () => ({ providers: [] }),
    agents: async () => ({ items: DISCOVERED, total: DISCOVERED.length, next_token: null }),
    import: () => importAgents(),
  },
}))

const releaseQuarantine = vi.fn(async () => {
  throw forbidden()
})
vi.mock('../../lib/api/sessions', () => ({
  sessionsApi: {
    list: async () => ({ sessions: SESSIONS, total: SESSIONS.length, next_token: null }),
    decisions: async () => ({ decisions: [] }),
    release: () => releaseQuarantine(),
  },
}))

// ---- fixtures ----
const AGENTS: AgentListItem[] = [
  {
    agent_id: 'ag_bound', name: 'Bound Agent', platform: 'bedrock', cloud_provider: 'aws',
    status: 'running', trust_score_avg: 90, requests_total: 10, requests_allowed: 9,
    requests_denied: 1, active_sessions: 1, last_seen: '2026-07-01T00:00:00Z', active_policy_id: 'pol_bound',
  },
  {
    agent_id: 'ag_unbound', name: 'Unbound Agent', platform: 'bedrock', cloud_provider: 'aws',
    status: 'running', trust_score_avg: 90, requests_total: 5, requests_allowed: 5,
    requests_denied: 0, active_sessions: 0, last_seen: '2026-07-01T00:00:00Z', active_policy_id: null,
  },
]

const POLICIES: PolicySummary[] = [
  { policy_id: 'pol_active', name: 'Active Policy', status: 'active', version: 1, agent_count: 1, updated_at: '2026-07-01T00:00:00Z', created_by: 'op@acme.io', policy_format: 'cedar', agent_id: 'ag_unbound' },
]

const AZURE_CONNECTION: CloudConnection = {
  id: 'conn_az', cloud_provider: 'azure', status: 'connecting', account_ref: 'acme-azure',
  external_id: null, aegion_principal_arn: null, role_arn: null,
  azure_subscription_id: null, azure_tenant_id: null, azure_client_id: null,
  scopes: [], agents_visible: null, last_scan: null, connected_at: null, error: null,
}

const DISCOVERED: DiscoveredAgent[] = [
  {
    id: 'disc_1', agent_id: null, native_resource_id: 'arn:aws:...:1', name: 'Detected One',
    cloud_provider: 'aws', framework: 'bedrock', first_seen: '2026-07-01T00:00:00Z',
    risk: 'high', status: 'not_imported', last_active: null,
  },
]

const SESSIONS: SessionInfo[] = [
  {
    session_id: 'sess_1', user_id: 'u1', agent_id: 'ag_bound', trust_score: 40,
    quarantine_status: 'quarantined', total_requests: 10, allow_count: 6, deny_count: 4,
    consecutive_allows: 0, created_at: '2026-07-01T00:00:00Z', last_activity: '2026-07-01T01:00:00Z',
  },
]

// ---- helpers ----
function mount(ui: ReactElement, entries: string[] = ['/']) {
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

/** Exactly one toast: the global bridge's sanitized message, page adds none. */
async function expectOneSanitizedToast() {
  const toasts = await screen.findAllByRole('status')
  expect(toasts).toHaveLength(1)
  expect(toasts[0]).toHaveTextContent('You no longer have permission.')
}

/** Click the confirm button INSIDE the open dialog (not the row trigger). */
async function confirmInDialog(user: ReturnType<typeof userEvent.setup>, name: RegExp | string) {
  const dialog = await screen.findByRole('dialog')
  await user.click(within(dialog).getByRole('button', { name }))
}

// The singleton client persists mutation state across tests; clear it + spies each time.
beforeEach(() => {
  role = 'admin'
  queryClient.clear()
  vi.clearAllMocks()
})
afterEach(() => queryClient.clear())

describe('FXR-1 — real page mutation 403 → exactly ONE toast (singleton MutationCache bridge)', () => {
  it('AgentInventoryPage: detach 403 → one toast (AgentInventoryPage.tsx:43)', async () => {
    const { AgentInventoryPage } = await import('../agents/AgentInventoryPage')
    const user = userEvent.setup()
    mount(<AgentInventoryPage />)

    await screen.findByText('Bound Agent')
    await user.click(screen.getByRole('button', { name: 'Detach' }))
    await confirmInDialog(user, 'Detach')

    await waitFor(() => expect(detachPolicy).toHaveBeenCalled())
    await expectOneSanitizedToast()
  })

  it('AttachPolicyModal: attach 403 → one toast (AttachPolicyModal.tsx:58)', async () => {
    const { AgentInventoryPage } = await import('../agents/AgentInventoryPage')
    const user = userEvent.setup()
    mount(<AgentInventoryPage />)

    await screen.findByText('Unbound Agent')
    await user.click(screen.getByRole('button', { name: 'Attach Policy' }))
    // Modal confirm button label is "Attach Policy"; the pre-selected policy makes it enabled.
    const dialog = await screen.findByRole('dialog')
    await waitFor(() => expect(within(dialog).getByRole('button', { name: 'Attach Policy' })).toBeEnabled())
    await user.click(within(dialog).getByRole('button', { name: 'Attach Policy' }))

    await waitFor(() => expect(attachPolicy).toHaveBeenCalled())
    await expectOneSanitizedToast()
  })

  it('PolicyLibraryPage: disable 403 → one toast (PolicyLibraryPage.tsx:85)', async () => {
    const { PolicyLibraryPage } = await import('../policies/PolicyLibraryPage')
    const user = userEvent.setup()
    mount(<PolicyLibraryPage />)

    await screen.findByText('Active Policy')
    // Active policy → toggle reads "Disable"; clicking opens the blast-radius confirm
    // dialog whose confirm button also reads "Disable" (scoped within the dialog).
    await user.click(screen.getByRole('button', { name: 'Disable' }))
    await confirmInDialog(user, 'Disable')

    await waitFor(() => expect(setPolicyStatus).toHaveBeenCalled())
    await expectOneSanitizedToast()
  })

  it('PolicyLibraryPage: delete 403 → one toast (PolicyLibraryPage.tsx:93)', async () => {
    const { PolicyLibraryPage } = await import('../policies/PolicyLibraryPage')
    const user = userEvent.setup()
    mount(<PolicyLibraryPage />)

    await screen.findByText('Active Policy')
    await user.click(screen.getByRole('button', { name: 'Delete' }))
    // The confirm dialog's confirm button also reads "Delete" (scoped within the dialog).
    await confirmInDialog(user, 'Delete')

    await waitFor(() => expect(deletePolicy).toHaveBeenCalled())
    await expectOneSanitizedToast()
  })

  it('ConnectAccountPage: create-connection 403 → one toast (ConnectAccountPage.tsx:132)', async () => {
    const { ConnectAccountPage } = await import('../connect/ConnectAccountPage')
    const user = userEvent.setup()
    mount(<ConnectAccountPage />)

    // Click the AWS tile → chooseCloud → create.mutate → 403.
    const awsTile = await screen.findByRole('button', { name: /AWS|Bedrock/i })
    await user.click(awsTile)

    await waitFor(() => expect(createConnection).toHaveBeenCalled())
    await expectOneSanitizedToast()
  })

  it('GrantAzureAccessCard: setAzureCredentials 403 → one toast (GrantAzureAccessCard.tsx:100)', async () => {
    const { GrantAzureAccessCard } = await import('../connect/GrantAzureAccessCard')
    const user = userEvent.setup()
    mount(<GrantAzureAccessCard connection={AZURE_CONNECTION} canOperate />)

    const guid = '00000000-0000-0000-0000-000000000001'
    await user.type(screen.getByLabelText(/Subscription ID/i), guid)
    await user.type(screen.getByLabelText(/Tenant ID/i), guid)
    await user.type(screen.getByLabelText(/Client ID/i), guid)
    await user.type(screen.getByLabelText(/Secret reference/i), 'aegion/azure/sp-secret')

    await user.click(screen.getByRole('button', { name: /Connect & test|Re-test/i }))

    await waitFor(() => expect(setAzureCreds).toHaveBeenCalled())
    await expectOneSanitizedToast()
  })

  it('ImportAgentsPage: import 403 → one toast (ImportAgentsPage.tsx:96)', async () => {
    const { ImportAgentsPage } = await import('../import/ImportAgentsPage')
    const user = userEvent.setup()
    mount(<ImportAgentsPage />)

    const checkbox = await screen.findByRole('checkbox', { name: /Select Detected One for import/i })
    await user.click(checkbox)
    await user.click(screen.getByRole('button', { name: /^Import/i }))

    await waitFor(() => expect(importAgents).toHaveBeenCalled())
    await expectOneSanitizedToast()
  })

  it('SessionForensicsPage: release-quarantine 403 → one toast (SessionForensicsPage.tsx:56)', async () => {
    const { SessionForensicsPage } = await import('../forensics/SessionForensicsPage')
    const user = userEvent.setup()
    mount(
      <Routes>
        <Route path="/sessions/:sessionId" element={<SessionForensicsPage />} />
      </Routes>,
      ['/sessions/sess_1'],
    )

    await user.click(await screen.findByRole('button', { name: /Release/i }))

    await waitFor(() => expect(releaseQuarantine).toHaveBeenCalled())
    await expectOneSanitizedToast()
  })

  it('CONTROL: an UNGUARDED page handler produces TWO toasts through the SAME singleton (guard is load-bearing)', async () => {
    // Mirrors the OLD buggy pattern (toast on EVERY error incl. a 403) driven through
    // the production singleton client — proves the guarded assertions above are not
    // vacuous: without the guard, the page toast stacks on the bridge toast.
    const { useMutation } = await import('@tanstack/react-query')
    const { useToast } = await import('../../components/ui/Toast')
    function Unguarded() {
      const { error } = useToast()
      const m = useMutation({
        mutationFn: async () => {
          throw forbidden()
        },
        retry: false,
        onError: () => error('Could not perform the action. Please try again.'),
      })
      return <button onClick={() => m.mutate()}>run</button>
    }
    const user = userEvent.setup()
    mount(<Unguarded />)
    await user.click(screen.getByRole('button', { name: 'run' }))
    await waitFor(() => expect(screen.getAllByRole('status')).toHaveLength(2))
  })
})
