import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  IconArrowLeft,
  IconArrowRight,
  IconCode,
  IconShieldLock,
  IconRobot,
  IconTool,
} from '@tabler/icons-react'
import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { CodeBlock } from '../../components/ui/CodeBlock'
import { StatusDot } from '../../components/ui/StatusDot'
import { ErrorState, LoadingState } from '../../components/ui/states'
import { usePolicyDetail } from '../../lib/query/usePolicies'
import { ROUTES } from '../../app/routes'
import { formatDateTime } from '../../lib/format'
import { policyFilename, renderContent, type PolicyLang } from '../../lib/policyFormat'
import type { PolicyStatus } from '../../types/enums'

const POLICY_STATUS_COLOR: Partial<Record<PolicyStatus, string>> = {
  active: '#22E58B',
  disabled: '#51636E',
  draft: '#FFB020',
}

const SEVERITY_COLOR: Record<string, string> = {
  critical: '#FF0080',
  high: '#FF0080',
  medium: '#FFB020',
  low: '#8DA2AE',
}

const LANGS: { id: PolicyLang; label: string }[] = [
  { id: 'yaml', label: 'YAML' },
  { id: 'json', label: 'JSON' },
]

function Section({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <Card>
      <div className="flex items-center gap-2 px-4 py-3" style={{ borderBottom: '1px solid var(--color-line)' }}>
        {icon}
        <span className="text-sm font-medium uppercase tracking-[0.2em] text-secondary">{title}</span>
      </div>
      {children}
    </Card>
  )
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5 px-4 py-3" style={{ borderTop: '1px solid var(--color-line)' }}>
      <span className="text-[10px] uppercase tracking-[0.2em] text-muted">{label}</span>
      {children}
    </div>
  )
}

function MetaRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <dt className="text-xs uppercase tracking-wider text-muted shrink-0">{label}</dt>
      <dd className="font-mono text-secondary text-right break-all">{children}</dd>
    </div>
  )
}

