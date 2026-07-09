import { useParams } from 'react-router-dom'
import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { SessionTrailView } from '../../components/decisions/SessionTrailView'
import { EmptyState } from '../../components/ui/states'

/**
 * Decision detail (M-G3.4 / FX-1.2). Keyed on the COMPOSITE PK
 * `:sessionId/:requestId` (both route params) — `request_id` is REQUIRED for the
 * trail query (the DDB PK is session-scoped, §9A.1). Binds the WS-D SERVER-recomputed
 * trail (`GET /v1/sessions/{id}/trail`) — the four coverage buckets + recomputed
 * `winning_source`/`block_point` — NOT the legacy client-side `/decisions`
 * reconstruction. `SessionTrailView` degrades to a PARTIAL banner + the legacy
 * per-request trace on a 404/501 (endpoint absent on an older stack); never blank,
 * never fabricated.
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
        <SessionTrailView sessionId={sessionId} requestId={requestId} />
      </Card>
    </div>
  )
}
