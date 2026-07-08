import { useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { IconDownload, IconCloudComputing, IconCloudCheck } from '@tabler/icons-react'
import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { Button } from '../../components/ui/Button'
import { SegmentedControl } from '../../components/ui/SegmentedControl'
import { Table, TBody, Td, Th, THead, Tr } from '../../components/ui/Table'
import { CloudBadge, DiscoveryStatusBadge, RiskBadge } from '../../components/ui/badges'
import { StatusDot } from '../../components/ui/StatusDot'
import { EmptyState, ErrorState, LoadingState } from '../../components/ui/states'
import { useToast } from '../../components/ui/Toast'
import {
  useDiscoveredAgents,
  useDiscoveryPlatforms,
  useDiscoverySummary,
  useImportAgents,
} from '../../lib/query/useDiscovery'
import { useConnection } from '../../lib/query/useConnections'
import { useCan } from '../../lib/query/useMe'
import { ImportResultDrawer } from './ImportResultDrawer'
import { agentDetailPath, ROUTES } from '../../app/routes'
import { ApiException } from '../../lib/http'
import { formatNumber, formatRelativeTime } from '../../lib/format'
import type { EnforcementMode } from '../../types/enums'
import type { ImportResponse } from '../../types/api'

const ENFORCEMENT_OPTIONS: readonly { value: EnforcementMode; label: string }[] = [
  { value: 'monitor', label: 'Monitor' },
  { value: 'enforce', label: 'Enforce' },
]

function KpiCard({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <Card className="p-5">
      <div className="text-[10px] uppercase tracking-[0.2em] text-secondary">{label}</div>
      <div className="font-display text-3xl font-bold mt-3 tracking-tight" style={accent ? { color: accent } : undefined}>{value}</div>
    </Card>
  )
}

/**
 * Discovery review + import (feature.md §13). Detect unmanaged agents (from
 * governing policy artifacts, scoped to a connected account when arriving from
 * the Connect wizard via `?connection=`), pick an enforcement mode, and bring
 * the selected ones under governance — surfacing the per-agent import result.
 */
export function ImportAgentsPage() {
  const navigate = useNavigate()
  const { error: toastError, success } = useToast()
  const [params] = useSearchParams()
  const connectionId = params.get('connection') ?? undefined
  const connection = useConnection(connectionId)

  const summary = useDiscoverySummary()
  const platforms = useDiscoveryPlatforms()
  // Scope the review table to the connected account when arriving from the wizard.
  const agentsQuery = useDiscoveredAgents(connectionId ? { connection_id: connectionId } : {})
  const importAgents = useImportAgents()
  // G2.5: import is an editor mutation (server POST /discovery/import). The
  // discovery review table stays visible (read); only the import action hides.
  const can = useCan()
  const canImport = can('agents.write')

  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [enforcementMode, setEnforcementMode] = useState<EnforcementMode>('monitor')
  const [importResult, setImportResult] = useState<ImportResponse | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)

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
      { agentIds: [...selected], enforcementMode },
      {
        onSuccess: (res) => {
          setSelected(new Set())
          setImportResult(res)
          setDrawerOpen(true)
          success(`Imported ${res.imported} agent${res.imported === 1 ? '' : 's'}`)
        },
        onError: (err) => toastError(err instanceof ApiException ? err.message : 'Import failed.'),
      },
    )
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8">
      <PageHeader
        title="Import Agents"
        subtitle="Connect discovers your agents; Import brings the selected ones under management against their governing policy."
        actions={
          <>
            {canImport && (
              <div
                className="flex items-center gap-2"
                title="Enforcement posture recorded on import. Monitor = observe-only; Enforce blocks. Runtime enforcement of this posture activates with governance (P1) — imports observe in Monitor today."
              >
                <span className="text-[11px] font-mono text-muted hidden sm:inline">Mode</span>
                <SegmentedControl options={ENFORCEMENT_OPTIONS} value={enforcementMode} onChange={setEnforcementMode} />
              </div>
            )}
            <Button variant="ghost" onClick={() => navigate(ROUTES.connect)}>
              <IconCloudComputing size={14} /> Connect account
            </Button>
            {canImport && (
              <Button onClick={doImport} disabled={selected.size === 0 || importAgents.isPending}>
                <IconDownload size={14} /> Import {selected.size > 0 ? `(${selected.size})` : ''}
              </Button>
            )}
          </>
        }
      />

      {/* Connection context (arriving from the Connect wizard) */}
      {connection.data && (
        <Card className="px-5 py-3 mb-5 flex items-center justify-between gap-3 flex-wrap">
          <span className="flex items-center gap-2.5 text-sm text-secondary">
            <IconCloudCheck size={18} className="text-green" />
            <CloudBadge provider={connection.data.cloud_provider} />
            <span className="font-mono text-ink">{connection.data.account_ref ?? connection.data.id}</span>
          </span>
          <span className="text-xs font-mono text-muted">
            {connection.data.agents_visible != null ? `${formatNumber(connection.data.agents_visible)} agents visible · ` : ''}
            last scan {formatRelativeTime(connection.data.last_scan)}
          </span>
        </Card>
      )}

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
                <Tr
                  key={d.id}
                  // Imported/Managed agents have a registry record → open detail.
                  // not_imported agents have none (Agent Detail would 404), so the
                  // row toggles selection instead (feature §8.1).
                  onClick={() =>
                    d.agent_id ? navigate(agentDetailPath(d.agent_id)) : toggle(d.id)
                  }
                >
                  <Td>
                    <input
                      type="checkbox"
                      aria-label={`Select ${d.name} for import`}
                      className="accent-cyan w-4 h-4 cursor-pointer disabled:cursor-not-allowed"
                      checked={selected.has(d.id)}
                      // Only not_imported agents can be imported.
                      disabled={d.status !== 'not_imported'}
                      onClick={(e) => e.stopPropagation()}
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

      <ImportResultDrawer
        open={drawerOpen}
        onClose={() => setDrawerOpen(false)}
        result={importResult}
        enforcementMode={enforcementMode}
      />
    </div>
  )
}