export function PolicyDetailPage() {
  const { policyId = '' } = useParams()
  const navigate = useNavigate()
  const [lang, setLang] = useState<PolicyLang>('yaml')
  const detail = usePolicyDetail(policyId)

  const policy = detail.data
  const code = useMemo(() => (policy ? renderContent(policy.content, lang) : ''), [policy, lang])

  if (detail.isLoading) return <div className="p-8"><Card className="p-6"><LoadingState /></Card></div>
  if (detail.isError || !policy)
    return <div className="p-8"><Card className="p-6"><ErrorState error={detail.error} onRetry={() => detail.refetch()} /></Card></div>

  const statusColor = POLICY_STATUS_COLOR[policy.status] ?? '#8DA2AE'

  return (
    <div className="p-4 sm:p-6 lg:p-8">
      <button
        type="button"
        onClick={() => navigate(ROUTES.policies)}
        className="mb-5 inline-flex items-center gap-2 text-xs font-mono text-secondary hover:text-cyan transition-colors cursor-pointer"
      >
        <IconArrowLeft size={14} /> Policy Library
      </button>

      <PageHeader
        title={policy.name}
        subtitle={`${policy.policy_id} · v${policy.version}${policy.platform ? ` · ${policy.platform}` : ''}`}
        actions={
          <span className="inline-flex items-center gap-2 text-xs font-mono capitalize" style={{ color: statusColor }}>
            <StatusDot color={statusColor} /> {policy.status ?? '—'}
          </span>
        }
      />

      <div className="grid gap-5 grid-cols-1 lg:grid-cols-3">
        {/* Source viewer (YAML / JSON of the real policy content) */}
        <div className="lg:col-span-2 flex flex-col gap-5">
          <CodeBlock
            code={code}
            filename={policyFilename(policy.name, lang)}
            toolbar={
              <div className="ml-2 flex rounded-md p-0.5" style={{ background: 'rgba(0,0,0,0.4)' }}>
                {LANGS.map((l) => (
                  <button
                    key={l.id}
                    type="button"
                    onClick={() => setLang(l.id)}
                    className={`px-3 py-1 rounded text-[10px] font-bold tracking-wide cursor-pointer transition-colors ${
                      l.id === lang ? 'text-cyan bg-white/10' : 'text-muted hover:text-white'
                    }`}
                  >
                    {l.label}
                  </button>
                ))}
              </div>
            }
          />

          {/* Cross-cloud dependencies — the marquee enforcement */}
          {policy.cross_cloud_dependencies.length > 0 && (
            <Section icon={<IconArrowRight size={16} className="text-pink" />} title="Cross-Cloud Preconditions">
              {policy.cross_cloud_dependencies.map((d, i) => (
                <Row key={i} label={`required before ${(d.required_before ?? []).join(', ') || '—'}`}>
                  <span className="font-mono text-xs text-secondary">
                    must call <span className="text-cyan">{d.target_agent}</span>.
                    <span className="text-cyan">{d.target_tool}</span>
                    {typeof d.max_age_seconds === 'number' && (
                      <span className="text-muted"> within {d.max_age_seconds}s (same session)</span>
                    )}
                  </span>
                </Row>
              ))}
            </Section>
          )}

          {/* Inner rules */}
          {policy.rules.length > 0 && (
            <Section icon={<IconShieldLock size={16} className="text-cyan" />} title={`Rules (${policy.rules.length})`}>
              {policy.rules.map((r, i) => (
                <Row key={r.policy_id ?? i} label={r.policy_id ?? `rule-${i}`}>
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-semibold text-sm text-white">{r.name ?? '—'}</span>
                    {r.action && (
                      <span className="text-[10px] font-mono uppercase px-2 py-0.5 rounded"
                        style={{ color: r.action === 'DENY' ? '#FF0080' : '#22E58B', background: r.action === 'DENY' ? 'rgba(255,0,128,0.1)' : 'rgba(34,229,139,0.1)' }}>
                        {r.action}
                      </span>
                    )}
                    {r.severity && (
                      <span className="text-[10px] font-mono uppercase" style={{ color: SEVERITY_COLOR[r.severity] ?? '#8DA2AE' }}>
                        {r.severity}
                      </span>
                    )}
                    {r.enabled === false && <span className="text-[10px] font-mono uppercase text-muted">disabled</span>}
                  </div>
                  {r.description && <div className="text-xs text-muted mt-1">{r.description}</div>}
                </Row>
              ))}
            </Section>
          )}
        </div>

        {/* Policy elements + metadata */}
        <div className="flex flex-col gap-5">
          <Section icon={<IconCode size={16} className="text-cyan" />} title="Policy Elements">
            <Row label="Agent">
              <span className="inline-flex items-center gap-1.5 font-mono text-xs text-secondary">
                <IconRobot size={14} className="text-cyan" /> {policy.agent_id ?? '—'}
              </span>
            </Row>
            <Row label="Platform / Region">
              <span className="font-mono text-xs text-secondary">
                {policy.platform ?? '—'}{policy.cloud_region ? ` · ${policy.cloud_region}` : ''}
              </span>
            </Row>
            <Row label={`Allowed Tools (${policy.allowed_tools.length})`}>
              {policy.allowed_tools.length === 0 ? (
                <span className="text-xs font-mono text-muted">—</span>
              ) : (
                <div className="flex flex-wrap gap-1.5">
                  {policy.allowed_tools.map((t) => (
                    <span key={t} className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-mono text-cyan bg-cyan/10 border border-cyan/20">
                      <IconTool size={11} /> {t}
                    </span>
                  ))}
                </div>
              )}
            </Row>
            <Row label="Rate Limit">
              <span className="font-mono text-xs text-secondary">
                {policy.max_calls_per_minute != null ? `${policy.max_calls_per_minute} calls / min` : '—'}
              </span>
            </Row>
            <Row label="Cross-Cloud Preconditions">
              <span className="font-mono text-xs text-secondary">
                {policy.cross_cloud_dependencies.length || 'none'}
              </span>
            </Row>
          </Section>

          <Card className="p-5">
            <div className="flex items-center gap-2 mb-4">
              <IconShieldLock size={16} className="text-cyan" />
              <span className="text-sm font-medium uppercase tracking-[0.2em] text-secondary">Metadata</span>
            </div>
            <dl className="flex flex-col gap-3 text-sm">
              <MetaRow label="Version">v{policy.version || '—'}</MetaRow>
              <MetaRow label="Schema">{policy.schema_version ?? '—'}</MetaRow>
              <MetaRow label="Created by">{policy.created_by ?? '—'}</MetaRow>
              <MetaRow label="Updated">{policy.updated_at ? formatDateTime(policy.updated_at) : '—'}</MetaRow>
              <MetaRow label="Matches (24h)">{policy.match_count_24h ?? 0}</MetaRow>
              {policy.content_hash && (
                <div className="flex flex-col gap-1">
                  <dt className="text-xs uppercase tracking-wider text-muted">Content Hash</dt>
                  <dd className="font-mono text-[11px] text-secondary break-all">{policy.content_hash}</dd>
                </div>
              )}
              {policy.s3_key && (
                <div className="flex flex-col gap-1">
                  <dt className="text-xs uppercase tracking-wider text-muted">S3 Key</dt>
                  <dd className="font-mono text-[11px] text-secondary break-all">{policy.s3_key}</dd>
                </div>
              )}
            </dl>
          </Card>
        </div>
      </div>
    </div>
  )
}
