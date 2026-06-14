import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  IconCheck,
  IconAlertTriangle,
  IconArrowRight,
  IconCircleDashed,
  IconRocket,
} from '@tabler/icons-react'
import { Modal } from '../../components/ui/Modal'
import { Button } from '../../components/ui/Button'
import { CodeBlock } from '../../components/ui/CodeBlock'
import { ROUTES } from '../../app/routes'
import type { ImportResponse, ImportResult } from '../../types/api'
import type { EnforcementMode } from '../../types/enums'

interface ImportResultDrawerProps {
  open: boolean
  onClose: () => void
  result: ImportResponse | null
  enforcementMode: EnforcementMode
}

const STATUS_STYLE: Record<ImportResult['status'], { label: string; color: string }> = {
  managed: { label: 'Policy seeded', color: '#22E58B' },
  skipped: { label: 'Skipped', color: '#8DA2AE' },
  failed: { label: 'Failed', color: '#FF0080' },
}

/** SDK scaffold for the first imported agent — the make-or-break interception step (feature.md §8). */
function sdkSnippet(agentId: string): string {
  return `import os
from aegion_guard import Guard

guard = Guard(
    agent_id="${agentId}",
    enrollment_token=os.environ["AEGION_ENROLL"],
)

@guard.tool
def process_refund(amount, txn_id):
    ...  # routes through POST /v1/validate`
}

/**
 * Import result (feature.md §13 "import result"): per-agent outcome from
 * `POST /v1/discovery/import` plus the honest governance-lifecycle state — an
 * imported agent is policy-seeded but NOT governed until a validate call is
 * observed (feature.md §8), so we surface the SDK wiring step.
 */
export function ImportResultDrawer({ open, onClose, result, enforcementMode }: ImportResultDrawerProps) {
  const navigate = useNavigate()

  const { managed, skipped, failed, firstManaged } = useMemo(() => {
    const rows = result?.agents ?? []
    return {
      managed: rows.filter((r) => r.status === 'managed'),
      skipped: rows.filter((r) => r.status === 'skipped'),
      failed: rows.filter((r) => r.status === 'failed'),
      firstManaged: rows.find((r) => r.status === 'managed' && r.agent_id),
    }
  }, [result])

  if (!result) return null

  return (
    <Modal
      open={open}
      onClose={onClose}
      widthClass="max-w-2xl"
      title={
        <span className="flex items-center gap-2.5">
          <span
            className="h-7 w-7 rounded-lg grid place-items-center"
            style={{ background: 'rgba(34,229,139,0.12)', border: '1px solid rgba(34,229,139,0.3)' }}
          >
            <IconCheck size={16} className="text-green" />
          </span>
          Import complete
        </span>
      }
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Done
          </Button>
          <Button onClick={() => navigate(ROUTES.agents)}>
            Go to Agent Inventory <IconArrowRight size={14} />
          </Button>
        </>
      }
    >
      <div className="space-y-5">
        <p className="text-xs font-mono text-secondary">
          {managed.length} seeded · {skipped.length} skipped · {failed.length} failed ·{' '}
          mode <span className="text-ink uppercase">{enforcementMode}</span>
        </p>

        {/* Governance lifecycle */}
        <div className="rounded-xl p-4" style={{ background: '#05090E', border: '1px solid var(--color-line)' }}>
          <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-secondary mb-3">
            Governance lifecycle
          </div>
          <div className="flex items-center">
            {[
              { label: 'Discovered', done: true },
              { label: 'Policy seeded', done: managed.length > 0 },
              { label: 'Intercepting', done: false },
            ].map((s, i, arr) => (
              <div key={s.label} className="flex items-center flex-1 last:flex-none">
                <div className="flex flex-col items-center gap-1.5">
                  <span
                    className="h-8 w-8 rounded-full grid place-items-center"
                    style={
                      s.done
                        ? { background: '#22E58B', color: '#010B13' }
                        : { border: '1px dashed rgba(255,176,32,0.5)', background: 'rgba(255,176,32,0.06)', color: '#FFB020' }
                    }
                  >
                    {s.done ? <IconCheck size={15} /> : <IconCircleDashed size={15} />}
                  </span>
                  <span className="text-[10px] font-medium" style={{ color: s.done ? '#22E58B' : '#FFB020' }}>
                    {s.label}
                  </span>
                </div>
                {i < arr.length - 1 && <div className="h-px flex-1 mx-1" style={{ background: 'rgba(255,255,255,0.12)' }} />}
              </div>
            ))}
          </div>
          <div
            className="mt-3 flex items-start gap-2 text-[11px] text-secondary rounded-lg p-2.5"
            style={{ background: 'rgba(255,176,32,0.06)', border: '1px solid rgba(255,176,32,0.2)' }}
          >
            <IconAlertTriangle size={14} className="text-amber mt-px shrink-0" />
            <span>
              <span className="text-ink font-medium">Not yet governed.</span> Agents are policy-seeded but
              won&apos;t be governed until we observe a <span className="font-mono text-ink">/v1/validate</span>{' '}
              call. Deploy the SDK below.
            </span>
          </div>
        </div>

        {/* Per-agent results */}
        <div className="space-y-2">
          {(result.agents ?? []).map((row) => {
            const style = STATUS_STYLE[row.status]
            return (
              <div
                key={row.discovery_id}
                className="flex items-center justify-between gap-3 rounded-xl px-4 py-3"
                style={{ border: '1px solid var(--color-line)' }}
              >
                <div className="min-w-0">
                  <div className="font-mono text-xs text-ink truncate">{row.agent_id ?? row.discovery_id}</div>
                  {row.reason && <div className="text-[11px] text-muted truncate">{row.reason}</div>}
                </div>
                <span
                  className="shrink-0 inline-flex items-center px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase tracking-tight"
                  style={{ color: style.color, background: `${style.color}1a`, border: `1px solid ${style.color}33` }}
                >
                  {style.label}
                </span>
              </div>
            )
          })}
        </div>

        {/* Interception next step */}
        {firstManaged?.agent_id && (
          <div className="rounded-xl overflow-hidden" style={{ background: '#05090E', border: '1px solid rgba(15,255,255,0.18)' }}>
            <div className="px-4 py-3 flex items-center gap-2" style={{ borderBottom: '1px solid var(--color-line)' }}>
              <IconRocket size={16} className="text-cyan" />
              <span className="text-[11px] font-semibold uppercase tracking-[0.16em] text-cyan">
                Next step — wire interception
              </span>
            </div>
            <div className="p-4">
              <p className="text-[11px] text-secondary mb-3">
                Drop this into the agent&apos;s tool code. The canonical{' '}
                <span className="font-mono text-ink">agent_id</span> is baked in; the keypair is generated on
                your first deploy — no secret leaves your environment.
              </p>
              <CodeBlock code={sdkSnippet(firstManaged.agent_id)} filename="guarded_tools.py" />
            </div>
          </div>
        )}
      </div>
    </Modal>
  )
}
