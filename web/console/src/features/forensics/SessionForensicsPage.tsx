import { useParams } from 'react-router-dom'
import { IconClock, IconLockOpen, IconShieldLock } from '@tabler/icons-react'
import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { Button } from '../../components/ui/Button'
import { StatusDot } from '../../components/ui/StatusDot'
import { DecisionTrace } from '../../components/decisions/DecisionTrace'
import { EmptyState } from '../../components/ui/states'
import { useToast } from '../../components/ui/Toast'
import { useSessionInfo, useReleaseQuarantine } from '../../lib/query/useSessions'
import { useCan } from '../../lib/query/useMe'
import { isAuthDegrade403 } from '../../lib/degrade'
import { formatDateTime, formatNumber, formatPercent } from '../../lib/format'
import type { SessionInfo } from '../../types/api'

/**
 * Session forensics (M-G3.5 / FX-1.3). Keyed on `:sessionId`. Above the per-request
 * `DecisionTrace`, renders the canvas Decision-Trail summary header from the session's
 * `SessionInfo`: trust score, total/allow/deny counts + deny rate, quarantine badge,
 * and the created→last-activity timeline. There is NO single-session GET — the header
 * reads the tenant-scoped session list (`useSessionInfo`) and honestly notes when the
 * session isn't in the current window rather than fabricating counts.
 *
 * The Release (un-quarantine) control renders only for `quarantine.manage` (admin) —
 * mirrors the server `DELETE /v1/quarantine/{id}` gate; hidden (not disabled) for a viewer.
 */

function trustColor(score: number): string {
  if (score < 60) return '#FF0080'
  if (score < 80) return '#FFB020'
  return '#22E58B'
}

function Stat({ label, value, accent }: { label: string; value: string; accent?: string }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[10px] uppercase tracking-[0.18em] text-muted">{label}</span>
      <span className="font-mono text-lg font-bold" style={{ color: accent ?? '#E6EDF3' }}>{value}</span>
    </div>
  )
}

function SummaryHeader({ session }: { session: SessionInfo }) {
  const { success, error } = useToast()
  const can = useCan()
  const release = useReleaseQuarantine()
  const quarantined = session.quarantine_status === 'quarantined'
  const denyRate = session.total_requests > 0 ? session.deny_count / session.total_requests : 0

  const onRelease = () => {
    release.mutate(
      { sessionId: session.session_id },
      {
        onSuccess: () => success(`Session ${session.session_id} released from quarantine.`),
        // FXR-1: a 403 is already surfaced once by the global MutationCache bridge
        // (the sanitized fail-secure toast) — the page must NOT add a second toast
        // for it. Only report non-403 failures here (network/5xx).
        onError: (e) => {
          if (!isAuthDegrade403(e)) error('Could not release the session. Please try again.')
        },
      },
    )
  }

  return (
    <Card className="p-5 mb-5">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex flex-wrap items-center gap-6">
          <Stat label="Trust score" value={formatNumber(session.trust_score)} accent={trustColor(session.trust_score)} />
          <Stat label="Requests" value={formatNumber(session.total_requests)} />
          <Stat label="Allowed" value={formatNumber(session.allow_count)} accent="#22E58B" />
          <Stat label="Denied" value={formatNumber(session.deny_count)} accent="#FF0080" />
          <Stat label="Deny rate" value={formatPercent(denyRate * 100)} accent={denyRate > 0.25 ? '#FF0080' : undefined} />
        </div>
        <div className="flex flex-col items-end gap-2">
          <span
            className="inline-flex items-center gap-2 px-3 h-7 rounded-xl text-xs font-mono font-bold uppercase tracking-wide"
            style={
              quarantined
                ? { color: '#FF0080', background: 'rgba(255,0,128,0.1)', border: '1px solid rgba(255,0,128,0.25)' }
                : { color: '#22E58B', background: 'rgba(34,229,139,0.08)', border: '1px solid rgba(34,229,139,0.22)' }
            }
          >
            {quarantined ? <IconShieldLock size={13} /> : <StatusDot color="#22E58B" />}
            {quarantined ? 'Quarantined' : session.quarantine_status}
          </span>
          {/* FX-1.3: Release is admin-only (server DELETE /quarantine/{id}) — hidden for a viewer. */}
          {quarantined && can('quarantine.manage') && (
            <Button variant="danger" className="!h-8 !px-3" disabled={release.isPending} onClick={onRelease}>
              <IconLockOpen size={14} /> {release.isPending ? 'Releasing…' : 'Release'}
            </Button>
          )}
        </div>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-1 text-[11px] font-mono text-muted">
        <span className="inline-flex items-center gap-1.5">
          <IconClock size={12} /> created {formatDateTime(session.created_at)}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <IconClock size={12} /> last activity {formatDateTime(session.last_activity)}
        </span>
        <span>agent {session.agent_id}</span>
      </div>
    </Card>
  )
}

export function SessionForensicsPage() {
  const { sessionId = '' } = useParams()
  const { session, isLoading, isError } = useSessionInfo(sessionId)

  if (!sessionId) {
    return (
      <div className="p-8">
        <EmptyState label="Missing session id." />
      </div>
    )
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8">
      <PageHeader title="Session Forensics" subtitle={`session ${sessionId}`} />
      {session ? (
        <SummaryHeader session={session} />
      ) : isError ? (
        // FX-1.3: a FAILED session-list fetch is a real error, NOT an absent row.
        // Don't render the benign "not in window" note (which reads as all-clear) —
        // surface the failure honestly. The trace below still attempts its own load.
        // Mirrors SessionTrailView's explicit isError handling (parity, not conflation).
        <Card
          className="px-5 py-3 mb-5 text-[11px] font-mono text-pink"
          role="alert"
          data-testid="session-summary-error"
        >
          Could not load the session summary — showing the per-request trace below.
        </Card>
      ) : !isLoading ? (
        <Card className="px-5 py-3 mb-5 text-[11px] font-mono text-muted">
          Session summary is not in the current window — showing the per-request trace below.
        </Card>
      ) : null}
      <Card className="overflow-hidden">
        <DecisionTrace sessionId={sessionId} />
      </Card>
    </div>
  )
}
