import { IconAlertTriangle } from '@tabler/icons-react'
import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { ErrorState, LoadingState } from '../../components/ui/states'
import { useUsage } from '../../lib/query/useUsage'
import { ApiException } from '../../lib/http'
import { formatNumber } from '../../lib/format'

/** Whether the usage feature is live in this build train (WS-H). OFF ⇒ no nav item
 *  (no dark billing tab); the route still renders a PARTIAL banner if reached. */
export const USAGE_ENABLED = import.meta.env.VITE_USAGE_ENABLED === 'true'

function PartialBanner({ message }: { message: string }) {
  return (
    <Card className="px-5 py-4 flex items-start gap-3" style={{ borderLeft: '4px solid var(--color-amber)' }}>
      <IconAlertTriangle size={18} className="text-amber shrink-0 mt-0.5" />
      <div>
        <div className="text-sm font-semibold text-white">Usage data not yet available</div>
        <p className="text-xs text-secondary mt-0.5">{message}</p>
      </div>
    </Card>
  )
}

/**
 * Usage & billing (M-G3.12 — BUILD, WS-H dependency). Binds `GET /v1/usage`. Until
 * WS-H ships the endpoint returns 404/501 → render the fail-secure PARTIAL banner
 * (never fabricated numbers). `retry:false` so the unavailable state surfaces
 * immediately. Treats the response as untrusted data (all fields optional).
 */
export function UsagePage() {
  const query = useUsage()

  const status = query.error instanceof ApiException ? query.error.status : 0
  const notReady = query.isError && (status === 404 || status === 501)

  return (
    <div className="p-4 sm:p-6 lg:p-8">
      <PageHeader title="Usage & Billing" subtitle="Metered validations against your plan." />

      {query.isLoading ? (
        <LoadingState label="Loading usage…" />
      ) : notReady ? (
        <PartialBanner message="Metered usage ships with the billing rollup. No figures are shown until it is live — nothing here is fabricated." />
      ) : query.isError ? (
        <ErrorState error={query.error} onRetry={() => query.refetch()} />
      ) : (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-5">
          <Card className="p-5">
            <div className="text-[10px] uppercase tracking-[0.2em] text-muted">Validations</div>
            <div className="font-display text-2xl font-bold mt-2 font-mono">{formatNumber(query.data?.validations ?? null)}</div>
          </Card>
          <Card className="p-5">
            <div className="text-[10px] uppercase tracking-[0.2em] text-muted">Quota</div>
            <div className="font-display text-2xl font-bold mt-2 font-mono">{formatNumber(query.data?.quota ?? null)}</div>
          </Card>
          <Card className="p-5">
            <div className="text-[10px] uppercase tracking-[0.2em] text-muted">Blocks</div>
            <div className="font-display text-2xl font-bold mt-2 font-mono">{formatNumber(query.data?.blocks ?? null)}</div>
          </Card>
          <Card className="p-5">
            <div className="text-[10px] uppercase tracking-[0.2em] text-muted">Agents</div>
            <div className="font-display text-2xl font-bold mt-2 font-mono">{formatNumber(query.data?.agents ?? null)}</div>
          </Card>
        </div>
      )}
    </div>
  )
}
