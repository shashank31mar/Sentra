import { useState } from 'react'
import { IconRadar2, IconDownload } from '@tabler/icons-react'
import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { Button } from '../../components/ui/Button'
import { Table, TBody, Td, Th, THead, Tr } from '../../components/ui/Table'
import { CloudBadge, DiscoveryStatusBadge, RiskBadge } from '../../components/ui/badges'
import { StatusDot } from '../../components/ui/StatusDot'
import { EmptyState, ErrorState, LoadingState } from '../../components/ui/states'
import {
  useDiscoveredAgents,
  useDiscoveryPlatforms,
  useDiscoverySummary,
  useImportAgents,
} from '../../lib/query/useDiscovery'
import { formatNumber, formatRelativeTime } from '../../lib/format'

function KpiCard({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <Card className="p-5">
      <div className="text-[10px] uppercase tracking-[0.2em] text-secondary">{label}</div>
      <div className="font-display text-3xl font-bold mt-3 tracking-tight" style={accent ? { color: accent } : undefined}>{value}</div>
    </Card>
  )
}

export function DiscoveryPage() {
  const summary = useDiscoverySummary()
  const platforms = useDiscoveryPlatforms()
  const agentsQuery = useDiscoveredAgents()
  const importAgents = useImportAgents()
  const [selected, setSelected] = useState<Set<string>>(new Set())

  const agents = agentsQuery.data?.pages.flatMap((p) => p.items) ?? []

  const toggle = (id: string) =>
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })

  const doImport = () => {
    if (selected.size === 0) return
    importAgents.mutate(
      { agentIds: [...selected] },
      { onSuccess: () => setSelected(new Set()) },
    )
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8">
      <PageHeader
        title="Discovery"
        subtitle="Agents detected from governing policy artifacts."
        actions={
          <>
            {/* POST /discovery/scan is descoped in P0 — disabled with tooltip */}
            <Button variant="ghost" disabled title="Dynamic scan ships in a later release">
              <IconRadar2 size={14} /> Trigger Scan
            </Button>
            <Button onClick={doImport} disabled={selected.size === 0 || importAgents.isPending}>
              <IconDownload size={14} /> Import {selected.size > 0 ? `(${selected.size})` : ''}
            </Button>
          </>
        }
      />

      {/* Summary KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-5 mb-5">
        {summary.isLoading || !summary.data ? (
          <Card className="p-5 col-span-2 md:col-span-4"><LoadingState label="Loading summary…" /></Card>
        ) : (
          <>
            <KpiCard label="Detected" value={formatNumber(summary.data.detected)} />
            <KpiCard label="Unmanaged" value={formatNumber(summary.data.unmanaged)} accent="#FFB020" />
            <KpiCard label="New · 24h" value={formatNumber(summary.data.new_24h)} accent="#0FFFFF" />
            <KpiCard label="Providers" value={`${summary.data.providers_connected}/${summary.data.providers_total}`} accent="#22E58B" />
          </>
        )}
      </div>

      {/* Platform scan status */}
      {platforms.data && (
        <Card className="p-6 mb-5">
          <span className="text-sm font-medium uppercase tracking-[0.2em] text-secondary">Platform Scan Status</span>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 sm:gap-6 mt-4">
            {platforms.data.providers.map((p) => (
              <div key={p.cloud_provider} className="flex items-center justify-between px-4 h-12 rounded-xl bg-surface" style={{ border: '1px solid var(--color-line)' }}>
                <div className="flex items-center gap-3">
                  <CloudBadge provider={p.cloud_provider} />
                  <span className="font-mono text-sm text-secondary">{formatNumber(p.agents)} agents</span>
                </div>
                <span className="inline-flex items-center gap-2 text-xs font-mono capitalize" style={{ color: p.status === 'scanning' ? '#0FFFFF' : '#51636E' }}>
                  <StatusDot color={p.status === 'scanning' ? '#0FFFFF' : '#51636E'} pulse={p.status === 'scanning'} /> {p.status}
                </span>
              </div>
            ))}
          </div>
        </Card>
      )}

      {/* Detected agents */}
      <Card>
        <div className="flex items-center justify-between px-6 py-4" style={{ borderBottom: '1px solid var(--color-line)' }}>
          <span className="text-sm font-medium uppercase tracking-[0.2em] text-secondary">Detected Agents</span>
          <span className="text-xs font-mono text-muted">Risk is provisional (heuristic)</span>
        </div>
        {agentsQuery.isLoading ? (
          <LoadingState />
        ) : agentsQuery.isError ? (
          <ErrorState error={agentsQuery.error} onRetry={() => agentsQuery.refetch()} />
        ) : agents.length === 0 ? (
          <EmptyState label="No detected agents" />
        ) : (
          <Table>
            <THead>
              <Th className="w-10" />
              <Th>Name</Th>
              <Th>Cloud</Th>
              <Th>Framework</Th>
              <Th>Risk</Th>
              <Th>Status</Th>
              <Th className="text-right">First seen</Th>
            </THead>
            <TBody>
              {agents.map((d) => (
                <Tr key={d.id}>
                  <Td>
                    <input
                      type="checkbox"
                      className="accent-cyan w-4 h-4 cursor-pointer"
                      checked={selected.has(d.id)}
                      disabled={d.status === 'managed'}
                      onChange={() => toggle(d.id)}
                    />
                  </Td>
                  <Td className="font-display font-bold text-white">{d.name}</Td>
                  <Td><CloudBadge provider={d.cloud_provider} /></Td>
                  <Td className="font-mono text-xs text-secondary">{d.framework ?? '—'}</Td>
                  <Td><RiskBadge risk={d.risk} /></Td>
                  <Td><DiscoveryStatusBadge status={d.status} /></Td>
                  <Td className="text-right font-mono text-muted">{formatRelativeTime(d.first_seen)}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    </div>
  )
}
