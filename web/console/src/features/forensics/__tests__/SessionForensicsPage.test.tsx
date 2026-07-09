import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { can } from '../../../lib/rbac'
import type { SessionInfo, TenantRole } from '../../../types/api'

/**
 * FX-1.3 — Session forensics renders the canvas Decision-Trail summary header from
 * `SessionInfo` (trust / deny counts / quarantine badge / timeline) above the trace.
 * The Release control is admin-only (`quarantine.manage`) — hidden for a viewer.
 */

const SESSION: SessionInfo = {
  session_id: 'sess-abc',
  user_id: 'u1',
  agent_id: 'agt-1',
  trust_score: 42,
  quarantine_status: 'quarantined',
  total_requests: 20,
  allow_count: 12,
  deny_count: 8,
  consecutive_allows: 0,
  created_at: '2026-07-01T00:00:00Z',
  last_activity: '2026-07-01T01:00:00Z',
}

const mockUseSessionInfo = vi.fn()
const releaseMutate = vi.fn()
vi.mock('../../../lib/query/useSessions', () => ({
  useSessionInfo: () => mockUseSessionInfo(),
  useReleaseQuarantine: () => ({ mutate: releaseMutate, isPending: false }),
}))

let role: TenantRole = 'viewer'
vi.mock('../../../lib/query/useMe', () => ({
  useCan: () => (cap: Parameters<typeof can>[1]) => can(role, cap),
}))

// Stub the trace so the test targets the header only.
vi.mock('../../../components/decisions/DecisionTrace', () => ({
  DecisionTrace: (props: { sessionId: string }) => <div data-testid="trace">{props.sessionId}</div>,
}))

import { SessionForensicsPage } from '../SessionForensicsPage'

function mount() {
  return renderWithProviders(
    <Routes>
      <Route path="/sessions/:sessionId" element={<SessionForensicsPage />} />
    </Routes>,
    { routerEntries: ['/sessions/sess-abc'] },
  )
}

describe('SessionForensicsPage summary header (FX-1.3)', () => {
  beforeEach(() => {
    role = 'viewer'
    mockUseSessionInfo.mockReset()
    releaseMutate.mockReset()
    mockUseSessionInfo.mockReturnValue({ session: SESSION, isLoading: false, isError: false })
  })

  it('renders trust score, deny counts, and the quarantine badge from SessionInfo', () => {
    role = 'admin'
    mount()
    expect(screen.getByText('42')).toBeInTheDocument() // trust score
    expect(screen.getByText('8')).toBeInTheDocument() // deny count
    expect(screen.getByText('Quarantined')).toBeInTheDocument()
    expect(screen.getByTestId('trace')).toHaveTextContent('sess-abc')
  })

  it('shows the Release control for an admin (quarantine.manage)', () => {
    role = 'admin'
    mount()
    expect(screen.getByRole('button', { name: /Release/i })).toBeInTheDocument()
  })

  it('HIDES the Release control for a viewer', () => {
    role = 'viewer'
    mount()
    expect(screen.queryByRole('button', { name: /Release/i })).not.toBeInTheDocument()
    // Header still renders (read is allowed).
    expect(screen.getByText('42')).toBeInTheDocument()
  })

  // FX-1.3 (green≠correct gap): a FAILED session-list fetch must NOT be conflated
  // with a legitimately-absent row. On isError the page surfaces an honest error,
  // not the benign "not in the current window" all-clear note.
  it('shows an ERROR note (not the benign "not in window" note) when the fetch FAILS', () => {
    mockUseSessionInfo.mockReturnValue({ session: null, isLoading: false, isError: true, error: new Error('boom') })
    mount()
    expect(screen.getByTestId('session-summary-error')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent(/Could not load the session summary/i)
    // The benign absent-row note must NOT show — that would hide the failure.
    expect(screen.queryByText(/not in the current window/i)).not.toBeInTheDocument()
    // The trace still attempts its own load below.
    expect(screen.getByTestId('trace')).toHaveTextContent('sess-abc')
  })

  it('shows the benign "not in window" note when the row is absent WITHOUT an error', () => {
    mockUseSessionInfo.mockReturnValue({ session: null, isLoading: false, isError: false })
    mount()
    expect(screen.getByText(/not in the current window/i)).toBeInTheDocument()
    expect(screen.queryByTestId('session-summary-error')).not.toBeInTheDocument()
  })
})
