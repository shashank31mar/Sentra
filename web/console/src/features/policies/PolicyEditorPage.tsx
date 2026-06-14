import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { Button } from '../../components/ui/Button'
import { LoadingState } from '../../components/ui/states'
import { useToast } from '../../components/ui/Toast'
import { usePolicyDetail, useCreatePolicy, useUpdatePolicy } from '../../lib/query/usePolicies'
import { agentsApi } from '../../lib/api/agents'
import { policyDetailPath } from '../../app/routes'
import { renderCedar, toYaml } from '../../lib/policyFormat'
import { ApiException } from '../../lib/http'
import type { PolicyCreateRequest, PolicyDetailView, PolicyRuleRequest } from '../../types/api'

/** A valid starter document so a new policy is editable immediately. */
const CREATE_SKELETON = JSON.stringify(
  {
    allowed_tools: ['query_orders'],
    policies: [
      { policy_id: 'rule-1', name: 'Example rule', severity: 'medium', action: 'ALLOW' },
    ],
    max_calls_per_minute: 30,
  },
  null,
  2,
)

/** Reconstruct the editable document body from a loaded policy (strip the
 *  server-owned envelope — agent-policy-management §6.3). */
function bodyFromDetail(d: PolicyDetailView): string {
  const doc: Record<string, unknown> = {
    allowed_tools: d.allowed_tools,
    policies: d.rules,
  }
  if (d.platform) doc.platform = d.platform
  if (d.cloud_region) doc.cloud_region = d.cloud_region
  if (d.max_calls_per_minute != null) doc.max_calls_per_minute = d.max_calls_per_minute
  if (d.cross_cloud_dependencies.length) doc.cross_cloud_dependencies = d.cross_cloud_dependencies
  return JSON.stringify(doc, null, 2)
}

