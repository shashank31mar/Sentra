import { useState } from 'react'
import { IconLockX } from '@tabler/icons-react'
import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { SegmentedControl } from '../../components/ui/SegmentedControl'
import { Button } from '../../components/ui/Button'
import { Table, TBody, Td, Th, THead, Tr } from '../../components/ui/Table'
import { CloudBadge, DecisionBadge } from '../../components/ui/badges'
import { EmptyState, ErrorState, LoadingState } from '../../components/ui/states'
import { useDecisions, useQuarantine } from '../../lib/query/useDecisions'
import { formatRelativeTime } from '../../lib/format'
import type { Decision } from '../../types/enums'

const FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'DENY', label: 'Blocked' },
  { value: 'ALLOW', label: 'Allowed' },
] as const

export function ThreatsPage() {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]['value']>('DENY')
  const decision = filter === 'all' ? undefined : (filter as Decision)
  const query = useDecisions(decision ? { decision } : {})
  const quarantine = useQuarantine()

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
                <Th>Agent</Th>
                <Th>Decision</Th>
                <Th>Threat</Th>
                <Th>Tool</Th>
                <Th>Cloud</Th>
                <Th className="text-right">Trust</Th>
                <Th className="text-right">Seen</Th>
                <Th className="text-right">Action</Th>
              </THead>
              <TBody>
                {items.map((d) => (
                  <Tr key={d.decision_id}>
                    <Td>
                      <div className="font-display font-bold tracking-tight text-white">{d.agent_name}</div>
                      <div className="text-[11px] font-mono text-muted">{d.session_id}</div>
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
                      <Button
                        variant="danger"
                        className="!h-8 !px-3"
                        disabled={quarantine.isPending}
                        onClick={() =>
                          quarantine.mutate({ sessionId: d.session_id, body: { reason: 'Operator review', operator_id: 'dana.reyes' } })
                        }
                      >
                        <IconLockX size={14} /> Quarantine
                      </Button>
                    </Td>
                  </Tr>
                ))}
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
