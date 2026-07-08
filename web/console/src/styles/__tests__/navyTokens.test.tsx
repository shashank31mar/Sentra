import { describe, it, expect } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '../../test/renderWithProviders'
import { trustColor } from '../../lib/format'
import { StatusDot } from '../../components/ui/StatusDot'
import { Button } from '../../components/ui/Button'

/**
 * F0.1 — navy retheme is a token-layer change (design-spec §1); shipped screens
 * re-skin through the same utility names. This smoke-mounts a couple of shipped
 * primitives to prove they still render after the remap, and pins the universal
 * `trustColor` thresholds (≥80 green / 50–79 amber / <50 pink / null faint).
 */
describe('F0.1 navy token remap', () => {
  it('trustColor maps the universal thresholds', () => {
    expect(trustColor(92)).toBe('#22E58B') // green
    expect(trustColor(80)).toBe('#22E58B') // boundary → green
    expect(trustColor(79)).toBe('#FFB020') // amber
    expect(trustColor(50)).toBe('#FFB020') // boundary → amber
    expect(trustColor(49)).toBe('#FF3D71') // pink
    expect(trustColor(0)).toBe('#FF3D71') // pink
    expect(trustColor(null)).toBe('#4E607E') // unknown → faint, never red
    expect(trustColor(undefined)).toBe('#4E607E')
  })

  it('shipped primitives still render after the reskin', () => {
    renderWithProviders(
      <div>
        <StatusDot color={trustColor(90)} />
        <Button>Save</Button>
      </div>,
    )
    expect(screen.getByRole('button', { name: 'Save' })).toBeInTheDocument()
  })
})