export function PolicyEditorPage() {
  const navigate = useNavigate()
  const { policyId } = useParams<{ policyId: string }>()
  const [params] = useSearchParams()
  const { success } = useToast()
  const isEdit = Boolean(policyId)

  const detail = usePolicyDetail(policyId ?? '')
  const create = useCreatePolicy()
  const update = useUpdatePolicy(policyId ?? '')

  // Create-from-inventory prefill + auto-attach (§6.1).
  const prefillAgent = params.get('agent_id') ?? ''
  const autoAttach = params.get('attach') === '1'

  // Form state — initialized once from the loaded detail (edit) or prefill (create).
  const [name, setName] = useState('')
  const [agentId, setAgentId] = useState(prefillAgent)
  const [version, setVersion] = useState('1.0.0')
  const [bodyText, setBodyText] = useState(CREATE_SKELETON)
  const [banner, setBanner] = useState<{ kind: 'error' | 'info'; msg: string; link?: string } | null>(null)

  // Seed the form from the loaded policy exactly once — when the detail first
  // arrives. A ref guard (not state) avoids clobbering the operator's in-progress
  // edits on a background refetch, and keeps seeding out of the render body.
  const seededRef = useRef(false)
  useEffect(() => {
    if (isEdit && !seededRef.current && detail.data) {
      seededRef.current = true
      setName(detail.data.name)
      setAgentId(detail.data.agent_id ?? '')
      setVersion(detail.data.version || '1.0.0')
      setBodyText(bodyFromDetail(detail.data))
    }
  }, [isEdit, detail.data])

  const parsed = useMemo(() => {
    try {
      return { ok: true as const, doc: JSON.parse(bodyText) as Record<string, unknown> }
    } catch (e) {
      return { ok: false as const, err: (e as Error).message }
    }
  }, [bodyText])

  const yamlPreview = useMemo(() => (parsed.ok ? toYaml(parsed.doc) : ''), [parsed])

  // cedar-policy CT13: read-only generated-Cedar preview, projected live from the
  // structured fields. The structured form stays the ONLY editor (single source of
  // truth, Kiro #6) — raw Cedar is never editable; this panel just shows the
  // operator the Cedar their policy maps to.
  const cedarPreview = useMemo(() => {
    if (!parsed.ok) return ''
    const d = parsed.doc as Record<string, unknown>
    const arr = <T,>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : [])
    const num = (v: unknown) => (typeof v === 'number' ? v : null)
    return renderCedar({
      policy_id: '(preview)', name, version, agent_id: agentId || null,
      allowed_tools: arr<string>(d.allowed_tools),
      allowed_agents: arr<string>(d.allowed_agents),
      rules: arr(d.policies),
      cross_cloud_dependencies: arr(d.cross_cloud_dependencies),
      max_calls_per_minute: num(d.max_calls_per_minute),
      max_refund_amount: num(d.max_refund_amount),
      status: 'active', platform: null, cloud_region: null, schema_version: null,
      created_by: null, updated_at: null, content_hash: null, s3_key: null,
      match_count_24h: null, content: null,
      policy_format: 'cedar', cedar_content: null, generator_version: null,
    } as PolicyDetailView)
  }, [parsed, name, agentId, version])

  const isDisabledPolicy = isEdit && detail.data?.status === 'disabled'

  const clientErrors = (): string[] => {
    const errs: string[] = []
    if (!name.trim()) errs.push('Name is required.')
    if (!agentId.trim()) errs.push('Agent ID is required.')
    if (!isEdit && !/^\d+\.\d+\.\d+$/.test(version.trim())) errs.push('Version must be semver (e.g. 1.0.0).')
    if (!parsed.ok) { errs.push('Document is not valid JSON.'); return errs }
    const doc = parsed.doc
    const tools = doc.allowed_tools
    if (!Array.isArray(tools) || tools.length === 0 || !tools.every((t) => typeof t === 'string')) {
      errs.push('allowed_tools must be a non-empty array of strings.')
    }
    const rules = doc.policies as unknown
    if (!Array.isArray(rules) || rules.length === 0) {
      errs.push('policies must contain at least one rule.')
    } else {
      const ids = new Set<string>()
      for (const r of rules as PolicyRuleRequest[]) {
        if (!r || !r.policy_id || !r.severity) { errs.push('Each rule needs a policy_id and severity.'); break }
        if (ids.has(r.policy_id)) { errs.push(`Duplicate rule policy_id: ${r.policy_id}.`); break }
        ids.add(r.policy_id)
      }
    }
    return errs
  }

  const handleApiError = (e: unknown) => {
    if (e instanceof ApiException) {
      if (e.status === 409) {
        setBanner({ kind: 'error', msg: 'A policy for this agent already exists. Edit it instead.' })
        return
      }
      if (e.status === 403) {
        setBanner({ kind: 'error', msg: 'This policy is disabled. Enable it first.' })
        return
      }
      setBanner({ kind: 'error', msg: e.message || 'The server rejected the policy.' })
      return
    }
    setBanner({ kind: 'error', msg: 'Something went wrong. Please try again.' })
  }

  const onSubmit = () => {
    setBanner(null)
    const errs = clientErrors()
    if (errs.length) { setBanner({ kind: 'error', msg: errs.join(' ') }); return }
    const doc = (parsed as { doc: Record<string, unknown> }).doc

    if (isEdit) {
      const body = { schema_version: 'v1' as const, agent_id: agentId, name, ...doc } as Omit<PolicyCreateRequest, 'version'>
      update.mutate(body, {
        onSuccess: () => { success(`${name} updated.`); navigate(policyDetailPath(policyId!)) },
        onError: handleApiError,
      })
      return
    }

    const body = { schema_version: 'v1' as const, agent_id: agentId, name, version, ...doc } as PolicyCreateRequest
    create.mutate(body, {
      onSuccess: async (res) => {
        if (autoAttach && agentId) {
          try {
            await agentsApi.attachPolicy(agentId, res.policy_id)
            success(`${name} created and attached to ${agentId}.`)
          } catch {
            success(`${name} created. Attach it from Agent Inventory.`)
          }
        } else {
          success(`${name} created.`)
        }
        navigate(policyDetailPath(res.policy_id))
      },
      onError: handleApiError,
    })
  }

  const busy = create.isPending || update.isPending
  if (isEdit && detail.isLoading) return <div className="p-8"><Card className="p-6"><LoadingState /></Card></div>

  return (
    <div className="p-4 sm:p-6 lg:p-8 max-w-5xl">
      <PageHeader
        title={isEdit ? `Edit policy` : 'New policy'}
        subtitle={isEdit ? policyId : 'Create a policy, then attach it to an agent from Agent Inventory.'}
      />

      {banner && (
        <div className={`mb-4 rounded-xl border px-4 py-3 text-xs ${banner.kind === 'error' ? 'border-pink/30 text-pink bg-pink/5' : 'border-cyan/30 text-cyan bg-cyan/5'}`}>
          {banner.msg}
        </div>
      )}

      {isEdit && (
        <div className="mb-4 rounded-xl border border-amber-500/30 bg-amber-500/5 px-4 py-3 text-xs text-amber-300">
          Editing changes the <strong>shared</strong> policy for <strong>every agent bound to it</strong>, not just one.
        </div>
      )}

      {isDisabledPolicy && (
        <div className="mb-4 rounded-xl border border-pink/30 bg-pink/5 px-4 py-3 text-xs text-pink">
          This policy is disabled. Enable it first to save edits.
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Card className="p-5 space-y-4">
          <Field label="Name">
            <input value={name} onChange={(e) => setName(e.target.value)} className={inputCls} style={lineStyle} placeholder="payments-guardrails" />
          </Field>
          <Field label="Agent ID" hint={isEdit ? 'Read-only — a policy is authored for one agent.' : undefined}>
            <input value={agentId} onChange={(e) => setAgentId(e.target.value)} readOnly={isEdit} className={`${inputCls} ${isEdit ? 'opacity-60' : ''}`} style={lineStyle} placeholder="payment-agent" />
          </Field>
          <Field label="Version" hint={isEdit ? `current ${version} → bumps on save` : 'semver, e.g. 1.0.0'}>
            <input value={version} onChange={(e) => setVersion(e.target.value)} readOnly={isEdit} className={`${inputCls} ${isEdit ? 'opacity-60' : ''}`} style={lineStyle} />
          </Field>

          <Field label="Document (JSON)" hint="allowed_tools (≥1), policies (≥1 rule), optional platform / cloud_region / max_calls_per_minute / cross_cloud_dependencies.">
            <textarea
              value={bodyText}
              onChange={(e) => setBodyText(e.target.value)}
              spellCheck={false}
              className="w-full h-72 rounded-xl bg-surface-2 border px-3 py-2 font-mono text-[12px] text-ink scrollbar-thin"
              style={{ borderColor: 'var(--color-line)' }}
            />
            <div className={`mt-1 text-[11px] font-mono ${parsed.ok ? 'text-cyan' : 'text-pink'}`}>
              {parsed.ok ? 'JSON valid' : `JSON error: ${parsed.err}`}
            </div>
          </Field>

          <div className="flex items-center gap-2 pt-1">
            <Button variant="primary" onClick={onSubmit} disabled={busy || isDisabledPolicy || !parsed.ok}>
              {busy ? 'Saving…' : isEdit ? 'Save changes' : 'Create policy'}
            </Button>
            <Button variant="ghost" onClick={() => navigate(-1)} disabled={busy}>Cancel</Button>
          </div>
        </Card>

        <Card className="p-5">
          <div className="text-[11px] uppercase tracking-[0.2em] text-secondary mb-2">YAML preview</div>
          <pre className="text-[12px] font-mono text-secondary whitespace-pre-wrap leading-relaxed max-h-[16rem] overflow-y-auto scrollbar-thin">
            {parsed.ok ? yamlPreview : '# Fix the JSON to preview'}
          </pre>
          <div className="mt-4 flex items-center gap-2">
            <span className="text-[11px] uppercase tracking-[0.2em] text-secondary">Generated Cedar</span>
            <span className="text-[9px] font-bold uppercase tracking-wide text-muted px-1.5 h-4 inline-flex items-center rounded border" style={lineStyle}>read-only</span>
          </div>
          <pre className="mt-2 text-[12px] font-mono text-secondary whitespace-pre-wrap leading-relaxed max-h-[16rem] overflow-y-auto scrollbar-thin">
            {parsed.ok ? cedarPreview : '# Fix the JSON to preview'}
          </pre>
        </Card>
      </div>
    </div>
  )
}

const inputCls = 'w-full rounded-xl bg-surface-2 border px-3 h-9 text-sm text-ink'
const lineStyle = { borderColor: 'var(--color-line)' } as const

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <div className="text-[11px] uppercase tracking-[0.15em] text-secondary mb-1">{label}</div>
      {children}
      {hint && <div className="mt-1 text-[11px] text-muted">{hint}</div>}
    </label>
  )
}
