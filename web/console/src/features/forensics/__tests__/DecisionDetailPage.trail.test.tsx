import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { ApiException } from '../../../lib/http'
import type { SessionTrail } from '../../../types/api'

/**
 * FX-1.2 — Decision-detail binds the WS-D server-recomputed trail
 * (`GET /v1/sessions/{id}/trail`), rendering the four coverage buckets +
 * winning_source. On a 404 it degrades to a PARTIAL banner + the legacy DecisionTrace
 * fallback (never blank, never fabricated).
 */

const mockUseSessionTrail = vi.fn()
vi.mock('../../../lib/query/useSessions', () => ({
  useSessionTrail: (sessionId: string, requestId: string) => mockUseSessionTrail(sessionId, requestId),
}))

// The PARTIAL fallback renders the legacy trace — stub it so we can detect it.
const traceProps = vi.fn()
vi.mock('../../../components/decisions/DecisionTrace', () => ({
  DecisionTrace: (props: { sessionId: string; requestId?: string }) => {
    traceProps(props)
    return <div data-testid="legacy-trace">legacy {props.sessionId}/{props.requestId}</div>
  },
}))

import { DecisionDetailPage } from '../DecisionDetailPage'

const TRAIL: SessionTrail = {
  session_id: 'sess1',
  request_id: 'req9',
  phase: 'request',
  winning_source: 'sentra.sigma',
  winning_source_display: 'Sigma',
  block_point: 'sentra.sigma',
  decision: 'DENY',
  coverage: [
    { source: 'sentra.trust', state: 'ran', decision: 'ALLOW', reason: null, latency_ms: 2, display_name: 'Trust', state_label: 'ran' },
    { source: 'sentra.sigma', state: 'ran', decision: 'DENY', reason: 'matched injection rule', latency_ms: 5, display_name: 'Sigma', state_label: 'ran' },
    { source: 'sentra.ml_classifier', state: 'not_run', decision: null, reason: null, latency_ms: null, display_name: 'ML Classifier', state_label: 'skipped' },
  ],
  coverage_total: 3,
  ran_count: 2,
  abstain_count: 0,
  ran_error_count: 0,
  not_run_count: 1,
  next_token: null,
}

function mount() {
  return renderWithProviders(
    <Routes>
      <Route path="/decisions/:sessionId/:requestId" element={<DecisionDetailPage />} />
    </Routes>,
    { routerEntries: ['/decisions/sess1/req9'] },
  )
}

describe('DecisionDetailPage — WS-D trail binding (FX-1.2)', () => {
  beforeEach(() => {
    mockUseSessionTrail.mockReset()
    traceProps.mockReset()
  })

  it('binds /trail with BOTH ids and renders the buckets + winning_source', () => {
    mockUseSessionTrail.mockReturnValue({ data: TRAIL, isLoading: false, isError: false })
    mount()
    // Bound with the composite PK (session + request).
    expect(mockUseSessionTrail).toHaveBeenCalledWith('sess1', 'req9')
    // Coverage buckets rendered from the server shape.
    expect(screen.getByTestId('trail-view')).toBeInTheDocument()
    expect(screen.getByText('Sigma')).toBeInTheDocument()
    expect(screen.getByText(/blocked at Sigma/)).toBeInTheDocument()
    expect(screen.getByText('matched injection rule')).toBeInTheDocument()
    // The legacy client reconstruction is NOT the primary path.
    expect(screen.queryByTestId('legacy-trace')).not.toBeInTheDocument()
  })

  it('on 404 shows a PARTIAL banner + the legacy trace fallback (not blank)', () => {
    mockUseSessionTrail.mockReturnValue({
      isLoading: false,
      isError: true,
      error: new ApiException(404, { error: 'trail not found', error_code: 'NOT_FOUND' }),
    })
    mount()
    expect(screen.getByTestId('trail-partial-banner')).toBeInTheDocument()
    expect(screen.getByTestId('legacy-trace')).toHaveTextContent('sess1/req9')
    expect(screen.queryByTestId('trail-view')).not.toBeInTheDocument()
  })
})
