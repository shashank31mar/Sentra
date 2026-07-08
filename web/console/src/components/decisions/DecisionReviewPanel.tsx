import { Button } from '../ui/Button'
import { useVerdict } from '../../lib/query/useDecisions'
import { useCan } from '../../lib/query/useMe'
import type { DecisionItem } from '../../types/api'
import type { Verdict } from '../../types/enums'

/**
 * Operator Decision Review — records a human verdict on a past decision
 * (LLD §12.3, `POST /v1/decisions/{id}/verdict`):
 *  - DENY rows  → "False Positive" (the block was wrong) vs "Confirm Threat"
 *  - ALLOW rows → "False Negative" (the allow was malicious) vs "Confirm Allow"
 *
 * Shared by the Audit Trail and Threat Explorer so both expose the same
 * FP/FN tagging action.
 */
export function DecisionReviewPanel({ item }: { item: DecisionItem }) {
  const verdict = useVerdict()
  // G2.4: FP/FN verdict is an editor write (server POST /decisions/{id}/verdict).
  // Gated once inside the shared panel so every mount (Threats, Audit) inherits it.
  const can = useCan()
  const blocked = item.decision === 'DENY'

  const submit = (v: Verdict) =>
    verdict.mutate({
      decisionId: item.decision_id,
      body: { verdict: v, reason: 'Operator review', operator_id: 'dana.reyes' },
    })

  // Viewers get no verdict control — the trace above stays visible.
  if (!can('decisions.verdict')) return null

  if (verdict.isSuccess) {
    return (
      <div className="px-6 py-4 bg-white/[0.015] text-xs font-mono text-green">
        Verdict recorded: {verdict.data?.verdict.replace('_', ' ')}
      </div>
    )
  }

  return (
    <div
      className="px-6 py-4 bg-white/[0.015] flex items-center justify-between gap-4"
      style={{ borderTop: '1px solid var(--color-line)' }}
    >
      <div className="text-xs font-mono text-secondary">
        {blocked
          ? 'Was this block wrong? Mark as a false positive to tune the rule.'
          : 'Was this allow actually malicious? Report a false negative to draft a blocking policy.'}
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {blocked ? (
          <>
            <Button variant="ghost" disabled={verdict.isPending} onClick={() => submit('confirmed_threat')}>
              Confirm Threat
            </Button>
            <Button variant="danger" disabled={verdict.isPending} onClick={() => submit('false_positive')}>
              False Positive
            </Button>
          </>
        ) : (
          <>
            <Button variant="ghost" disabled={verdict.isPending} onClick={() => submit('confirmed_safe')}>
              Confirm Allow
            </Button>
            <Button variant="danger" disabled={verdict.isPending} onClick={() => submit('false_negative')}>
              False Negative
            </Button>
          </>
        )}
      </div>
    </div>
  )
}
