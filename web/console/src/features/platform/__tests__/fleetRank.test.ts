import { describe, it, expect } from 'vitest'
import { rankByBlocks, rankByDenyRate, hasRankableMetrics, quotaHeadroom } from '../fleetRank'
import type { PlatformTenantRow } from '../../../types/api'

const row = (over: Partial<PlatformTenantRow>): PlatformTenantRow => ({
  tenant_id: over.tenant_id ?? 't',
  display_name: over.display_name ?? 'T',
  plan: 'enterprise',
  status: 'active',
  identity_mode: 'enforce',
  created_at: '2026-01-01',
  ...over,
})

describe('fleetRank (G4.4)', () => {
  it('rankByBlocks sorts descending', () => {
    const rows = [row({ tenant_id: 'a', blocks_24h: 5 }), row({ tenant_id: 'b', blocks_24h: 50 }), row({ tenant_id: 'c', blocks_24h: 20 })]
    expect(rankByBlocks(rows).map((r) => r.tenant_id)).toEqual(['b', 'c', 'a'])
  })

  it('rankByDenyRate sorts descending', () => {
    const rows = [row({ tenant_id: 'a', deny_rate: 0.1 }), row({ tenant_id: 'b', deny_rate: 0.9 })]
    expect(rankByDenyRate(rows).map((r) => r.tenant_id)).toEqual(['b', 'a'])
  })

  it('missing/NaN metric sorts LAST, never treated as 0', () => {
    const rows = [
      row({ tenant_id: 'known', blocks_24h: 3 }),
      row({ tenant_id: 'missing' }), // undefined
      row({ tenant_id: 'nan', blocks_24h: NaN }),
    ]
    const order = rankByBlocks(rows).map((r) => r.tenant_id)
    expect(order[0]).toBe('known')
    // both unknowns sink below the known non-zero value
    expect(order.slice(1).sort()).toEqual(['missing', 'nan'])
  })

  it('hasRankableMetrics false when no row has a metric', () => {
    expect(hasRankableMetrics([row({}), row({})])).toBe(false)
    expect(hasRankableMetrics([row({ blocks_24h: 1 })])).toBe(true)
  })

  it('quotaHeadroom returns unknown when quota missing', () => {
    expect(quotaHeadroom({ decisions_24h: 100 }, undefined).known).toBe(false)
    expect(quotaHeadroom({ decisions_24h: 100 }, { other: 5 }).known).toBe(false)
  })

  it('quotaHeadroom computes used percent from decisions vs quota', () => {
    const h = quotaHeadroom({ decisions_24h: 250 }, { monthly_validations: 1000 })
    expect(h.known).toBe(true)
    expect(h.usedPct).toBeCloseTo(25)
  })

  it('quotaHeadroom guards a non-numeric quota value', () => {
    expect(quotaHeadroom({ decisions_24h: 100 }, { monthly_validations: 'lots' }).known).toBe(false)
  })
})
