import { Fragment, useMemo, useState } from 'react'
import { IconChevronDown, IconChevronRight, IconSearch, IconX } from '@tabler/icons-react'
import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { SegmentedControl } from '../../components/ui/SegmentedControl'
import { Button } from '../../components/ui/Button'
import { Table, TBody, Td, Th, THead, Tr } from '../../components/ui/Table'
import { CloudBadge, DecisionBadge } from '../../components/ui/badges'
import { DecisionReviewPanel } from '../../components/decisions/DecisionReviewPanel'
import { DecisionTrace } from '../../components/decisions/DecisionTrace'
import { EmptyState, ErrorState, LoadingState } from '../../components/ui/states'
import { useDecisions } from '../../lib/query/useDecisions'
import { formatDateTime } from '../../lib/format'
import type { Decision } from '../../types/enums'

const FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'DENY', label: 'Blocked' },
  { value: 'ALLOW', label: 'Allowed' },
] as const

export function AuditTrailPage() {
  const [decisionFilter, setDecisionFilter] = useState<(typeof FILTERS)[number]['value']>('all')
  const [sessionId, setSessionId] = useState('')
  const [search, setSearch] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)

  // Server-side filters (decision + session id). The session-id box is debounce-free — it filters on
  // submit/blur via the trimmed value so we don't refetch on every keystroke.
  const serverFilters = useMemo(
    () => ({
      ...(decisionFilter === 'all' ? {} : { decision: decisionFilter as Decision }),
      ...(sessionId.trim() ? { session_id: sessionId.trim() } : {}),
    }),
    [decisionFilter, sessionId],
  )
  const query = useDecisions(serverFilters)

  const allItems = query.data?.pages.flatMap((p) => p.items) ?? []
  // Free-text search is applied client-side over the loaded pages (agent, reason, tool, id, session).
  const needle = search.trim().toLowerCase()
  const items = needle
    ? allItems.filter((d) =>
        [d.agent_name, d.reason, d.tool_name, d.decision_id, d.session_id, d.threat_type]
          .filter(Boolean)
          .some((v) => String(v).toLowerCase().includes(needle)),
      )
    : allItems

  const inputCls =
    'h-9 rounded-xl bg-surface-2 px-3 text-xs font-mono text-white placeholder:text-muted outline-none focus:border-cyan/40'

  return (
    <div className="p-4 sm:p-6 lg:p-8">
      <PageHeader
        title="Audit Trail"
        subtitle="Every runtime decision, reviewable for false positives and negatives."
        actions={<SegmentedControl options={FILTERS} value={decisionFilter} onChange={setDecisionFilter} />}
      />

      <Card>
        <div className="flex flex-wrap items-center gap-3 px-6 py-4" style={{ borderBottom: '1px solid var(--color-line)' }}>
          <div className="relative flex items-center">
            <IconSearch size={14} className="absolute left-3 text-muted" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search loaded rows…"
              className={`${inputCls} pl-8 w-56`}
              style={{ border: '1px solid var(--color-line)' }}
            />
          </div>
          <div className="relative flex items-center">
            <input
              value={sessionId}
              onChange={(e) => setSessionId(e.target.value)}
              placeholder="Filter by session id…"
              className={`${inputCls} w-64`}
              style={{ border: '1px solid var(--color-line)' }}
            />
            {sessionId && (
              <button type="button" onClick={() => setSessionId('')} className="absolute right-2 text-muted hover:text-pink" aria-label="Clear session filter">
                <IconX size={14} />
              </button>
            )}
          </div>
          <span className="ml-auto text-xs font-mono text-muted">
            {items.length}
            {needle ? ' matched' : ''} loaded
          </span>
        </div>

        {query.isLoading ? (
          <LoadingState />
        ) : query.isError ? (
          <ErrorState error={query.error} onRetry={() => query.refetch()} />
        ) : items.length === 0 ? (
          <EmptyState label={needle || sessionId ? 'No decisions match your filters' : 'No decisions logged'} />
        ) : (
          <>
            <Table>
              <THead>
                <Th className="w-10" />
                <Th>Agent</Th>
                <Th>Decision</Th>
                <Th>Detail</Th>
                <Th>Cloud</Th>
                <Th className="text-right">Time</Th>
              </THead>
              <TBody>
                {items.map((d) => {
                  const open = expanded === d.decision_id
                  return (
                    <Fragment key={d.decision_id}>
                      <Tr onClick={() => setExpanded(open ? null : d.decision_id)}>
                        <Td>{open ? <IconChevronDown size={16} className="text-cyan" /> : <IconChevronRight size={16} className="text-muted" />}</Td>
                        <Td>
                          <div className="font-display font-bold text-white">{d.agent_name}</div>
                          <div className="text-[11px] font-mono text-muted">{d.session_id}</div>
                        </Td>
                        <Td><DecisionBadge decision={d.decision} /></Td>
                        <Td className="text-xs text-secondary">{d.reason ?? d.tool_name ?? '—'}</Td>
                        <Td><CloudBadge provider={d.cloud_provider} /></Td>
                        <Td className="text-right font-mono text-muted">{formatDateTime(d.timestamp)}</Td>
                      </Tr>
                      {open && (
                        <tr>
                          <td colSpan={6} className="p-0">
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
