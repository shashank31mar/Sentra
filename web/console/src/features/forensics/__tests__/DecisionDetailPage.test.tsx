import { describe, it, expect, vi } from 'vitest'
import { screen } from '@testing-library/react'
import { Routes, Route } from 'react-router-dom'
import { renderWithProviders } from '../../../test/renderWithProviders'

// Capture the params DecisionTrace is bound with.
const traceProps = vi.fn()
vi.mock('../../../components/decisions/DecisionTrace', () => ({
  DecisionTrace: (props: { sessionId: string; requestId?: string }) => {
    traceProps(props)
    return <div data-testid="trace">trace {props.sessionId}/{props.requestId}</div>
  },
}))

import { DecisionDetailPage } from '../DecisionDetailPage'

describe('DecisionDetailPage (M-G3.4)', () => {
  it('binds the trace to BOTH route params (composite PK)', () => {
    renderWithProviders(
      <Routes>
        <Route path="/decisions/:sessionId/:requestId" element={<DecisionDetailPage />} />
      </Routes>,
      { routerEntries: ['/decisions/sess1/req9'] },
    )
    expect(traceProps).toHaveBeenCalledWith({ sessionId: 'sess1', requestId: 'req9' })
    expect(screen.getByTestId('trace')).toHaveTextContent('sess1/req9')
  })
})
