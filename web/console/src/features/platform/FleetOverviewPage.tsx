import { useMemo, useState } from 'react'
import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { SegmentedControl } from '../../components/ui/SegmentedControl'
import { Button } from '../../components/ui/Button'
import { EmptyState, ErrorState, LoadingState } from '../../components/ui/states'
import { AllowedVsBlockedChart } from '../../components/charts/AllowedVsBlockedChart'
import { KpiGrid } from '../overview/KpiGrid'
import { useFleetTenants } from '../../lib/query/usePlatform'
import { useFleetOverview, useFleetDecisionsTimeseries } from '../../lib/query/useMetrics'
import { TenantGrid } from './TenantGrid'
import { rankByBlocks, rankByDenyRate, hasRankableMetrics, metricsPresent } from './fleetRank'
import { formatNumber } from '../../lib/format'
import type { PlatformTenantRow } from '../../types/api'

const FLEET_PAGE_SIZE = 50

const SORTS = [
  { value: 'blocks_24h', label: 'Blocks' },
  { value: 'trust', label: 'Trust' },
  { value: 'created_at', label: 'Newest' },
] as const

function RankStrip({ title, note, rows, value }: { title: string; note?: string; rows: PlatformTenantRow[]; value: (r: PlatformTenantRow) => number | null }) {
  const top = rows.slice(0, 5)
  return (
    <Card className="p-5">
      <div className="text-[10px] uppercase tracking-[0.18em] text-muted mb-3">{title}</div>
      <ol className="space-y-2">
        {top.map((r, i) => (
          <li key={r.tenant_id} className="flex items-center justify-between gap-3 text-xs">
            <span className="flex items-center gap-2 min-w-0">
              <span className="font-mono text-muted w-4">{i + 1}</span>
              <span className="font-display font-bold text-white truncate">{r.display_name}</span>
            </span>
            <span className="font-mono text-blue-lt">{formatNumber(value(r))}</span>
          </li>
        ))}
      </ol>
      {/* FX-1.5: honest scope caveat — the rank is page-local when the fleet is paged. */}
      {note && <div className="mt-3 text-[10px] font-mono text-muted">{note}</div>}
    </Card>
  )
}

/**
 * Fleet Overview / Tenant Grid page (G4.3–G4.5 / FX-1.5 / FX-3.4). Binds the fleet
 * KPI grid + allowed-vs-blocked chart (`useFleetOverview`/`useFleetDecisionsTimeseries`,
 * fleet-mode — no `X-Aegion-Tenant`) above the tenant grid — the §6.11 view-set (a)
 * fleet aggregate. Ranked strips show only once rollup metrics are present (PRE-G4-a).
 * FX-3.4: the grid sends `limit`/`cursor`/`sort` (backend paging in `tenancy_routes.py`)
 * and advances the cursor so the fleet is never silently truncated to page 1.
 * Read-only — no mutation control anywhere.
 */
