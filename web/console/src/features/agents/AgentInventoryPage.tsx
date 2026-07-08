import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { Table, TBody, Td, Th, THead, Tr } from '../../components/ui/Table'
import { CloudBadge } from '../../components/ui/badges'
import { StatusDot } from '../../components/ui/StatusDot'
import { EmptyState, ErrorState, LoadingState } from '../../components/ui/states'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { useToast } from '../../components/ui/Toast'
import { useAgents, useDetachPolicy } from '../../lib/query/useAgents'
import { useCan } from '../../lib/query/useMe'
import { AttachPolicyModal } from './AttachPolicyModal'
import { agentDetailPath, policyDetailPath, policyEditPath } from '../../app/routes'
import { formatNumber, formatRelativeTime } from '../../lib/format'
import type { AgentListItem } from '../../types/api'
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
  const { success, error } = useToast()
  // G2.5: attach/detach are editor writes (server POST/DELETE /agents/{id}/policies).
  // Row navigation + the policy chip (navigation) stay ungated; only mutations hide.
  const can = useCan()
  const canWrite = can('agents.write')

  // Which agent's attach modal is open, and which agent is pending a detach.
  const [attachFor, setAttachFor] = useState<AgentListItem | null>(null)
  const [detachFor, setDetachFor] = useState<AgentListItem | null>(null)
  const detach = useDetachPolicy(detachFor?.agent_id ?? '')

  const confirmDetach = () => {
    if (!detachFor?.active_policy_id) return
    detach.mutate(detachFor.active_policy_id, {
      onSuccess: () => {
        success(`Policy detached from ${detachFor.name}. Its tool calls are now blocked until a policy is attached.`)
        setDetachFor(null)
      },
      onError: () => error('Could not detach the policy. Please try again.'),
    })
  }

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
              <Th>Policy</Th>
              <Th className="text-right">Trust</Th>
              <Th className="text-right">Requests</Th>
              <Th className="text-right">Denied</Th>
              <Th className="text-right">Sessions</Th>
              <Th className="text-right">Last seen</Th>
              <Th className="text-right">Actions</Th>
            </THead>
            <TBody>
              {agents.map((a) => {
                const activePolicyId = a.active_policy_id ?? null
                return (
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
                    <Td>
                      {activePolicyId ? (
                        <button
                          type="button"
                          title={`View policy ${activePolicyId}`}
                          onClick={(e) => {
                            e.stopPropagation()
                            navigate(policyDetailPath(activePolicyId))
                          }}
                          className="max-w-[180px] truncate px-2 py-0.5 rounded-md text-[11px] font-mono text-cyan bg-cyan/10 border border-cyan/20 hover:bg-cyan/20 transition-colors"
                        >
                          {activePolicyId}
                        </button>
                      ) : (
                        <span className="text-xs font-mono text-muted">unbound</span>
                      )}
                    </Td>
                    <Td className="text-right font-mono" style={{ color: (a.trust_score_avg ?? 100) < 60 ? '#FF0080' : '#8DA2AE' }}>
                      {a.trust_score_avg ?? '—'}
                    </Td>
                    <Td className="text-right font-mono text-secondary">{formatNumber(a.requests_total, true)}</Td>
                    <Td className="text-right font-mono text-pink">{formatNumber(a.requests_denied)}</Td>
                    <Td className="text-right font-mono text-secondary">{a.active_sessions}</Td>
                    <Td className="text-right font-mono text-muted">{formatRelativeTime(a.last_seen)}</Td>
                    <Td className="text-right">
                      {/* G2.5: attach/detach mutating controls gated on agents.write;
                          not-rendered (dash) for viewers. */}
                      {canWrite ? (
                        <div className="inline-flex items-center gap-1.5 justify-end">
                          {activePolicyId ? (
                            <>
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  navigate(policyEditPath(activePolicyId))
                                }}
                                className="px-2 py-1 rounded-lg text-[11px] font-bold text-secondary bg-surface-2 hover:text-cyan transition-colors"
                                style={{ border: '1px solid var(--color-line)' }}
                              >
                                Update
                              </button>
                              <button
                                type="button"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  setDetachFor(a)
                                }}
                                className="px-2 py-1 rounded-lg text-[11px] font-bold text-pink bg-pink/10 border border-pink/20 hover:bg-pink/20 transition-colors"
                              >
                                Detach
                              </button>
                            </>
                          ) : (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation()
                                setAttachFor(a)
                              }}
                              className="px-2 py-1 rounded-lg text-[11px] font-bold text-cyan bg-cyan/10 border border-cyan/20 hover:bg-cyan/20 transition-colors"
                            >
                              Attach Policy
                            </button>
                          )}
                        </div>
                      ) : (
                        <span className="text-[11px] font-mono text-faint">—</span>
                      )}
                    </Td>
                  </Tr>
                )
              })}
            </TBody>
          </Table>
        )}
      </Card>

      {attachFor && (
        <AttachPolicyModal
          open
          agentId={attachFor.agent_id}
          agentName={attachFor.name}
          onClose={() => setAttachFor(null)}
        />
      )}

      <ConfirmDialog
        open={Boolean(detachFor)}
        title="Detach policy"
        variant="danger"
        confirmLabel="Detach"
        busy={detach.isPending}
        onCancel={() => setDetachFor(null)}
        onConfirm={confirmDetach}
        message={
          <>
            Detach <span className="font-mono text-ink">{detachFor?.active_policy_id}</span> from{' '}
            <span className="font-mono text-ink">{detachFor?.name}</span>?{' '}
            <strong className="text-pink">This agent's tool calls will all be blocked (fail-secure) until a policy is attached.</strong>{' '}
            Other agents using this policy are unaffected. Re-attach from this row at any time to restore governance.
          </>
        }
      />
    </div>
  )
}
