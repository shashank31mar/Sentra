import { IconArrowRight, IconWorld, IconRobot, IconTool, IconClock } from '@tabler/icons-react'
import { DecisionBadge } from '../ui/badges'
import { LoadingState } from '../ui/states'
import { useSessionDecisions } from '../../lib/query/useSessions'
import { formatDateTime } from '../../lib/format'
import type { DecisionSignal, SessionDecision } from '../../types/api'

/** The validators in the exact order the controller runs them (validation_service pipeline). The
 *  trace renders ALL of these — even when a validator emitted no signal — so the flow is complete:
 *  a stage can ALLOW, DENY, ABSTAIN (e.g. the ML classifier when low-confidence → no signal), or be
 *  NOT REACHED (the pipeline short-circuits on a blocking DENY before the later, costlier stages). */
const PIPELINE: { source: string; label: string }[] = [
  { source: 'sentra.trust', label: 'Trust' },
  { source: 'sentra.policy', label: 'Policy' },
  { source: 'sentra.cross_agent', label: 'Cross-Agent' },
  { source: 'sentra.sigma', label: 'Sigma' },
  { source: 'sentra.ml_classifier', label: 'ML Classifier' },
  { source: 'sentra.context', label: 'Context' },
  { source: 'sentra.abuse', label: 'Rate Limit' },
]
const SOURCE_LABEL: Record<string, string> = Object.fromEntries(PIPELINE.map((p) => [p.source, p.label]))

const sourceLabel = (s: string) => SOURCE_LABEL[s] ?? s.replace(/^sentra\./, '')

function Meta({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-[11px] font-mono text-muted">
      {icon} {children}
    </span>
  )
}

type StepStatus = 'ran' | 'abstained' | 'not_reached'

/** One pipeline stage. Renders whether it ran (ALLOW/DENY + reason), abstained (no signal), or was
 *  not reached because an earlier stage short-circuited the pipeline. The winning DENY is highlighted. */
function SignalStep({
  label,
  sig,
  status,
  winner,
  blockedBy,
}: {
  label: string
  sig: DecisionSignal | null
  status: StepStatus
  winner: boolean
  blockedBy?: string | null
}) {
  const denied = sig?.decision === 'DENY'
  const model = (sig?.metadata?.model_used as string | undefined) // ML: "hot" (Haiku) | "escalation" (Sonnet)
  const dim = status !== 'ran'

  return (
    <div
      className="flex items-start gap-3 px-3 py-2 rounded-lg"
      style={{
        background: winner ? 'rgba(255,0,128,0.06)' : 'transparent',
        border: winner ? '1px solid rgba(255,0,128,0.25)' : '1px solid var(--color-line)',
        opacity: dim ? 0.6 : 1,
      }}
    >
      <div className="w-24 shrink-0 text-xs font-mono font-bold text-secondary">{label}</div>
      <div className="shrink-0">
        {status === 'ran' ? (
          <DecisionBadge decision={denied ? 'DENY' : 'ALLOW'} />
        ) : (
          <span className="inline-flex items-center px-2 h-5 rounded text-[10px] font-mono uppercase tracking-wide text-muted"
            style={{ border: '1px solid var(--color-line)' }}>
            {status === 'abstained' ? 'abstain' : 'skipped'}
          </span>
        )}
      </div>
      <div className="min-w-0 flex-1 text-xs font-mono">
        {status === 'not_reached' ? (
          <span className="text-faint">not reached — pipeline short-circuited{blockedBy ? ` at ${blockedBy}` : ''}</span>
        ) : status === 'abstained' ? (
          <span className="text-faint">abstained — below confidence threshold (no verdict emitted)</span>
        ) : sig?.reason ? (
          <span className={denied ? 'text-pink' : 'text-muted'}>{sig.reason}</span>
        ) : (
          <span className="text-faint">— passed</span>
        )}
        {sig?.matched_rule && <div className="text-[10px] text-muted mt-0.5">rule: {sig.matched_rule}</div>}
        {typeof sig?.confidence === 'number' && (
          <div className="text-[10px] text-muted mt-0.5">
            confidence: {(sig.confidence * 100).toFixed(0)}%{model ? ` · ${model === 'escalation' ? 'Sonnet (escalated)' : 'Haiku (hot)'}` : ''}
          </div>
        )}
      </div>
    </div>
  )
}

