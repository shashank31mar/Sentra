import { useParams } from 'react-router-dom'
import { IconAlertTriangle, IconShieldCheck } from '@tabler/icons-react'
import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { Table, TBody, Td, Th, THead, Tr } from '../../components/ui/Table'
import { ErrorState, LoadingState } from '../../components/ui/states'
import { useTenantDetail } from '../../lib/query/usePlatform'
import { quotaHeadroom } from './fleetRank'
import { formatNumber, formatPercent } from '../../lib/format'
import { ApiException } from '../../lib/http'

/**
 * Audited per-tenant metadata drill-down (G4.6). Reads `:tenantId` → `GET
 * /v1/platform/tenants/{id}` (server dual-audits `_audit_platform_read` BEFORE
 * serving). Read-only: registry row + quota + consent state + member roster; NO
 * mutation control (no member add/remove, no consent toggle). Distinguishes:
 *   - 403 (consent required, PRE-G4-c enforced) → friendly consent panel, no retry;
 *   - 404 (tenant not found) → distinct not-found panel.
 * `useTenantDetail` sets `retry:false` so a 403 does not retry-storm the DENY audit.
 * Does NOT reach tenant data via `X-Aegion-Tenant` (that is the stricter forensic
 * break-glass path) — the metadata path param only.
 */
export function TenantDetailPage() {
  const { tenantId = '' } = useParams()
  const query = useTenantDetail(tenantId)

  if (query.isLoading) return <div className="p-8"><LoadingState label="Loading tenant…" /></div>

  if (query.isError) {
    const status = query.error instanceof ApiException ? query.error.status : 0
    if (status === 403) {
      return (
        <div className="p-4 sm:p-6 lg:p-8">
          <PageHeader title={tenantId} subtitle="Cross-tenant drill-down" />
          <Card className="p-8 flex flex-col items-center gap-3 text-center" accent="default">
            <IconAlertTriangle size={28} className="text-amber" />
            <h2 className="font-display text-lg font-bold text-white">Consent required</h2>
            <p className="text-sm text-secondary max-w-md">
              This tenant has not granted platform-read consent. Per-tenant detail is withheld until
              consent is granted. The fleet aggregate remains available.
            </p>
          </Card>
        </div>
      )
    }
    if (status === 404) {
      return (
        <div className="p-4 sm:p-6 lg:p-8">
          <PageHeader title={tenantId} subtitle="Cross-tenant drill-down" />
          <Card className="p-8 flex flex-col items-center gap-3 text-center">
            <IconAlertTriangle size={28} className="text-faint" />
            <h2 className="font-display text-lg font-bold text-white">Tenant not found</h2>
            <p className="text-sm text-secondary max-w-md">No tenant with id “{tenantId}”.</p>
          </Card>
        </div>
      )
    }
    return <div className="p-8"><ErrorState error={query.error} /></div>
  }

  const t = query.data
  if (!t) return null

  return (
    <div className="p-4 sm:p-6 lg:p-8">
      <PageHeader title={t.display_name} subtitle={`${t.tenant_id} · read-only`} />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <Card className="p-5 lg:col-span-2">
          <div className="text-[10px] uppercase tracking-[0.18em] text-muted mb-4">Registry</div>
          <dl className="grid grid-cols-2 gap-4 text-sm">
            <div><dt className="text-muted text-xs">Plan</dt><dd className="font-mono capitalize">{t.plan}</dd></div>
            <div><dt className="text-muted text-xs">Status</dt><dd className="font-mono capitalize">{t.status}</dd></div>
            <div><dt className="text-muted text-xs">Identity mode</dt><dd className="font-mono capitalize">{t.identity_mode}</dd></div>
            <div>
              <dt className="text-muted text-xs">Platform-read consent</dt>
              <dd className="font-mono flex items-center gap-1.5">
                {t.platform_read_consent ? (
                  <span className="text-green flex items-center gap-1.5"><IconShieldCheck size={14} /> granted</span>
                ) : (
                  <span className="text-amber">not granted</span>
                )}
              </dd>
            </div>
          </dl>
        </Card>

        <Card className="p-5">
          <div className="text-[10px] uppercase tracking-[0.18em] text-muted mb-3">Quota &amp; headroom</div>
          {(() => {
            // FX-3.6: surface the computed headroom (used vs limit) instead of dumping
            // raw JSON. `quotaHeadroom` narrows the one quota key it reads and treats
            // anything non-numeric/absent as "unknown" — never fabricates a number.
            const hr = quotaHeadroom({ decisions_24h: t.decisions_24h }, t.quota)
            return (
              <dl className="flex flex-col gap-3 text-sm">
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-xs uppercase tracking-wider text-muted">Validations (24h)</dt>
                  <dd className="font-mono text-secondary">{hr.used === null ? '—' : formatNumber(hr.used)}</dd>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-xs uppercase tracking-wider text-muted">Monthly limit</dt>
                  <dd className="font-mono text-secondary">{hr.limit === null ? '—' : formatNumber(hr.limit)}</dd>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <dt className="text-xs uppercase tracking-wider text-muted">Headroom used</dt>
                  <dd
                    className="font-mono"
                    style={{ color: hr.known && hr.usedPct! >= 80 ? '#FF0080' : '#8DA2AE' }}
                  >
                    {hr.known ? formatPercent(hr.usedPct) : 'unknown'}
                  </dd>
                </div>
              </dl>
            )
          })()}
        </Card>
      </div>

      <Card className="mt-5">
        <div className="px-6 py-4" style={{ borderBottom: '1px solid var(--color-line)' }}>
          <span className="text-sm font-medium uppercase tracking-[0.2em] text-secondary">Members</span>
        </div>
        <Table>
          <THead>
            <Th>Operator</Th>
            <Th>Role</Th>
          </THead>
          <TBody>
            {(t.members ?? []).map((m) => (
              <Tr key={m.operator_sub}>
                <Td className="font-mono text-xs text-secondary">{m.operator_sub}</Td>
                <Td className="font-mono text-xs capitalize text-secondary">{m.role}</Td>
              </Tr>
            ))}
          </TBody>
        </Table>
      </Card>
    </div>
  )
}
