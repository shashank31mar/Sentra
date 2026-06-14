import { useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { IconCircleCheck, IconCircleX, IconRoute, IconLayoutList } from '@tabler/icons-react'
import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { CloudBadge } from '../../components/ui/badges'
import { StatusDot } from '../../components/ui/StatusDot'
import { ErrorState, LoadingState } from '../../components/ui/states'
import { Table, TBody, Td, Th, THead, Tr } from '../../components/ui/Table'
import { AgentFlowTab } from './AgentFlowTab'
import { useAgentDetail, useAgentTools } from '../../lib/query/useAgents'
import { policyDetailPath } from '../../app/routes'
import { formatNumber, formatRelativeTime } from '../../lib/format'

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <Card className="p-5">
      <div className="text-[10px] uppercase tracking-[0.2em] text-secondary">{label}</div>
      <div className="font-display text-2xl font-bold mt-3 tracking-tight" style={color ? { color } : undefined}>{value}</div>
    </Card>
  )
}

const TABS = [
  { id: 'overview', label: 'Overview', icon: IconLayoutList },
  { id: 'flow', label: 'Flow', icon: IconRoute },
] as const
type TabId = (typeof TABS)[number]['id']

export function AgentDetailPage() {
  const { agentId = '' } = useParams()
  const navigate = useNavigate()
  const [tab, setTab] = useState<TabId>('overview')
  const detail = useAgentDetail(agentId)
  const tools = useAgentTools(agentId)

  if (detail.isLoading) return <div className="p-8"><Card className="p-6"><LoadingState /></Card></div>
  if (detail.isError || !detail.data)
    return <div className="p-8"><Card className="p-6"><ErrorState error={detail.error} onRetry={() => detail.refetch()} /></Card></div>

  const a = detail.data
  // agent-policy-management T47: single scalar binding (active_policy_id), not
  // the vestigial String-Set. 0-or-1 policy.
  const policyIds = a.active_policy_id ? [a.active_policy_id] : []

  return (
    <div className="p-4 sm:p-6 lg:p-8">
      <PageHeader
        title={a.name}
        subtitle={`${a.framework ?? 'Unknown framework'} · ${a.region ?? 'unknown region'}`}
        actions={<CloudBadge provider={a.cloud_provider} />}
      />

      <div className="grid grid-cols-2 md:grid-cols-4 gap-5 mb-6">
        <Stat label="Trust Score" value={a.trust_score_avg === null ? '—' : String(a.trust_score_avg)} color={(a.trust_score_avg ?? 100) < 60 ? '#FF0080' : '#0FFFFF'} />
        <Stat label="Total Requests" value={formatNumber(a.requests_total, true)} />
        <Stat label="Denied" value={formatNumber(a.requests_denied)} color="#FF0080" />
        <Stat label="Active Sessions" value={String(a.active_sessions)} />
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-1 mb-5" style={{ borderBottom: '1px solid var(--color-line)' }}>
        {TABS.map((t) => {
          const Icon = t.icon
          const active = tab === t.id
          return (
            <button
              key={t.id}
              type="button"
              onClick={() => setTab(t.id)}
              className="relative inline-flex items-center gap-2 px-4 h-10 text-sm font-medium cursor-pointer transition-colors"
              style={{ color: active ? '#0FFFFF' : '#8DA2AE' }}
            >
              <Icon size={16} /> {t.label}
              {active && (
                <span
                  className="absolute left-0 -bottom-px h-0.5 w-full rounded-full"
                  style={{ background: '#0FFFFF', boxShadow: '0 0 10px #0FFFFF' }}
                />
              )}
            </button>
          )
        })}
      </div>

      {tab === 'flow' ? (
        <AgentFlowTab agent={a} />
      ) : (
        <div className="grid gap-5 grid-cols-1 lg:grid-cols-2">
          {/* Tools */}
          <Card>
            <div className="px-6 py-4" style={{ borderBottom: '1px solid var(--color-line)' }}>
              <span className="text-sm font-medium uppercase tracking-[0.2em] text-secondary">Allowed Tools</span>
            </div>
            {tools.isLoading ? (
              <LoadingState />
            ) : (
              <Table>
                <THead>
                  <Th>Tool</Th>
                  <Th>Operation</Th>
                  <Th className="text-right">Allowed</Th>
                </THead>
                <TBody>
                  {(tools.data?.tools ?? []).map((t) => (
                    <Tr key={t.name}>
                      <Td className="font-mono text-secondary">{t.name}</Td>
                      <Td className="font-mono text-xs text-muted">{t.operation_type}</Td>
                      <Td className="text-right">
                        {t.allowed ? <IconCircleCheck size={18} className="inline text-green" /> : <IconCircleX size={18} className="inline text-pink" />}
                      </Td>
                    </Tr>
                  ))}
                </TBody>
              </Table>
            )}
          </Card>

          {/* Attached policies + meta */}
          <Card className="p-6">
            <span className="text-sm font-medium uppercase tracking-[0.2em] text-secondary">Attached Policies</span>
            <div className="mt-4 flex flex-col gap-2">
              {policyIds.length === 0 ? (
                <span className="text-sm text-muted font-mono">None attached</span>
              ) : (
                policyIds.map((pid) => (
                  <button
                    key={pid}
                    type="button"
                    title={`View policy ${pid}`}
                    onClick={() => navigate(policyDetailPath(pid))}
                    className="flex items-center gap-2 px-3 h-10 rounded-lg bg-surface text-left hover:bg-cyan/10 hover:border-cyan/30 transition-colors"
                    style={{ border: '1px solid var(--color-line)' }}
                  >
                    <StatusDot color="#22E58B" />
                    <span className="font-mono text-sm text-secondary">{pid}</span>
                  </button>
                ))
              )}
            </div>
            <div className="mt-6 text-xs font-mono text-muted">Last seen {formatRelativeTime(a.last_seen)}</div>
          </Card>
        </div>
      )}
    </div>
  )
}
