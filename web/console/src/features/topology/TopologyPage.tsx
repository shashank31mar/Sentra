import { useMemo, useState } from 'react'
import { IconFlame, IconSitemap } from '@tabler/icons-react'
import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { SegmentedControl } from '../../components/ui/SegmentedControl'
import { EmptyState, ErrorState, LoadingState } from '../../components/ui/states'
import { FlowSankey } from '../../components/charts/FlowSankey'
import { useDecisions } from '../../lib/query/useDecisions'
import { buildFleetFlow, computeHeatPath } from '../../lib/flowGraph'
import type { Decision } from '../../types/enums'

const VIEW = [
  { value: 'all', label: 'All' },
  { value: 'DENY', label: 'Blocked' },
  { value: 'ALLOW', label: 'Allowed' },
] as const

const TOPN = [
  { value: '5', label: 'Top 5' },
  { value: '10', label: 'Top 10' },
  { value: '20', label: 'Top 20' },
  { value: '999', label: 'All' },
] as const

const LEGEND = [
  { c: '#0FFFFF', l: 'Allowed' },
  { c: '#FF0080', l: 'Blocked' },
  { c: '#FFB020', l: 'Mixed' },
]

function Kpi({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <Card className="p-5 min-w-0">
      <div className="text-[10px] uppercase tracking-[0.2em] text-secondary">{label}</div>
      <div
        className="font-display text-2xl font-bold mt-2 tracking-tight truncate"
        style={accent ? { color: accent } : undefined}
        title={value}
      >
        {value}
      </div>
    </Card>
  )
}

export function TopologyPage() {
  const [view, setView] = useState<(typeof VIEW)[number]['value']>('all')
  const [topN, setTopN] = useState<(typeof TOPN)[number]['value']>('10')
  const query = useDecisions({ limit: 200 })

  const items = useMemo(() => query.data?.pages.flatMap((p) => p.items) ?? [], [query.data])
  const filtered = useMemo(
    () => (view === 'all' ? items : items.filter((d) => d.decision === (view as Decision))),
    [items, view],
  )
  const graph = useMemo(() => buildFleetFlow(filtered, Number(topN)), [filtered, topN])
  const heat = useMemo(() => computeHeatPath(graph), [graph])

  const agentCount = graph.nodes.filter((n) => n.column === 1).length
  const blocked = items.filter((d) => d.decision === 'DENY').length
  const blockedShare = items.length ? Math.round((blocked / items.length) * 100) : 0

  return (
    <div className="p-4 sm:p-6 lg:p-8">
      <PageHeader
        title="Topology"
        subtitle="Cross-fleet flow map — clouds to agents to tools, weighted by live traffic. The brightest ribbon is the hottest path."
        actions={
          <div className="flex items-center gap-3 flex-wrap">
            <SegmentedControl options={TOPN} value={topN} onChange={setTopN} />
            <SegmentedControl options={VIEW} value={view} onChange={setView} />
          </div>
        }
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-5 mb-5">
        <Kpi label="Flows Analyzed" value={String(items.length)} />
        <Kpi label="Agents Shown" value={String(agentCount)} accent="#0FFFFF" />
        <Kpi label="Blocked Share" value={`${blockedShare}%`} accent={blockedShare > 0 ? '#FF0080' : undefined} />
        <Kpi label="Hottest Path" value={heat ? heat.labels.join(' \u2192 ') : '\u2014'} accent="#FFB020" />
      </div>

      <Card>
        <div
          className="flex items-center justify-between px-6 py-4 flex-wrap gap-3"
          style={{ borderBottom: '1px solid var(--color-line)' }}
        >
          <span className="inline-flex items-center gap-2 text-sm font-medium uppercase tracking-[0.2em] text-secondary">
            <IconSitemap size={16} className="text-cyan" /> Flow Map
          </span>
          <div className="flex items-center gap-4">
            {LEGEND.map((i) => (
              <span key={i.l} className="inline-flex items-center gap-1.5 text-[11px] font-mono text-muted">
                <span className="h-2.5 w-2.5 rounded-sm" style={{ background: i.c }} /> {i.l}
              </span>
            ))}
          </div>
        </div>

        {query.isLoading ? (
          <LoadingState />
        ) : query.isError ? (
          <ErrorState error={query.error} onRetry={() => query.refetch()} />
        ) : graph.links.length === 0 ? (
          <EmptyState label="No runtime traffic to map for this filter" />
        ) : (
          <div className="p-4 sm:p-6">
            {heat && (
              <div
                className="mb-4 inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-mono text-amber"
                style={{ background: 'rgba(255,176,32,0.08)', border: '1px solid rgba(255,176,32,0.2)' }}
              >
                <IconFlame size={14} /> Heat path · {heat.labels.join(' \u2192 ')} · {heat.value} flows
              </div>
            )}
            <FlowSankey graph={graph} heatLinkIds={heat?.linkIds} height={Math.max(360, agentCount * 48)} />
          </div>
        )}
      </Card>
    </div>
  )
}
