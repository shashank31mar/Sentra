import { describe, it, expect, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import { renderWithProviders } from '../../../test/renderWithProviders'

const traceProps = vi.fn()
vi.mock('../../../components/decisions/DecisionTrace', () => ({
  DecisionTrace: (props: { sessionId: string; requestId?: string }) => {
    traceProps(props)
    return <div data-testid="trace">trace {props.sessionId}</div>
  },
}))

import { SessionForensicsPage } from '../SessionForensicsPage'

describe('SessionForensicsPage (M-G3.5)', () => {
  it('renders the per-request trace for the session (no requestId narrowing)', () => {
    renderWithProviders(
      <Routes>
        <Route path="/sessions/:sessionId" element={<SessionForensicsPage />} />
      </Routes>,
      { routerEntries: ['/sessions/sess-abc'] },
    )
    expect(traceProps).toHaveBeenCalledWith({ sessionId: 'sess-abc' })
    expect(screen.getByTestId('trace')).toHaveTextContent('sess-abc')
  })
})
