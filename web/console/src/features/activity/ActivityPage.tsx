import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import { IconActivity } from '@tabler/icons-react'
import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { Button } from '../../components/ui/Button'
import { Table, TBody, Td, Th, THead, Tr } from '../../components/ui/Table'
import { CloudBadge, DecisionBadge } from '../../components/ui/badges'
import { EmptyState, ErrorState, LoadingState } from '../../components/ui/states'
import { useDecisions } from '../../lib/query/useDecisions'
import { decisionDetailPath } from '../../app/routes'
import { formatRelativeTime } from '../../lib/format'
import type { DecisionItem } from '../../types/api'

/**
 * Activity / live-decision feed (M-G3.2 — BUILD). Binds `GET /v1/decisions` through
 * `useDecisions` (which polls at 15s — this is a PULL cadence, NOT streaming; there
 * is deliberately NO WebSocket/SSE). Read-only for any authenticated operator. Each
 * row links to the decision detail using BOTH `session_id` AND `request_id` (the
 * composite PK — a request_id-only link can't key the trail query). Server
 * tenant-scopes; no client tenant filter.
 */
export function ActivityPage() {
  const query = useDecisions({})

  const items = useMemo(() => {
    const seen = new Set<string>()
    const out: DecisionItem[] = []
    for (const p of query.data?.pages ?? []) {
      for (const d of p.items) {
        if (seen.has(d.decision_id)) continue
        seen.add(d.decision_id)
        out.push(d)
      }
    }
    return out
  }, [query.data])

  return (
    <div className="p-4 sm:p-6 lg:p-8">
      <PageHeader
        title="Activity"
        subtitle="Live runtime decisions across your fleet, newest first."
        actions={
          <span className="inline-flex items-center gap-1.5 text-[11px] font-mono text-secondary">
            <IconActivity size={14} className="text-green" /> near-real-time (≤15s pull)
          </span>
        }
      />

      <Card>
        {query.isLoading ? (
          <LoadingState />
        ) : query.isError ? (
          <ErrorState error={query.error} onRetry={() => query.refetch()} />
        ) : items.length === 0 ? (
          <EmptyState label="No recent activity" />
        ) : (
          <>
            <Table>
              <THead>
                <Th>Agent</Th>
                <Th>Decision</Th>
                <Th>Threat</Th>
                <Th>Tool</Th>
                <Th>Cloud</Th>
                <Th className="text-right">Seen</Th>
                <Th className="text-right">Trail</Th>
              </THead>
              <TBody>
                {items.map((d) => (
                  <Tr key={d.decision_id}>
                    <Td>
                      <div className="font-display font-bold text-white">{d.agent_name}</div>
                      <div className="text-[11px] font-mono text-muted">session {d.session_id}</div>
                    </Td>
                    <Td><DecisionBadge decision={d.decision} /></Td>
                    <Td className="font-mono text-xs text-secondary">{d.threat_type ?? '—'}</Td>
                    <Td className="font-mono text-xs text-secondary">{d.tool_name ?? '—'}</Td>
                    <Td><CloudBadge provider={d.cloud_provider} /></Td>
                    <Td className="text-right font-mono text-muted">{formatRelativeTime(d.timestamp)}</Td>
                    <Td className="text-right">
                      <Link
                        to={decisionDetailPath(d.session_id, d.request_id)}
                        className="text-xs font-mono text-blue hover:underline"
                      >
                        View trail →
                      </Link>
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
