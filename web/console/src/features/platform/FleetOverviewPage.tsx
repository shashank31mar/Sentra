import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { EmptyState, ErrorState, LoadingState } from '../../components/ui/states'
import { useFleetTenants } from '../../lib/query/usePlatform'
import { TenantGrid } from './TenantGrid'
import { rankByBlocks, rankByDenyRate, hasRankableMetrics, metricsPresent } from './fleetRank'
import { formatNumber } from '../../lib/format'
import type { PlatformTenantRow } from '../../types/api'

function RankStrip({ title, rows, value }: { title: string; rows: PlatformTenantRow[]; value: (r: PlatformTenantRow) => number | null }) {
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
    </Card>
  )
}

/**
 * Fleet Overview / Tenant Grid page (G4.3–G4.4). Binds `useFleetTenants` (server
 * auto-fleet, no client tenant scoping). Ranked strips (Top by blocks / by DENY
 * rate) show only once rollup metrics are present (PRE-G4-a) — never rank on
 * `undefined`. The grid ships the 6-col shape first and lights up metric columns
 * when they arrive; row-virtualization kicks in only when the response carries a
 * `cursor` (PRE-G4-b). Read-only — no mutation control anywhere.
 */
export function FleetOverviewPage() {
  const query = useFleetTenants()
  const rows = query.data?.tenants ?? []
  const serverPaged = Boolean(query.data?.cursor)
  const showRanks = hasRankableMetrics(rows)

  return (
    <div className="p-4 sm:p-6 lg:p-8">
      <PageHeader
        title="Fleet Overview"
        subtitle="All tenants · cross-tenant aggregate (read-only, server-audited)."
      />

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
              <RankStrip title="Top tenants by blocks (24h)" rows={rankByBlocks(rows)} value={(r) => r.blocks_24h ?? null} />
              <RankStrip title="Top tenants by DENY rate" rows={rankByDenyRate(rows)} value={(r) => r.deny_rate ?? null} />
            </div>
          ) : (
            <Card className="px-5 py-3 mb-5 text-[11px] font-mono text-muted">
              Ranking available once the fleet metrics rollup ships.
            </Card>
          )}

          <Card>
            <div
              className="flex items-center justify-between px-6 py-4"
              style={{ borderBottom: '1px solid var(--color-line)' }}
            >
              <span className="text-sm font-medium uppercase tracking-[0.2em] text-secondary">Tenants</span>
              <span className="text-xs font-mono text-muted">
                {query.data?.count ?? rows.length} total
                {!serverPaged && ' · showing all (server paging pending)'}
                {!metricsPresent(rows) && ' · metrics pending'}
              </span>
            </div>
            <TenantGrid rows={rows} virtualized={serverPaged} />
          </Card>
        </>
      )}
    </div>
  )
}
