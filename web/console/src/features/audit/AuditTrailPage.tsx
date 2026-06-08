import { Fragment, useState } from 'react'
import { IconChevronDown, IconChevronRight } from '@tabler/icons-react'
import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { Button } from '../../components/ui/Button'
import { Table, TBody, Td, Th, THead, Tr } from '../../components/ui/Table'
import { CloudBadge, DecisionBadge } from '../../components/ui/badges'
import { EmptyState, ErrorState, LoadingState } from '../../components/ui/states'
import { useDecisions, useVerdict } from '../../lib/query/useDecisions'
import { formatDateTime } from '../../lib/format'
import type { DecisionItem } from '../../types/api'
import type { Verdict } from '../../types/enums'

/** Decision Review panel — FP for blocked rows, FN for allowed rows (LLD §12). */
function ReviewPanel({ item }: { item: DecisionItem }) {
  const verdict = useVerdict()
  const blocked = item.decision === 'DENY'

  const submit = (v: Verdict) =>
    verdict.mutate({ decisionId: item.decision_id, body: { verdict: v, reason: 'Operator review', operator_id: 'dana.reyes' } })

  if (verdict.isSuccess) {
    return (
      <div className="px-6 py-4 bg-white/[0.015] text-xs font-mono text-green">
        Verdict recorded: {verdict.data?.verdict.replace('_', ' ')}
      </div>
    )
  }

  return (
    <div className="px-6 py-4 bg-white/[0.015] flex items-center justify-between gap-4" style={{ borderTop: '1px solid var(--color-line)' }}>
      <div className="text-xs font-mono text-secondary">
        {blocked
          ? 'Was this block wrong? Mark as a false positive to tune the rule.'
          : 'Was this allow actually malicious? Report a false negative to draft a blocking policy.'}
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {blocked ? (
          <>
            <Button variant="ghost" disabled={verdict.isPending} onClick={() => submit('confirmed_threat')}>Confirm Threat</Button>
            <Button variant="danger" disabled={verdict.isPending} onClick={() => submit('false_positive')}>False Positive</Button>
          </>
        ) : (
          <>
            <Button variant="ghost" disabled={verdict.isPending} onClick={() => submit('confirmed_safe')}>Confirm Allow</Button>
            <Button variant="danger" disabled={verdict.isPending} onClick={() => submit('false_negative')}>False Negative</Button>
          </>
        )}
      </div>
    </div>
  )
}

export function AuditTrailPage() {
  const query = useDecisions({})
  const [expanded, setExpanded] = useState<string | null>(null)
  const items = query.data?.pages.flatMap((p) => p.items) ?? []

  return (
    <div className="p-4 sm:p-6 lg:p-8">
      <PageHeader title="Audit Trail" subtitle="Every runtime decision, reviewable for false positives and negatives." />

      <Card>
        <div className="flex items-center justify-between px-6 py-4" style={{ borderBottom: '1px solid var(--color-line)' }}>
          <span className="text-sm font-medium uppercase tracking-[0.2em] text-secondary">Decision Log</span>
        </div>

        {query.isLoading ? (
          <LoadingState />
        ) : query.isError ? (
          <ErrorState error={query.error} onRetry={() => query.refetch()} />
        ) : items.length === 0 ? (
          <EmptyState label="No decisions logged" />
        ) : (
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
                        <div className="text-[11px] font-mono text-muted">{d.decision_id}</div>
                      </Td>
                      <Td><DecisionBadge decision={d.decision} /></Td>
                      <Td className="text-xs text-secondary">{d.reason ?? d.tool_name ?? '—'}</Td>
                      <Td><CloudBadge provider={d.cloud_provider} /></Td>
                      <Td className="text-right font-mono text-muted">{formatDateTime(d.timestamp)}</Td>
                    </Tr>
                    {open && (
                      <tr>
                        <td colSpan={6} className="p-0">
                          <ReviewPanel item={d} />
                        </td>
                      </tr>
                    )}
                  </Fragment>
                )
              })}
            </TBody>
          </Table>
        )}
      </Card>
    </div>
  )
}