function DecisionCard({ d }: { d: SessionDecision }) {
  const blocked = d.combined.decision === 'DENY'
  const winnerSource = d.combined.winning_source
  const bySource = new Map(d.signals.map((s) => [s.source, s]))
  const winnerIdx = PIPELINE.findIndex((p) => p.source === winnerSource)

  // Walk the canonical pipeline. A stage either ran (has a signal), abstained (no signal but the
  // request wasn't short-circuited before it), or was not reached (a blocking DENY upstream stopped
  // the pipeline). This makes ML visible even when it abstains or is short-circuited on a block.
  const steps = PIPELINE.map((stage, i) => {
    const sig = bySource.get(stage.source) ?? null
    let status: StepStatus = 'ran'
    if (!sig) status = blocked && winnerIdx >= 0 && i > winnerIdx ? 'not_reached' : 'abstained'
    return { ...stage, sig, status, winner: stage.source === winnerSource && sig?.decision === 'DENY' }
  })
  const blockedByLabel = winnerIdx >= 0 ? PIPELINE[winnerIdx].label : null

  return (
    <div className="rounded-xl p-4" style={{ background: '#0B141C', border: '1px solid var(--color-line)' }}>
      {/* Prompt */}
      <div className="text-[10px] uppercase tracking-[0.2em] text-label mb-1.5">Prompt</div>
      <pre className="text-xs font-mono whitespace-pre-wrap break-words rounded-lg px-3 py-2 text-secondary"
        style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid var(--color-line)' }}>
        {d.user_input || '— (no prompt captured)'}
      </pre>

      {/* Meta */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 mt-3">
        {d.agent_id && <Meta icon={<IconRobot size={12} />}>{d.agent_id}</Meta>}
        {d.tool_name && <Meta icon={<IconTool size={12} />}>{d.tool_name}</Meta>}
        <Meta icon={<IconWorld size={12} />}>{d.source_ip || 'IP n/a'}</Meta>
        {d.timestamp_iso && <Meta icon={<IconClock size={12} />}>{formatDateTime(d.timestamp_iso)}</Meta>}
      </div>

      {/* Verdict */}
      <div className="mt-3 flex items-center gap-2 text-xs font-mono">
        <DecisionBadge decision={blocked ? 'DENY' : 'ALLOW'} />
        {blocked && (
          <span className="text-pink">
            {d.combined.reason}
            {d.combined.winning_source && <span className="text-muted"> · by {sourceLabel(d.combined.winning_source)}</span>}
            {d.combined.severity && <span className="text-amber"> · {d.combined.severity}</span>}
          </span>
        )}
      </div>

      {/* Flow / breadcrumbs */}
      <div className="text-[10px] uppercase tracking-[0.2em] text-label mt-4 mb-2 flex items-center gap-1.5">
        Validation flow <IconArrowRight size={11} />
      </div>
      <div className="flex flex-col gap-1.5">
        {steps.map((s) => (
          <SignalStep
            key={s.source}
            label={s.label}
            sig={s.sig}
            status={s.status}
            winner={s.winner}
            blockedBy={blockedByLabel}
          />
        ))}
      </div>
    </div>
  )
}

/**
 * Forensic trace for a session (or a single request within it):
 * the prompt, the caller (agent / IP), the verdict + why, and the per-validator flow.
 * Used by the Threat Explorer (one request) and the Quarantine console (whole session).
 */
export function DecisionTrace({ sessionId, requestId }: { sessionId: string; requestId?: string }) {
  const q = useSessionDecisions(sessionId, requestId)
  const decisions = q.data?.decisions ?? []

  return (
    <div className="px-6 py-4 bg-white/[0.015] flex flex-col gap-3" style={{ borderTop: '1px solid var(--color-line)' }}>
      {q.isLoading ? (
        <LoadingState label="Loading trace…" />
      ) : q.isError ? (
        <div className="text-xs font-mono text-pink">Could not load the decision trace.</div>
      ) : decisions.length === 0 ? (
        <div className="text-xs font-mono text-muted">
          No stored trace for this session (signals expire after 90 days).
        </div>
      ) : (
        decisions.map((d) => <DecisionCard key={d.request_id} d={d} />)
      )}
    </div>
  )
}
