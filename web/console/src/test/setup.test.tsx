import { describe, it, expect } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from './renderWithProviders'

// G2.0 smoke test: proves the harness is wired — jsdom mounts, the jest-dom
// matcher `toBeInTheDocument` resolves, and renderWithProviders supplies the
// QueryClient + Router without throwing. Every other WS-G Vitest depends on this.
describe('test harness (G2.0)', () => {
  it('mounts a component and resolves the jest-dom matcher', () => {
    renderWithProviders(<div data-testid="probe">ready</div>)
    expect(screen.getByTestId('probe')).toBeInTheDocument()
    expect(screen.getByTestId('probe')).toHaveTextContent('ready')
  })
})
