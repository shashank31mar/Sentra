import { useParams } from 'react-router-dom'
import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { DecisionTrace } from '../../components/decisions/DecisionTrace'
import { EmptyState } from '../../components/ui/states'

/**
 * Decision detail (M-G3.4). Keyed on the COMPOSITE PK `:sessionId/:requestId` (both
 * route params) — a request_id-only route can't key the trail query (routes.py:554
 * keys `{session_id}#{request_id}`). Renders the per-validator forensic trace via
 * the shared `DecisionTrace` bound to the LIVE `/sessions/{id}/decisions` slice
 * narrowed to this request. No fabricated data — if the store has no trace,
 * `DecisionTrace` shows its own honest "no stored trace" state.
 *
 * (The dedicated WS-D `/trail` four-bucket view binds here once its shape is
 * confirmed; until then this uses the live per-request trace — the same forensic
 * content, no fabrication.)
 */
export function DecisionDetailPage() {
  const { sessionId = '', requestId = '' } = useParams()

  if (!sessionId || !requestId) {
    return (
      <div className="p-8">
        <EmptyState label="Missing session or request id." />
      </div>
    )
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8">
      <PageHeader
        title="Decision Detail"
        subtitle={`session ${sessionId} · request ${requestId}`}
      />
      <Card className="overflow-hidden">
        <DecisionTrace sessionId={sessionId} requestId={requestId} />
      </Card>
    </div>
  )
}
