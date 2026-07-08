import { useParams } from 'react-router-dom'
import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { DecisionTrace } from '../../components/decisions/DecisionTrace'
import { EmptyState } from '../../components/ui/states'

/**
 * Session forensics (M-G3.5). Keyed on `:sessionId`. There is NO single-session GET
 * (`GET /v1/sessions/{id}` does not exist — do not invent it); the per-request body
 * comes from `GET /v1/sessions/{id}/decisions` via the shared `DecisionTrace`, which
 * renders one card per request in the session. The server tenant-scopes `/sessions*`
 * — no client tenant filter.
 */
export function SessionForensicsPage() {
  const { sessionId = '' } = useParams()

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
      <Card className="overflow-hidden">
        <DecisionTrace sessionId={sessionId} />
      </Card>
    </div>
  )
}
