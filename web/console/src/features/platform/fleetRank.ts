import type { PlatformTenantRow } from '../../types/api'

/**
 * Fleet ranking + quota-headroom helpers (G4.4) — pure, DERIVED client-side from
 * the rollup metric fields (no new endpoint). The metric fields are OPTIONAL
 * (PRE-G4-a); a missing/NaN metric MUST sort LAST ("unknown"), never coerce to 0
 * (which would falsely rank a no-data tenant as safest/quietest).
 */

/** A finite number, or `null` when absent/NaN/non-finite (→ sorts last). */
function metric(n: number | null | undefined): number | null {
  return typeof n === 'number' && Number.isFinite(n) ? n : null
}

/** Descending comparator that always sinks `null` (unknown) to the bottom. */
function byDesc(pick: (r: PlatformTenantRow) => number | null) {
  return (a: PlatformTenantRow, b: PlatformTenantRow) => {
    const av = pick(a)
    const bv = pick(b)
    if (av === null && bv === null) return 0
    if (av === null) return 1 // a unknown → after b
    if (bv === null) return -1 // b unknown → after a
    return bv - av
  }
}

export function rankByBlocks(rows: PlatformTenantRow[]): PlatformTenantRow[] {
  return [...rows].sort(byDesc((r) => metric(r.blocks_24h)))
}

export function rankByDenyRate(rows: PlatformTenantRow[]): PlatformTenantRow[] {
  return [...rows].sort(byDesc((r) => metric(r.deny_rate)))
}

/** Whether ANY row carries a usable ranking metric (else the ranked strip hides). */
export function hasRankableMetrics(rows: PlatformTenantRow[]): boolean {
  return rows.some((r) => metric(r.blocks_24h) !== null || metric(r.deny_rate) !== null)
}

/** Whether ANY loaded row carries the optional metric fields (PRE-G4-a) — drives
 *  the grid's degraded-6-col vs full-metric-column shape. */
export function metricsPresent(rows: PlatformTenantRow[]): boolean {
  return rows.some(
    (r) =>
      r.blocks_24h !== undefined ||
      r.deny_rate !== undefined ||
      r.trust !== undefined ||
      r.agents !== undefined ||
      r.quarantined !== undefined ||
      r.decisions_24h !== undefined,
  )
}

export interface QuotaHeadroom {
  known: boolean
  /** Percent of quota USED (0–100), only when both used + limit are known. */
  usedPct: number | null
  used: number | null
  limit: number | null
}

/**
 * Quota headroom from `decisions_24h` vs a narrow, guarded quota key
 * (`quota.monthly_validations`). Loose `quota:Record<string,unknown>` — narrow the
 * one key we read and treat anything non-numeric as unknown; never assume presence.
 */
export function quotaHeadroom(
  row: Pick<PlatformTenantRow, 'decisions_24h'>,
  quota: Record<string, unknown> | undefined | null,
): QuotaHeadroom {
  const used = metric(row.decisions_24h)
  const rawLimit = quota?.['monthly_validations']
  const limit = typeof rawLimit === 'number' && Number.isFinite(rawLimit) && rawLimit > 0 ? rawLimit : null
  if (used === null || limit === null) {
    return { known: false, usedPct: null, used, limit }
  }
  return { known: true, usedPct: Math.min(100, (used / limit) * 100), used, limit }
}
