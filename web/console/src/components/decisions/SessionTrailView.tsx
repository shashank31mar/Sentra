import { DecisionBadge } from '../ui/badges'
import { LoadingState } from '../ui/states'
import { DecisionTrace } from './DecisionTrace'
import { useSessionTrail } from '../../lib/query/useSessions'
import { ApiException } from '../../lib/http'
import type { SessionTrailEntry } from '../../types/api'

/**
 * FX-1.2 — Decision-detail bound to the WS-D server-recomputed trail
 * (`GET /v1/sessions/{id}/trail`), NOT the legacy client-side `/decisions`
 * reconstruction. Renders the four coverage buckets (ran / abstain / error / not-run)
 * + the recomputed `winning_source` / `block_point`. On a 404/501 (the endpoint is
 * absent on an older stack) it degrades to a PARTIAL banner + the legacy `DecisionTrace`
 * fallback — never a blank view, never a fabricated trail.
 */

const STATE_STYLE: Record<SessionTrailEntry['state'], { fg: string; label: string }> = {
  ran: { fg: '#22E58B', label: 'ran' },
  ran_abstain: { fg: '#8DA2AE', label: 'abstain' },
  ran_error: { fg: '#FFB020', label: 'error' },
  not_run: { fg: '#51636E', label: 'skipped' },
}

function CoverageRow({ entry, winner }: { entry: SessionTrailEntry; winner: boolean }) {
  const denied = entry.decision === 'DENY'
  const style = STATE_STYLE[entry.state]
  return (
    <div
      className="flex items-start gap-3 px-3 py-2 rounded-lg"
      style={{
        background: winner ? 'rgba(255,0,128,0.06)' : 'transparent',
        border: winner ? '1px solid rgba(255,0,128,0.25)' : '1px solid var(--color-line)',
        opacity: entry.state === 'ran' ? 1 : 0.65,
      }}
    >
      <div className="w-28 shrink-0 text-xs font-mono font-bold text-secondary">{entry.display_name}</div>
      <div className="shrink-0">
        {entry.state === 'ran' && entry.decision ? (
          <DecisionBadge decision={denied ? 'DENY' : 'ALLOW'} />
        ) : (
          <span
            className="inline-flex items-center px-2 h-5 rounded text-[10px] font-mono uppercase tracking-wide"
            style={{ border: '1px solid var(--color-line)', color: style.fg }}
          >
            {entry.state_label || style.label}
          </span>
        )}
      </div>
      <div className="min-w-0 flex-1 text-xs font-mono">
        {entry.reason ? (
          <span className={denied ? 'text-pink' : 'text-muted'}>{entry.reason}</span>
        ) : (
          <span className="text-faint">—</span>
        )}
        {typeof entry.latency_ms === 'number' && (
          <div className="text-[10px] text-muted mt-0.5">{entry.latency_ms} ms</div>
        )}
      </div>
    </div>
  )
}

function Stat({ label, value, accent }: { label: string; value: number; accent?: string }) {
  return (
    <div className="flex flex-col">
      <span className="text-[10px] uppercase tracking-[0.18em] text-muted">{label}</span>
      <span className="font-mono text-lg font-bold" style={{ color: accent ?? '#E6EDF3' }}>{value}</span>
    </div>
  )
}

export function SessionTrailView({ sessionId, requestId }: { sessionId: string; requestId: string }) {
  const q = useSessionTrail(sessionId, requestId)

  if (q.isLoading) {
    return (
      <div className="px-6 py-4">
        <LoadingState label="Loading decision trail…" />
      </div>
    )
  }

  // PARTIAL fallback: the trail endpoint is absent (older stack) → 404/501. Show a
  // banner + the legacy client-reconstructed trace so the operator still sees the
  // per-validator breadcrumbs — never blank, never fabricated.
  const status = q.error instanceof ApiException ? q.error.status : 0
  if (q.isError && (status === 404 || status === 501)) {
    return (
      <div className="flex flex-col">
        <div
          className="mx-6 mt-4 rounded-xl border px-4 py-3 text-xs"
          style={{ borderColor: 'rgba(255,176,32,0.3)', background: 'rgba(255,176,32,0.05)', color: '#FFB020' }}
          role="status"
          data-testid="trail-partial-banner"
        >
          Recomputed decision trail is not available on this deployment yet — showing the
          per-request trace instead (PARTIAL).
        </div>
        <DecisionTrace sessionId={sessionId} requestId={requestId} />
      </div>
    )
  }

  if (q.isError || !q.data) {
    return <div className="px-6 py-4 text-xs font-mono text-pink">Could not load the decision trail.</div>
  }

  const trail = q.data
  const blocked = trail.decision === 'DENY'

  return (
    <div className="px-6 py-4 flex flex-col gap-4" data-testid="trail-view">
      {/* Verdict + winning source */}
      <div className="flex flex-wrap items-center gap-3">
        <DecisionBadge decision={blocked ? 'DENY' : 'ALLOW'} />
        {blocked && trail.winning_source && (
          <span className="text-xs font-mono text-pink">
            blocked at {trail.winning_source_display ?? trail.winning_source}
          </span>
        )}
        <span className="text-[11px] font-mono text-muted">phase: {trail.phase}</span>
      </div>

      {/* Coverage buckets summary */}
      <div className="grid grid-cols-4 gap-4 rounded-xl px-4 py-3" style={{ border: '1px solid var(--color-line)' }}>
        <Stat label="Ran" value={trail.ran_count} accent="#22E58B" />
        <Stat label="Abstain" value={trail.abstain_count} accent="#8DA2AE" />
        <Stat label="Error" value={trail.ran_error_count} accent="#FFB020" />
        <Stat label="Not run" value={trail.not_run_count} accent="#51636E" />
      </div>

      {/* Per-validator coverage in order */}
      <div className="flex flex-col gap-1.5">
        {trail.coverage.map((entry) => (
          <CoverageRow
            key={entry.source}
            entry={entry}
            winner={entry.source === trail.winning_source && entry.decision === 'DENY'}
          />
        ))}
        {trail.coverage.length === 0 && (
          <span className="text-xs font-mono text-muted">No coverage rows for this request.</span>
        )}
      </div>
    </div>
  )
}
