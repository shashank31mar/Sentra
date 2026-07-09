import { Fragment, useMemo, useState } from 'react'
import { IconChevronDown, IconChevronRight, IconLockX, IconSearch, IconShieldLock, IconX } from '@tabler/icons-react'
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
import { useCan } from '../../lib/query/useMe'
import { formatRelativeTime } from '../../lib/format'
import type { Decision } from '../../types/enums'
import type { DecisionItem } from '../../types/api'

const FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'DENY', label: 'Blocked' },
  { value: 'ALLOW', label: 'Allowed' },
] as const

/** Cosmetic label for a deciding source (FX-3.1). Purely display — the raw
 *  `winning_source` value stays the source of truth for the facet + filtering. */
const sourceLabel = (s: string) =>
  s.replace(/^sentra\./, '').replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())

const ALL_SOURCES = '__all__'

export function ThreatsPage() {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]['value']>('DENY')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [sessionId, setSessionId] = useState('')
  const [search, setSearch] = useState('')
  // FX-3.1: per-detector facet (deciding source), client-side over the loaded rows.
  const [source, setSource] = useState<string>(ALL_SOURCES)
  const decision = filter === 'all' ? undefined : (filter as Decision)

  // Server-side filters page through ALL matching threats via the cursor (Load more); session-id is
  // a backend filter. limit=100 = fewer round-trips.
  const serverFilters = useMemo(
    () => ({
      ...(decision ? { decision } : {}),
      ...(sessionId.trim() ? { session_id: sessionId.trim() } : {}),
      limit: 100,
    }),
    [decision, sessionId],
  )
  const query = useDecisions(serverFilters)
  const quarantine = useQuarantine()
  const quarantinedSessions = useSessions({ status: 'quarantined', limit: 200 })
  // G2.4: inline Quarantine is admin-only (server POST /quarantine/{id}).
  const can = useCan()
  const canQuarantine = can('quarantine.manage')

  // Sessions just quarantined from this page — instant feedback before the
  // sessions query refetches.
  const [justQuarantined, setJustQuarantined] = useState<Set<string>>(new Set())

  const quarantinedIds = useMemo(() => {
    const ids = new Set<string>(justQuarantined)
    for (const s of quarantinedSessions.data?.sessions ?? []) ids.add(s.session_id)
    return ids
  }, [quarantinedSessions.data, justQuarantined])

  // Flatten pages + dedupe by decision_id (cursor page boundaries can re-include a row).
  const allItems = useMemo(() => {
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

  // FX-3.1: facet options DERIVED from the API's `winning_source` values on the
  // loaded rows — never a FE constant. If NO row carries the field (the backend
  // field-add is absent), `sourceOptions` is empty and the facet ships PARTIAL/
  // disabled with a note; the rows still render (no crash, no fabricated list).
  const sourceOptions = useMemo(() => {
    const set = new Set<string>()
    for (const d of allItems) {
      if (d.winning_source) set.add(d.winning_source)
    }
    return Array.from(set).sort()
  }, [allItems])
  const facetAvailable = sourceOptions.length > 0

  // Free-text search over the loaded rows (agent, reason, tool, threat, session, id).
  const needle = search.trim().toLowerCase()
  const items = useMemo(() => {
    let out = allItems
    // Apply the deciding-source facet only when a specific source is chosen AND the
    // field is present (otherwise the facet is inert — never silently empties the list).
    if (facetAvailable && source !== ALL_SOURCES) {
      out = out.filter((d) => d.winning_source === source)
    }
    if (needle) {
      out = out.filter((d) =>
        [d.agent_name, d.reason, d.tool_name, d.threat_type, d.session_id, d.decision_id]
          .filter(Boolean)
          .some((v) => String(v).toLowerCase().includes(needle)),
      )
    }
    return out
  }, [allItems, facetAvailable, source, needle])
  const total = query.data?.pages[0]?.total ?? 0

  return (
    <div className="p-4 sm:p-6 lg:p-8">
      <PageHeader
        title="Threat Explorer"
        subtitle="Cross-fleet runtime decisions, newest first."
        actions={<SegmentedControl options={FILTERS} value={filter} onChange={setFilter} />}
      />

      <Card>
        <div className="flex flex-wrap items-center gap-3 px-6 py-4" style={{ borderBottom: '1px solid var(--color-line)' }}>
          <span className="text-sm font-medium uppercase tracking-[0.2em] text-secondary">Decisions</span>
          <div className="relative flex items-center">
            <IconSearch size={14} className="absolute left-3 text-muted" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search loaded rows…"
              className="h-9 rounded-xl bg-surface-2 pl-8 pr-3 w-52 text-xs font-mono text-white placeholder:text-muted outline-none focus:border-cyan/40"
              style={{ border: '1px solid var(--color-line)' }}
            />
          </div>
          <div className="relative flex items-center">
            <input
              value={sessionId}
              onChange={(e) => setSessionId(e.target.value)}
              placeholder="Filter by session id…"
              className="h-9 rounded-xl bg-surface-2 px-3 w-60 text-xs font-mono text-white placeholder:text-muted outline-none focus:border-cyan/40"
              style={{ border: '1px solid var(--color-line)' }}
            />
            {sessionId && (
              <button type="button" onClick={() => setSessionId('')} className="absolute right-2 text-muted hover:text-pink" aria-label="Clear session filter">
                <IconX size={14} />
              </button>
            )}
          </div>
          {/* FX-3.1: per-detector facet — options DRIVEN from the API's winning_source
              values (never a FE constant). PARTIAL/disabled when the field is absent. */}
          {facetAvailable ? (
            <select
              aria-label="Filter by deciding source"
              value={source}
              onChange={(e) => setSource(e.target.value)}
              className="h-9 rounded-xl bg-surface-2 px-3 text-xs font-mono text-white outline-none focus:border-cyan/40"
              style={{ border: '1px solid var(--color-line)' }}
            >
              <option value={ALL_SOURCES}>All detectors</option>
              {sourceOptions.map((s) => (
                <option key={s} value={s}>{sourceLabel(s)}</option>
              ))}
            </select>
          ) : (
            <span
              data-testid="source-facet-partial"
              title="Per-detector filtering needs the winning_source field on /decisions rows (backend field-add pending)."
              className="h-9 inline-flex items-center rounded-xl bg-surface-2 px-3 text-xs font-mono text-faint"
              style={{ border: '1px solid var(--color-line)' }}
            >
              Detector facet — pending
            </span>
          )}
          <span className="ml-auto text-xs font-mono text-muted">
            {items.length} loaded{needle ? ' (matched)' : ''} · {total}+ in window
          </span>
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
                          ) : canQuarantine ? (
                            <Button
                              variant="danger"
                              className="!h-8 !px-3"
                              disabled={isQuarantining}
                              onClick={(e) => {
                                e.stopPropagation()
                                quarantine.mutate(
                                  // No operator_id — server derives from ctx.sub (M-G3.13).
                                  { sessionId: d.session_id, body: { reason: 'Operator review' } },
                                  { onSuccess: () => setJustQuarantined((prev) => new Set(prev).add(d.session_id)) },
                                )
                              }}
                            >
                              <IconLockX size={14} /> {isQuarantining ? 'Quarantining…' : 'Quarantine'}
                            </Button>
                          ) : (
                            <span className="text-[11px] font-mono text-faint">—</span>
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
