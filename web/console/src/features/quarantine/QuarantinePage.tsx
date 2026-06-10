import { Fragment, useMemo, useState } from 'react'
import { IconChevronDown, IconChevronRight, IconLockOpen, IconSearch, IconShieldLock } from '@tabler/icons-react'
import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { Button } from '../../components/ui/Button'
import { Table, TBody, Td, Th, THead, Tr } from '../../components/ui/Table'
import { StatusDot } from '../../components/ui/StatusDot'
import { EmptyState, ErrorState, LoadingState } from '../../components/ui/states'
import { DecisionTrace } from '../../components/decisions/DecisionTrace'
import { useInfiniteSessions, useReleaseQuarantine } from '../../lib/query/useSessions'
import { formatNumber, formatRelativeTime } from '../../lib/format'
import type { SessionInfo } from '../../types/api'

function trustColor(score: number): string {
  if (score < 40) return '#FF0080'
  if (score < 70) return '#F5A623'
  return '#22E58B'
}

function ReleaseButton({ session }: { session: SessionInfo }) {
  const release = useReleaseQuarantine()
  const [released, setReleased] = useState(false)
  const pending = release.isPending

  if (released) {
    return (
      <span className="inline-flex items-center gap-1.5 text-xs font-mono text-green">
        <IconLockOpen size={14} /> Released
      </span>
    )
  }

  return (
    <button
      type="button"
      disabled={pending}
      onClick={() =>
        release.mutate(
          { sessionId: session.session_id },
          { onSuccess: () => setReleased(true) },
        )
      }
      title="Release this session from quarantine"
      className="inline-flex items-center gap-1.5 px-3 h-8 rounded-lg text-xs font-bold text-cyan bg-cyan/10 border border-cyan/20 hover:bg-cyan/20 transition-colors cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed"
    >
      <IconLockOpen size={14} /> {pending ? 'Releasing…' : 'Unquarantine'}
    </button>
  )
}

export function QuarantinePage() {
  const query = useInfiniteSessions({ status: 'quarantined', limit: 100 })
  const [expanded, setExpanded] = useState<string | null>(null)
  const [search, setSearch] = useState('')

  // Flatten + dedupe across pages (cursor boundaries are clean, but guard anyway).
  const allSessions = useMemo(() => {
    const seen = new Set<string>()
    const out: SessionInfo[] = []
    for (const p of query.data?.pages ?? []) {
      for (const s of p.items) {
        if (seen.has(s.session_id)) continue
        seen.add(s.session_id)
        out.push(s)
      }
    }
    return out
  }, [query.data])

  // Search across loaded rows (session id, agent, user).
  const needle = search.trim().toLowerCase()
  const sessions = needle
    ? allSessions.filter((s) =>
        [s.session_id, s.agent_id, s.user_id].filter(Boolean).some((v) => String(v).toLowerCase().includes(needle)),
      )
    : allSessions

  return (
    <div className="p-4 sm:p-6 lg:p-8">
      <PageHeader
        title="Quarantined Sessions"
        subtitle="Sessions isolated after trust decay or operator override. Release to restore agent access."
      />

      <Card>
        <div className="flex flex-wrap items-center gap-3 px-6 py-4" style={{ borderBottom: '1px solid var(--color-line)' }}>
          <span className="text-sm font-medium uppercase tracking-[0.2em] text-secondary flex items-center gap-2">
            <IconShieldLock size={15} className="text-pink" /> Quarantine
          </span>
          <div className="relative flex items-center">
            <IconSearch size={14} className="absolute left-3 text-muted" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search session / agent / user…"
              className="h-9 rounded-xl bg-surface-2 pl-8 pr-3 w-64 text-xs font-mono text-white placeholder:text-muted outline-none focus:border-cyan/40"
              style={{ border: '1px solid var(--color-line)' }}
            />
          </div>
          <span className="ml-auto text-xs font-mono text-muted">{sessions.length} loaded{needle ? ' (matched)' : ''}</span>
        </div>

        {query.isLoading ? (
          <LoadingState label="Loading quarantined sessions…" />
        ) : query.isError ? (
          <ErrorState error={query.error} onRetry={() => query.refetch()} />
        ) : sessions.length === 0 ? (
          <EmptyState label="No sessions in quarantine" icon={<IconShieldLock size={26} className="text-green" />} />
        ) : (
          <Table>
            <THead>
              <Th className="w-10" />
              <Th>Session</Th>
              <Th>Agent</Th>
              <Th>User</Th>
              <Th className="text-right">Trust</Th>
              <Th className="text-right">Requests</Th>
              <Th className="text-right">Denied</Th>
              <Th className="text-right">Last activity</Th>
              <Th className="text-right">Action</Th>
            </THead>
            <TBody>
              {sessions.map((s) => {
                const open = expanded === s.session_id
                return (
                  <Fragment key={s.session_id}>
                    <Tr onClick={() => setExpanded(open ? null : s.session_id)}>
                      <Td>{open ? <IconChevronDown size={16} className="text-cyan" /> : <IconChevronRight size={16} className="text-muted" />}</Td>
                      <Td>
                        <div className="font-mono text-xs text-white truncate max-w-[200px]">{s.session_id}</div>
                        <div className="text-[11px] font-mono text-pink uppercase mt-0.5 flex items-center gap-1.5">
                          <StatusDot color="#FF0080" pulse /> {s.quarantine_status}
                        </div>
                      </Td>
                      <Td className="font-mono text-xs text-secondary">{s.agent_id}</Td>
                      <Td className="font-mono text-xs text-muted">{s.user_id}</Td>
                      <Td className="text-right font-mono" style={{ color: trustColor(s.trust_score) }}>
                        {Math.round(s.trust_score)}
                      </Td>
                      <Td className="text-right font-mono text-secondary">{formatNumber(s.total_requests)}</Td>
                      <Td className="text-right font-mono text-pink">{formatNumber(s.deny_count)}</Td>
                      <Td className="text-right font-mono text-muted">{formatRelativeTime(s.last_activity)}</Td>
                      <Td className="text-right">
                        <span onClick={(e) => e.stopPropagation()}>
                          <ReleaseButton session={s} />
                        </span>
                      </Td>
                    </Tr>
                    {open && (
                      <tr>
                        <td colSpan={9} className="p-0">
                          <div className="px-6 pt-3 text-[10px] uppercase tracking-[0.2em] text-label bg-white/[0.015]">
                            Why quarantined — the requests that decayed this session's trust
                          </div>
                          <DecisionTrace sessionId={s.session_id} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </TBody>
          </Table>
        )}

        {query.hasNextPage && (
          <div className="flex justify-center py-4" style={{ borderTop: '1px solid var(--color-line)' }}>
            <Button variant="ghost" onClick={() => query.fetchNextPage()} disabled={query.isFetchingNextPage}>
              {query.isFetchingNextPage ? 'Loading…' : 'Load more'}
            </Button>
          </div>
        )}
      </Card>
    </div>
  )
}
