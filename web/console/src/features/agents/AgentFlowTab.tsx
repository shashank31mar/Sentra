import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { IconFlame, IconRoute } from '@tabler/icons-react'
import { Card } from '../../components/ui/Card'
import { StatusDot } from '../../components/ui/StatusDot'
import { EmptyState, ErrorState, LoadingState } from '../../components/ui/states'
import { FlowSankey } from '../../components/charts/FlowSankey'
import { useDecisions } from '../../lib/query/useDecisions'
import { useAgentTools } from '../../lib/query/useAgents'
import { buildAgentFlow, computeHeatPath } from '../../lib/flowGraph'
import { policyDetailPath } from '../../app/routes'
import type { AgentDetail } from '../../types/api'

export function AgentFlowTab({ agent }: { agent: AgentDetail }) {
  const navigate = useNavigate()
  const query = useDecisions({ agent_id: agent.agent_id, limit: 200 })
  const tools = useAgentTools(agent.agent_id)

  // Filter client-side too: the live API honors `agent_id`, but mocks/proxies
  // may return the full feed — never attribute another agent's flow here.
  const items = useMemo(
    () => (query.data?.pages.flatMap((p) => p.items) ?? []).filter((d) => d.agent_id === agent.agent_id),
    [query.data, agent.agent_id],
  )
  const graph = useMemo(() => buildAgentFlow(items, agent.agent_id, agent.name), [items, agent.agent_id, agent.name])
  const heat = useMemo(() => computeHeatPath(graph), [graph])
  // agent-policy-management T47: scalar binding (0-or-1), not the vestigial Set.
  const policyIds = agent.active_policy_id ? [agent.active_policy_id] : []
  const toolColCount = graph.nodes.filter((n) => n.column === 1).length

  return (
    <div className="grid gap-5 grid-cols-1 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <div
          className="flex items-center justify-between px-6 py-4 flex-wrap gap-3"
          style={{ borderBottom: '1px solid var(--color-line)' }}
        >
          <span className="inline-flex items-center gap-2 text-sm font-medium uppercase tracking-[0.2em] text-secondary">
            <IconRoute size={16} className="text-cyan" /> Tool Flow
          </span>
          <div className="flex items-center gap-4">
            <span className="inline-flex items-center gap-1.5 text-[11px] font-mono text-muted">
              <span className="h-2.5 w-2.5 rounded-sm bg-cyan" /> Allowed
            </span>
            <span className="inline-flex items-center gap-1.5 text-[11px] font-mono text-muted">
              <span className="h-2.5 w-2.5 rounded-sm bg-pink" /> Blocked
            </span>
          </div>
        </div>

        {query.isLoading ? (
          <LoadingState />
        ) : query.isError ? (
          <ErrorState error={query.error} onRetry={() => query.refetch()} />
        ) : graph.links.length === 0 ? (
          <EmptyState label="No runtime activity recorded for this agent yet" />
        ) : (
          <div className="p-4 sm:p-6">
            {heat && (
              <div
                className="mb-4 inline-flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-mono text-amber"
                style={{ background: 'rgba(255,176,32,0.08)', border: '1px solid rgba(255,176,32,0.2)' }}
              >
                <IconFlame size={14} /> Most used · {heat.labels.join(' \u2192 ')} · {heat.value}
              </div>
            )}
            <FlowSankey graph={graph} heatLinkIds={heat?.linkIds} height={Math.max(260, toolColCount * 56)} />
          </div>
        )}
      </Card>

      <div className="flex flex-col gap-5">
        <Card className="p-5">
          <span className="text-sm font-medium uppercase tracking-[0.2em] text-secondary">Policy-Allowed Tools</span>
          <div className="mt-4 flex flex-col gap-2">
            {tools.isLoading ? (
              <LoadingState label="Loading tools…" />
            ) : (tools.data?.tools ?? []).length === 0 ? (
              <span className="text-sm text-muted font-mono">No tools resolved</span>
            ) : (
              (tools.data?.tools ?? []).map((t) => (
                <div
                  key={t.name}
                  className="flex items-center justify-between px-3 h-9 rounded-lg bg-surface"
                  style={{ border: '1px solid var(--color-line)' }}
                >
                  <span className="font-mono text-xs text-secondary">{t.name}</span>
                  <span
                    className="inline-flex items-center gap-1.5 text-[10px] font-mono uppercase"
                    style={{ color: t.allowed ? '#22E58B' : '#FF0080' }}
                  >
                    <StatusDot color={t.allowed ? '#22E58B' : '#FF0080'} /> {t.allowed ? 'Allow' : 'Forbid'}
                  </span>
                </div>
              ))
            )}
          </div>
        </Card>

        <Card className="p-5">
          <span className="text-sm font-medium uppercase tracking-[0.2em] text-secondary">Governing Policies</span>
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
                  className="flex items-center gap-2 px-3 h-10 rounded-lg bg-surface text-left hover:bg-cyan/10 transition-colors"
                  style={{ border: '1px solid var(--color-line)' }}
                >
                  <StatusDot color="#22E58B" />
                  <span className="font-mono text-sm text-secondary">{pid}</span>
                </button>
              ))
            )}
          </div>
        </Card>
      </div>
    </div>
  )
}
