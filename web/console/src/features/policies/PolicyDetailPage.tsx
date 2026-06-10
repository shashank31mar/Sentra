import { useMemo, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import {
  IconArrowLeft,
  IconBan,
  IconCircleCheck,
  IconCode,
  IconShieldLock,
  IconRobot,
} from '@tabler/icons-react'
import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { CodeBlock } from '../../components/ui/CodeBlock'
import { StatusDot } from '../../components/ui/StatusDot'
import { ErrorState, LoadingState } from '../../components/ui/states'
import { usePolicyDetail } from '../../lib/query/usePolicies'
import { ROUTES } from '../../app/routes'
import { formatDateTime, formatNumber } from '../../lib/format'
import {
  parseCedarElements,
  policyFilename,
  renderPolicy,
  type PolicyLang,
} from '../../lib/policyFormat'
import type { PolicyStatus } from '../../types/enums'

const POLICY_STATUS_COLOR: Partial<Record<PolicyStatus, string>> = {
  active: '#22E58B',
  disabled: '#51636E',
  draft: '#FFB020',
}

const LANGS: { id: PolicyLang; label: string }[] = [
  { id: 'cedar', label: 'CEDAR' },
  { id: 'json', label: 'JSON' },
  { id: 'yaml', label: 'YAML' },
]

function ElementRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5 px-4 py-3" style={{ borderTop: '1px solid var(--color-line)' }}>
      <span className="text-[10px] uppercase tracking-[0.2em] text-muted">{label}</span>
      {children}
    </div>
  )
}

export function PolicyDetailPage() {
  const { policyId = '' } = useParams()
  const navigate = useNavigate()
  const [lang, setLang] = useState<PolicyLang>('cedar')
  const detail = usePolicyDetail(policyId)

  const policy = detail.data?.policy
  const elements = useMemo(() => parseCedarElements(policy?.content), [policy?.content])
  const code = useMemo(() => (policy ? renderPolicy(policy, lang) : ''), [policy, lang])

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
        subtitle={`${policy.policy_id} · v${policy.version}`}
        actions={
          <span className="inline-flex items-center gap-2 text-xs font-mono capitalize" style={{ color: statusColor }}>
            <StatusDot color={statusColor} /> {policy.status ?? '—'}
          </span>
        }
      />

      <div className="grid gap-5 grid-cols-1 lg:grid-cols-3">
        {/* Source viewer with CEDAR / JSON / YAML tabs */}
        <div className="lg:col-span-2">
          <CodeBlock
            code={code}
            filename={policyFilename(policy.name, lang)}
            toolbar={
              <div className="ml-2 flex rounded-md p-0.5" style={{ background: 'rgba(0,0,0,0.4)' }}>
                {LANGS.map((l) => {
                  const active = l.id === lang
                  return (
                    <button
                      key={l.id}
                      type="button"
                      onClick={() => setLang(l.id)}
                      className={`px-3 py-1 rounded text-[10px] font-bold tracking-wide cursor-pointer transition-colors ${
                        active ? 'text-cyan bg-white/10' : 'text-muted hover:text-white'
                      }`}
                    >
                      {l.label}
                    </button>
                  )
                })}
              </div>
            }
          />
        </div>

        {/* Individual policy elements + metadata */}
        <div className="flex flex-col gap-5">
          <Card>
            <div className="flex items-center gap-2 px-4 py-3" style={{ borderBottom: '1px solid var(--color-line)' }}>
              <IconCode size={16} className="text-cyan" />
              <span className="text-sm font-medium uppercase tracking-[0.2em] text-secondary">Policy Elements</span>
            </div>

            <ElementRow label="Effect">
              {elements.effect === 'forbid' ? (
                <span className="inline-flex items-center gap-2 text-sm font-semibold text-pink">
                  <IconBan size={16} /> Forbid
                </span>
              ) : elements.effect === 'permit' ? (
                <span className="inline-flex items-center gap-2 text-sm font-semibold text-cyan">
                  <IconCircleCheck size={16} /> Permit
                </span>
              ) : (
                <span className="text-sm font-mono text-muted">—</span>
              )}
            </ElementRow>

            <ElementRow label="Principal">
              <span className="font-mono text-xs text-secondary break-words">{elements.principal ?? '—'}</span>
            </ElementRow>

            <ElementRow label="Action">
              <span className="font-mono text-xs text-secondary break-words">{elements.action ?? '—'}</span>
            </ElementRow>

            <ElementRow label="Resource">
              <span className="font-mono text-xs text-secondary break-words">{elements.resource ?? '—'}</span>
            </ElementRow>

            <ElementRow label="Conditions">
              {elements.conditions.length === 0 ? (
                <span className="text-xs font-mono text-muted">None</span>
              ) : (
                <div className="flex flex-col gap-1.5">
                  {elements.conditions.map((c, i) => (
                    <code
                      key={i}
                      className="font-mono text-[11px] text-amber px-2 py-1 rounded-md break-words"
                      style={{ background: 'rgba(255,176,32,0.08)' }}
                    >
                      {c}
                    </code>
                  ))}
                </div>
              )}
            </ElementRow>
          </Card>

          <Card className="p-5">
            <div className="flex items-center gap-2 mb-4">
              <IconShieldLock size={16} className="text-cyan" />
              <span className="text-sm font-medium uppercase tracking-[0.2em] text-secondary">Metadata</span>
            </div>
            <dl className="flex flex-col gap-3 text-sm">
              <div className="flex items-center justify-between gap-3">
                <dt className="text-xs uppercase tracking-wider text-muted">Version</dt>
                <dd className="font-mono text-secondary">v{policy.version}</dd>
              </div>
              <div className="flex items-center justify-between gap-3">
                <dt className="text-xs uppercase tracking-wider text-muted">Attached Agents</dt>
                <dd className="inline-flex items-center gap-1.5 font-mono text-secondary">
                  <IconRobot size={14} className="text-cyan" /> {formatNumber(policy.agent_count)}
                </dd>
              </div>
              <div className="flex items-center justify-between gap-3">
                <dt className="text-xs uppercase tracking-wider text-muted">Updated</dt>
                <dd className="font-mono text-muted">{formatDateTime(policy.updated_at)}</dd>
              </div>
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