export function FleetOverviewPage() {
  // FX-3.4: cursor-based pager. `cursorStack` holds the cursor that STARTED each
  // page so Prev can walk back; `cursor` is the current page's start (undefined = p1).
  const [cursorStack, setCursorStack] = useState<(string | undefined)[]>([undefined])
  const [sort, setSort] = useState<(typeof SORTS)[number]['value']>('blocks_24h')
  const cursor = cursorStack[cursorStack.length - 1]

  const fleet = useFleetOverview()
  const timeseries = useFleetDecisionsTimeseries()
  const query = useFleetTenants({ limit: FLEET_PAGE_SIZE, cursor, sort })

  const rows = query.data?.tenants ?? []
  const nextCursor = query.data?.cursor
  const serverPaged = Boolean(nextCursor) || cursorStack.length > 1
  const pageNum = cursorStack.length
  const showRanks = hasRankableMetrics(rows)
  // FX-1.5: rankBy* is computed over the loaded page only. When the fleet spans more
  // than one server page, the strip ranks THIS page, not the whole fleet — say so.
  const rankScopeNote = `Ranked within this page (${rows.length}) — the fleet spans multiple pages.`

  const timeseriesSeries = useMemo(() => timeseries.data?.series ?? [], [timeseries.data])

  const goNext = () => {
    if (nextCursor) setCursorStack((s) => [...s, nextCursor])
  }
  const goPrev = () => {
    setCursorStack((s) => (s.length > 1 ? s.slice(0, -1) : s))
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8">
      <PageHeader
        title="Fleet Overview"
        subtitle="All tenants · cross-tenant aggregate (read-only, server-audited)."
      />

      {/* FX-1.5: fleet KPI grid (§6.11 view-set a). */}
      {fleet.isLoading ? (
        <Card className="p-6 mb-5"><LoadingState label="Loading fleet metrics…" /></Card>
      ) : fleet.isError ? (
        <Card className="p-6 mb-5"><ErrorState error={fleet.error} onRetry={() => fleet.refetch()} /></Card>
      ) : fleet.data ? (
        <KpiGrid data={fleet.data} />
      ) : null}

      {/* FX-1.5: fleet allowed-vs-blocked chart. */}
      <Card className="p-7 flex flex-col mb-5">
        <div className="flex items-center justify-between mb-6">
          <h3 className="font-display text-lg font-bold tracking-tight">Allowed vs Blocked · fleet</h3>
          <div className="flex items-center gap-6 text-xs font-mono">
            <span className="flex items-center gap-2.5 text-secondary"><span className="w-3.5 h-3.5 rounded-sm" style={{ background: '#0FFFFF' }} /> Allowed</span>
            <span className="flex items-center gap-2.5 text-secondary"><span className="w-3.5 h-3.5 rounded-sm" style={{ background: '#FF0080' }} /> Blocked</span>
          </div>
        </div>
        <div className="flex-1" style={{ height: 260 }}>
          {timeseries.isLoading ? (
            <LoadingState label="Loading telemetry…" />
          ) : timeseries.isError ? (
            <ErrorState error={timeseries.error} onRetry={() => timeseries.refetch()} />
          ) : (
            <AllowedVsBlockedChart series={timeseriesSeries} />
          )}
        </div>
      </Card>

      {query.isLoading ? (
        <LoadingState label="Loading fleet…" />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => query.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState label="No tenants in the fleet." />
      ) : (
        <>
          {showRanks ? (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-5 mb-5">
              {/* FX-1.5: rankBy* only sees the loaded page. When the fleet is server-paged
                  (>1 page), the "top 5" is page-local, NOT fleet-wide — label + note say so
                  honestly rather than mislabeling a page rank as a cross-fleet rank. */}
              <RankStrip
                title={serverPaged ? `Top on page ${pageNum} by blocks (24h)` : 'Top tenants by blocks (24h)'}
                note={serverPaged ? rankScopeNote : undefined}
                rows={rankByBlocks(rows)}
                value={(r) => r.blocks_24h ?? null}
              />
              <RankStrip
                title={serverPaged ? `Top on page ${pageNum} by DENY rate` : 'Top tenants by DENY rate'}
                note={serverPaged ? rankScopeNote : undefined}
                rows={rankByDenyRate(rows)}
                value={(r) => r.deny_rate ?? null}
              />
            </div>
          ) : (
            <Card className="px-5 py-3 mb-5 text-[11px] font-mono text-muted">
              Ranking available once the fleet metrics rollup ships.
            </Card>
          )}

          <Card>
            <div
              className="flex flex-wrap items-center justify-between gap-3 px-6 py-4"
              style={{ borderBottom: '1px solid var(--color-line)' }}
            >
              <span className="text-sm font-medium uppercase tracking-[0.2em] text-secondary">Tenants</span>
              <div className="flex items-center gap-3">
                <SegmentedControl options={SORTS} value={sort} onChange={(v) => { setSort(v); setCursorStack([undefined]) }} />
                <span className="text-xs font-mono text-muted">
                  {query.data?.count ?? rows.length} total
                  {!metricsPresent(rows) && ' · metrics pending'}
                </span>
              </div>
            </div>
            <TenantGrid rows={rows} virtualized={serverPaged} />
            {/* FX-3.4: advance the cursor so the fleet isn't truncated to page 1. */}
            {(nextCursor || cursorStack.length > 1) && (
              <div className="flex items-center justify-between px-6 py-3" style={{ borderTop: '1px solid var(--color-line)' }}>
                <Button variant="ghost" disabled={cursorStack.length <= 1} onClick={goPrev}>
                  Previous
                </Button>
                <span className="text-[11px] font-mono text-muted">page {pageNum}</span>
                <Button variant="ghost" disabled={!nextCursor} onClick={goNext}>
                  Next
                </Button>
              </div>
            )}
          </Card>
        </>
      )}
    </div>
  )
}
