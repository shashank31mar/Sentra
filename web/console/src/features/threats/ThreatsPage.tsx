import { Fragment, useMemo, useState } from 'react'
import { IconChevronDown, IconChevronRight, IconLockX, IconShieldLock } from '@tabler/icons-react'
import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { SegmentedControl } from '../../components/ui/SegmentedControl'
import { Button } from '../../components/ui/Button'
import { StatusDot } from '../../components/ui/StatusDot'
import { Table, TBody, Td, Th, THead, Tr } from '../../components/ui/Table'
import { CloudBadge, DecisionBadge } from '../../components/ui/badges'
import { DecisionReviewPanel } from '../../components/decisions/DecisionReviewPanel'
import { DecisionTrace } from '../../components/decisions/DecisionTrace'
import { EmptyState, ErrorState, LoadingState } from '../../components/ui/states'
import { useDecisions, useQuarantine } from '../../lib/query/useDecisions'
import { useSessions } from '../../lib/query/useSessions'
import { formatRelativeTime } from '../../lib/format'
import type { Decision } from '../../types/enums'

const FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'DENY', label: 'Blocked' },
  { value: 'ALLOW', label: 'Allowed' },
] as const

export function ThreatsPage() {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]['value']>('DENY')
  const [expanded, setExpanded] = useState<string | null>(null)
  const decision = filter === 'all' ? undefined : (filter as Decision)
  const query = useDecisions(decision ? { decision } : {})
  const quarantine = useQuarantine()
  const quarantinedSessions = useSessions({ status: 'quarantined', limit: 200 })

  // Sessions just quarantined from this page — instant feedback before the
  // sessions query refetches.
  const [justQuarantined, setJustQuarantined] = useState<Set<string>>(new Set())

  const quarantinedIds = useMemo(() => {
    const ids = new Set<string>(justQuarantined)
    for (const s of quarantinedSessions.data?.sessions ?? []) ids.add(s.session_id)
    return ids
  }, [quarantinedSessions.data, justQuarantined])

  const items = query.data?.pages.flatMap((p) => p.items) ?? []
  const total = query.data?.pages[0]?.total ?? 0

  return (
    <div className="p-4 sm:p-6 lg:p-8">
      <PageHeader
        title="Threat Explorer"
        subtitle="Cross-fleet runtime decisions, newest first."
        actions={<SegmentedControl options={FILTERS} value={filter} onChange={setFilter} />}
      />

      <Card>
        <div className="flex items-center justify-between px-6 py-4" style={{ borderBottom: '1px solid var(--color-line)' }}>
          <span className="text-sm font-medium uppercase tracking-[0.2em] text-secondary">Decisions</span>
          <span className="text-xs font-mono text-muted">{total} total</span>
        </div>

        {query.isLoading ? (
          <LoadingState />
        ) : query.isError ? (
          <ErrorState error={query.error} onRetry={() => query.refetch()} />
        ) : items.length === 0 ? (
          <EmptyState label="No decisions for this filter" />
        ) : (
          <>
            <Table>
              <THead>
                <Th className="w-10" />
                <Th>Agent</Th>
                <Th>Decision</Th>
                <Th>Threat</Th>
                <Th>Tool</Th>
                <Th>Cloud</Th>
                <Th className="text-right">
                  <span title="The session's trust score at the moment this request arrived (before this decision's penalty). Per-session, not per-agent — agent-level trust is on Agent Inventory.">
                    Session Trust
                  </span>
                </Th>
                <Th className="text-right">Seen</Th>
                <Th className="text-right">Action</Th>
              </THead>
              <TBody>
                {items.map((d) => {
                  const open = expanded === d.decision_id
                  const isQuarantined = quarantinedIds.has(d.session_id)
                  const isQuarantining =
                    quarantine.isPending && quarantine.variables?.sessionId === d.session_id
                  return (
                    <Fragment key={d.decision_id}>
                      <Tr onClick={() => setExpanded(open ? null : d.decision_id)}>
                        <Td>{open ? <IconChevronDown size={16} className="text-cyan" /> : <IconChevronRight size={16} className="text-muted" />}</Td>
                        <Td>
                          <div className="font-display font-bold tracking-tight text-white">{d.agent_name}</div>
                          <div className="text-[11px] font-mono text-muted flex items-center gap-1.5">
                            <span className="text-secondary/70">session</span> {d.session_id}
                            {isQuarantined && (
                              <span className="inline-flex items-center gap-1 text-pink uppercase tracking-wide">
                                <StatusDot color="#FF0080" pulse /> quarantined
                              </span>
                            )}
                          </div>
                        </Td>
                        <Td><DecisionBadge decision={d.decision} /></Td>
                        <Td className="font-mono text-xs text-secondary">{d.threat_type ?? '—'}</Td>
                        <Td className="font-mono text-xs text-secondary">{d.tool_name ?? '—'}</Td>
                        <Td><CloudBadge provider={d.cloud_provider} /></Td>
                        <Td className="text-right font-mono" style={{ color: (d.trust_score ?? 100) < 60 ? '#FF0080' : '#8DA2AE' }}>
                          {d.trust_score ?? '—'}
                        </Td>
                        <Td className="text-right font-mono text-muted">{formatRelativeTime(d.timestamp)}</Td>
                        <Td className="text-right">
                          {isQuarantined ? (
                            <span
                              title="This session is quarantined"
                              className="inline-flex items-center gap-1.5 px-3 h-8 rounded-xl text-xs font-bold text-pink bg-pink/10 border border-pink/20"
                            >
                              <IconShieldLock size={14} /> Quarantined
                            </span>
                          ) : (
                            <Button
                              variant="danger"
                              className="!h-8 !px-3"
                              disabled={isQuarantining}
                              onClick={(e) => {
                                e.stopPropagation()
                                quarantine.mutate(
                                  { sessionId: d.session_id, body: { reason: 'Operator review', operator_id: 'dana.reyes' } },
                                  { onSuccess: () => setJustQuarantined((prev) => new Set(prev).add(d.session_id)) },
                                )
                              }}
                            >
                              <IconLockX size={14} /> {isQuarantining ? 'Quarantining…' : 'Quarantine'}
                            </Button>
                          )}
                        </Td>
                      </Tr>
                      {open && (
                        <tr>
                          <td colSpan={9} className="p-0">
                            <DecisionTrace sessionId={d.session_id} requestId={d.request_id} />
                            <DecisionReviewPanel item={d} />
                          </td>
                        </tr>
                      )}
                    </Fragment>
                  )
                })}
              </TBody>
            </Table>

            {query.hasNextPage && (
              <div className="flex justify-center py-4" style={{ borderTop: '1px solid var(--color-line)' }}>
                <Button variant="ghost" onClick={() => query.fetchNextPage()} disabled={query.isFetchingNextPage}>
                  {query.isFetchingNextPage ? 'Loading…' : 'Load more'}
                </Button>
              </div>
            )}
          </>
        )}
      </Card>
    </div>
  )
}
