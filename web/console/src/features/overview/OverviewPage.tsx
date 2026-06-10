import { useMemo, useState } from 'react'
import { IconRefresh } from '@tabler/icons-react'
import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { SegmentedControl } from '../../components/ui/SegmentedControl'
import { ErrorState, LoadingState } from '../../components/ui/states'
import { AllowedVsBlockedChart } from '../../components/charts/AllowedVsBlockedChart'
import {
  useDecisionsTimeseries,
  useOverview,
  usePlatformDistribution,
} from '../../lib/query/useMetrics'
import { useDecisions } from '../../lib/query/useDecisions'
import type { MetricsRange } from '../../types/enums'
import { KpiGrid } from './KpiGrid'
import { LiveActivity } from './LiveActivity'
import { PlatformDistribution } from './PlatformDistribution'

const RANGES = [
  { value: '1h', label: '1H' },
  { value: '24h', label: '24H' },
  { value: '7d', label: '7D' },
  { value: '30d', label: '30D' },
] as const

export function OverviewPage() {
  const [range, setRange] = useState<MetricsRange>('24h')
  // 30d must use 1d buckets (LLD §11.2 rejects 30d+1h).
  const bucket = range === '30d' ? '1d' : '1h'

  const overview = useOverview(range)
  const distribution = usePlatformDistribution()
  const timeseries = useDecisionsTimeseries(range, bucket)
  const feed = useDecisions({ limit: 5 })

  const feedItems = useMemo(
    () => feed.data?.pages.flatMap((p) => p.items).slice(0, 6) ?? [],
    [feed.data],
  )

  return (
    <div className="p-4 sm:p-6 lg:p-8">
      <PageHeader
        title="Security Overview"
        subtitle="Runtime governance across all connected agent fleets."
        actions={
          <>
            <span className="text-xs font-mono flex items-center gap-1.5 text-muted">
              <IconRefresh size={14} /> {overview.isFetching ? 'Syncing…' : 'Live'}
            </span>
            <SegmentedControl options={RANGES} value={range} onChange={setRange} />
          </>
        }
      />

      {/* KPI grid */}
      {overview.isLoading ? (
        <Card className="p-6 mb-5"><LoadingState label="Loading metrics…" /></Card>
      ) : overview.isError ? (
        <Card className="p-6 mb-5"><ErrorState error={overview.error} onRetry={() => overview.refetch()} /></Card>
      ) : overview.data ? (
        <KpiGrid data={overview.data} />
      ) : null}

      {/* Platform distribution */}
      {distribution.isLoading ? (
        <Card className="p-6 mb-5"><LoadingState label="Loading distribution…" /></Card>
      ) : distribution.isError ? (
        <Card className="p-6 mb-5"><ErrorState error={distribution.error} onRetry={() => distribution.refetch()} /></Card>
      ) : distribution.data ? (
        <PlatformDistribution data={distribution.data} />
      ) : null}

      {/* Chart + live activity */}
      <div className="grid gap-5 mb-8 grid-cols-1 lg:grid-cols-[62%_1fr]">
        <Card className="p-7 flex flex-col">
          <div className="flex items-center justify-between mb-8">
            <div>
              <h3 className="font-display text-lg font-bold tracking-tight">Allowed vs Blocked</h3>
              <p className="text-xs mt-1 text-muted">Real-time request decision telemetry · {range}</p>
            </div>
            <div className="flex items-center gap-6 text-xs font-mono">
              <span className="flex items-center gap-2.5 text-secondary"><span className="w-3.5 h-3.5 rounded-sm" style={{ background: '#0FFFFF' }} /> Allowed</span>
              <span className="flex items-center gap-2.5 text-secondary"><span className="w-3.5 h-3.5 rounded-sm" style={{ background: '#FF0080' }} /> Blocked</span>
            </div>
          </div>
          <div className="flex-1" style={{ height: 280 }}>
            {timeseries.isLoading ? (
              <LoadingState label="Loading telemetry…" />
            ) : timeseries.isError ? (
              <ErrorState error={timeseries.error} onRetry={() => timeseries.refetch()} />
            ) : timeseries.data ? (
              <AllowedVsBlockedChart series={timeseries.data.series} />
            ) : null}
          </div>
        </Card>

        <LiveActivity
          items={feedItems}
          isLoading={feed.isLoading}
          isFetching={feed.isFetching}
          onRefresh={() => feed.refetch()}
        />
      </div>
    </div>
  )
}
