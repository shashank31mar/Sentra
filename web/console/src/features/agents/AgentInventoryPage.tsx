import { useNavigate } from 'react-router-dom'
import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { Table, TBody, Td, Th, THead, Tr } from '../../components/ui/Table'
import { CloudBadge } from '../../components/ui/badges'
import { StatusDot } from '../../components/ui/StatusDot'
import { EmptyState, ErrorState, LoadingState } from '../../components/ui/states'
import { useAgents } from '../../lib/query/useAgents'
import { agentDetailPath } from '../../app/routes'
import { formatNumber, formatRelativeTime } from '../../lib/format'
import type { AgentStatus } from '../../types/enums'

const STATUS_COLOR: Partial<Record<AgentStatus, string>> = {
  active: '#22E58B',
  idle: '#8DA2AE',
  quarantined: '#FF0080',
  inactive: '#51636E',
}

export function AgentInventoryPage() {
  const navigate = useNavigate()
  const query = useAgents()
  const agents = query.data?.agents ?? []

  return (
    <div className="p-4 sm:p-6 lg:p-8">
      <PageHeader title="Agent Inventory" subtitle="All managed agents across connected clouds." />

      <Card>
        <div className="flex items-center justify-between px-6 py-4" style={{ borderBottom: '1px solid var(--color-line)' }}>
          <span className="text-sm font-medium uppercase tracking-[0.2em] text-secondary">Agents</span>
          <span className="text-xs font-mono text-muted">{query.data?.total ?? 0} managed</span>
        </div>

        {query.isLoading ? (
          <LoadingState />
        ) : query.isError ? (
          <ErrorState error={query.error} onRetry={() => query.refetch()} />
        ) : agents.length === 0 ? (
          <EmptyState label="No agents yet" />
        ) : (
          <Table>
            <THead>
              <Th>Agent</Th>
              <Th>Cloud</Th>
              <Th>Status</Th>
              <Th className="text-right">Trust</Th>
              <Th className="text-right">Requests</Th>
              <Th className="text-right">Denied</Th>
              <Th className="text-right">Sessions</Th>
              <Th className="text-right">Last seen</Th>
            </THead>
            <TBody>
              {agents.map((a) => (
                <Tr key={a.agent_id} onClick={() => navigate(agentDetailPath(a.agent_id))}>
                  <Td>
                    <div className="font-display font-bold tracking-tight text-white">{a.name}</div>
                    <div className="text-[11px] font-mono text-muted uppercase">{a.platform}</div>
                  </Td>
                  <Td><CloudBadge provider={a.cloud_provider} /></Td>
                  <Td>
                    <span className="inline-flex items-center gap-2 text-xs font-mono capitalize text-secondary">
                      <StatusDot color={STATUS_COLOR[a.status] ?? '#8DA2AE'} /> {a.status ?? '—'}
                    </span>
                  </Td>
                  <Td className="text-right font-mono" style={{ color: (a.trust_score_avg ?? 100) < 60 ? '#FF0080' : '#8DA2AE' }}>
                    {a.trust_score_avg ?? '—'}
                  </Td>
                  <Td className="text-right font-mono text-secondary">{formatNumber(a.requests_total, true)}</Td>
                  <Td className="text-right font-mono text-pink">{formatNumber(a.requests_denied)}</Td>
                  <Td className="text-right font-mono text-secondary">{a.active_sessions}</Td>
                  <Td className="text-right font-mono text-muted">{formatRelativeTime(a.last_seen)}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    </div>
  )
}
