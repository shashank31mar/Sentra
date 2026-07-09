import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { IconChevronDown, IconChevronRight, IconShieldLock, IconToggleLeft, IconToggleRight, IconPlus } from '@tabler/icons-react'
import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { Button } from '../../components/ui/Button'
import { SegmentedControl } from '../../components/ui/SegmentedControl'
import { Table, TBody, Td, Th, THead, Tr } from '../../components/ui/Table'
import { EmptyState, ErrorState, LoadingState } from '../../components/ui/states'
import { ConfirmDialog } from '../../components/ui/ConfirmDialog'
import { useToast } from '../../components/ui/Toast'
import {
  usePolicies, useSigmaRules, useSigmaRuleContent, useToggleSigmaRule,
  useSetPolicyStatus, useDeletePolicy,
} from '../../lib/query/usePolicies'
import { useCan, usePlatformCan } from '../../lib/query/useMe'
import { isAuthDegrade403 } from '../../lib/degrade'
import { policyDetailPath, policyEditPath, policyNewPath } from '../../app/routes'
import { formatDateTime, formatNumber } from '../../lib/format'
import type { PolicySummary } from '../../types/api'
import type { PolicyStatus, MetricsRange } from '../../types/enums'

const POLICY_STATUS_COLOR: Partial<Record<PolicyStatus, string>> = {
  active: '#22E58B',
  disabled: '#51636E',
  draft: '#FFB020',
}

const SEVERITY_COLOR: Record<string, string> = {
  low: '#22E58B',
  medium: '#FFB020',
  high: '#FF9900',
  critical: '#FF0080',
}

const RANGES = [
  { value: '1h', label: '1H' },
  { value: '24h', label: '24H' },
  { value: '7d', label: '7D' },
  { value: '30d', label: '30D' },
] as const

export function PolicyLibraryPage() {
  const navigate = useNavigate()
  // Role-conditional rendering (LLD-26 WS-C C2): a viewer never sees write
  // controls. The server still authorizes every mutation (require_role) — this
  // gate is UX only, so a tampered client gains nothing.
  const can = useCan()
  // FX-1.1: the Sigma enable/disable toggle is a FLEET-GLOBAL kill-switch — the
  // server gates `PATCH /sigma-rules/{id}` on `require_platform`, so a tenant admin
  // must NOT see a control they can't use. Gated on `is_platform` (a PlatformCapability),
  // NOT a TenantRole — hence `usePlatformCan`, never `useCan`.
  const platformCan = usePlatformCan()
  const canRetireSigma = platformCan('sigma.retire')
  const policies = usePolicies()
  const [range, setRange] = useState<MetricsRange>('24h')
  const sigma = useSigmaRules({ range })
  const { success, error } = useToast()
  const setStatus = useSetPolicyStatus()
  const del = useDeletePolicy()
  // Pending confirm dialogs (disable + delete carry blast-radius copy).
  const [disableFor, setDisableFor] = useState<PolicySummary | null>(null)
  const [deleteFor, setDeleteFor] = useState<PolicySummary | null>(null)

  const onToggle = (p: PolicySummary) => {
    if (p.status === 'active') {
      setDisableFor(p) // disable needs confirm (blast radius)
      return
    }
    setStatus.mutate(
      { policyId: p.policy_id, status: 'active' },
      {
        onSuccess: () => success(`${p.name} enabled.`),
        // FXR-1: a 403 is surfaced once by the global bridge — skip the page toast.
        onError: (e) => { if (!isAuthDegrade403(e)) error('Could not enable the policy.') },
      },
    )
  }
  const confirmDisable = () => {
    if (!disableFor) return
    setStatus.mutate(
      { policyId: disableFor.policy_id, status: 'disabled' },
      {
        onSuccess: () => { success(`${disableFor.name} disabled.`); setDisableFor(null) },
        onError: (e) => { if (!isAuthDegrade403(e)) error('Could not disable the policy.') },
      },
    )
  }
  const confirmDelete = () => {
    if (!deleteFor) return
    del.mutate(deleteFor.policy_id, {
      onSuccess: () => { success(`${deleteFor.name} deleted (soft-disabled).`); setDeleteFor(null) },
      onError: (e) => { if (!isAuthDegrade403(e)) error('System policies can’t be deleted — disable instead.') },
    })
  }

  const policyItems = policies.data?.pages.flatMap((p) => p.items) ?? []
  const ruleItems = sigma.data?.pages.flatMap((p) => p.items) ?? []

  // Deep-link from Agent Inventory's clickable policy chips (?policy=<id>):
  // scroll the matching row into view and flash a highlight.
  const [params] = useSearchParams()
  const highlightId = params.get('policy')
  useEffect(() => {
    if (!highlightId || policyItems.length === 0) return
    const el = document.getElementById(`policy-row-${highlightId}`)
    el?.scrollIntoView({ behavior: 'smooth', block: 'center' })
  }, [highlightId, policyItems.length])

  return (
    <div className="p-4 sm:p-6 lg:p-8">
      <PageHeader title="Policy Library" subtitle="Agent policies and Sigma detection rules governing your fleet." />

      {/* Policies */}
      <Card className="mb-5">
        <div className="flex items-center justify-between px-6 py-4" style={{ borderBottom: '1px solid var(--color-line)' }}>
          <span className="text-sm font-medium uppercase tracking-[0.2em] text-secondary flex items-center gap-2">
            <IconShieldLock size={16} className="text-cyan" /> Policies
          </span>
          <div className="flex items-center gap-3">
            <span className="text-xs font-mono text-muted">{policies.data?.pages[0]?.total ?? 0} total</span>
            {can('policies.write') && (
              <Button variant="primary" onClick={() => navigate(policyNewPath())}>
                <IconPlus size={14} /> New Policy
              </Button>
            )}
          </div>
        </div>
        {policies.isLoading ? (
          <LoadingState />
        ) : policies.isError ? (
          <ErrorState error={policies.error} onRetry={() => policies.refetch()} />
        ) : policyItems.length === 0 ? (
          <EmptyState label="No policies yet" />
        ) : (
          <Table>
            <THead>
              <Th>Policy</Th>
              <Th>Status</Th>
              <Th className="text-right">Version</Th>
              <Th className="text-right">Agents</Th>
              <Th className="text-right">Updated</Th>
              <Th className="text-right">Actions</Th>
            </THead>
            <TBody>
              {policyItems.map((p) => {
                const isSystem = p.created_by === 'system'
                const isDisabled = p.status === 'disabled'
                const busy = setStatus.isPending || del.isPending
                return (
                  <Tr
                    key={p.policy_id}
                    id={`policy-row-${p.policy_id}`}
                    onClick={() => navigate(policyDetailPath(p.policy_id))}
                    className={`${p.policy_id === highlightId ? 'bg-cyan/10' : ''} ${isDisabled ? 'opacity-60' : ''}`}
                  >
                    <Td>
                      <div className="flex items-center gap-2">
                        <span className="font-display font-bold text-white">{p.name}</span>
                        {/* cedar-policy CT13b: migration-progress badge. */}
                        <span
                          className="inline-flex items-center px-1.5 h-4 rounded text-[9px] font-bold tracking-wide uppercase border"
                          style={
                            p.policy_format === 'cedar'
                              ? { color: '#0FFFFF', background: 'rgba(15,255,255,0.08)', borderColor: 'rgba(15,255,255,0.25)' }
                              : { color: '#8DA2AE', background: 'rgba(141,162,174,0.08)', borderColor: 'rgba(141,162,174,0.22)' }
                          }
                          title={p.policy_format === 'cedar' ? 'Cedar — compiled policy enforced' : 'Legacy structured (YAML)'}
                        >
                          {p.policy_format === 'cedar' ? 'Cedar' : 'YAML'}
                        </span>
                      </div>
                      <div className="text-[11px] font-mono text-muted">{p.policy_id}</div>
                    </Td>
                    <Td>
                      <span className="text-xs font-mono capitalize" style={{ color: POLICY_STATUS_COLOR[p.status] ?? '#8DA2AE' }}>{p.status ?? '—'}</span>
                    </Td>
                    <Td className="text-right font-mono text-secondary">v{p.version}</Td>
                    <Td className="text-right font-mono text-secondary">{formatNumber(p.agent_count)}</Td>
                    <Td className="text-right font-mono text-muted">{formatDateTime(p.updated_at)}</Td>
                    <Td className="text-right">
                      <div className="inline-flex items-center gap-1.5 justify-end">
                        {/* G2.2: Edit + Enable/Disable are editor-class writes
                            (server PUT / PATCH status) — gate under policies.write. */}
                        {can('policies.write') && (
                          <button
                            type="button"
                            disabled={busy}
                            onClick={(e) => { e.stopPropagation(); navigate(policyEditPath(p.policy_id)) }}
                            className="px-2 py-1 rounded-lg text-[11px] font-bold text-secondary bg-surface-2 hover:text-cyan transition-colors disabled:opacity-40"
                            style={{ border: '1px solid var(--color-line)' }}
                          >
                            Edit
                          </button>
                        )}
                        {can('policies.write') && (
                          <button
                            type="button"
                            disabled={busy}
                            onClick={(e) => { e.stopPropagation(); onToggle(p) }}
                            className="px-2 py-1 rounded-lg text-[11px] font-bold text-secondary bg-surface-2 hover:text-cyan transition-colors disabled:opacity-40"
                            style={{ border: '1px solid var(--color-line)' }}
                          >
                            {isDisabled ? 'Enable' : 'Disable'}
                          </button>
                        )}
                        {/* G2.2: Delete is admin-only (server DELETE /policies/{id});
                            NOT rendered for editor/viewer — hidden, not disabled. */}
                        {can('policies.delete') && (
                          <button
                            type="button"
                            disabled={busy || isSystem}
                            title={isSystem ? "System policies can't be deleted — disable instead." : 'Delete policy'}
                            onClick={(e) => { e.stopPropagation(); setDeleteFor(p) }}
                            className="px-2 py-1 rounded-lg text-[11px] font-bold text-pink bg-pink/10 border border-pink/20 hover:bg-pink/20 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                          >
                            Delete
                          </button>
                        )}
                      </div>
                    </Td>
                  </Tr>
                )
              })}
            </TBody>
          </Table>
        )}
      </Card>

      {/* Sigma rules */}
      <Card>
        <div className="flex items-center justify-between px-6 py-4" style={{ borderBottom: '1px solid var(--color-line)' }}>
          <span className="text-sm font-medium uppercase tracking-[0.2em] text-secondary">Sigma Detection Rules</span>
          <SegmentedControl options={RANGES} value={range} onChange={setRange} />
        </div>
        {sigma.isLoading ? (
          <LoadingState />
        ) : sigma.isError ? (
          <ErrorState error={sigma.error} onRetry={() => sigma.refetch()} />
        ) : ruleItems.length === 0 ? (
          <EmptyState label="No rules" />
        ) : (
          <Table>
            <THead>
              <Th />
              <Th>Rule</Th>
              <Th>Category</Th>
              <Th>Severity</Th>
              <Th className="text-right">Matches ({range})</Th>
              {canRetireSigma && <Th className="text-right">Enabled</Th>}
            </THead>
            <TBody>
              {ruleItems.map((r) => (
                <SigmaRuleRow key={r.rule_id} rule={r} canRetire={canRetireSigma} />
              ))}
            </TBody>
          </Table>
        )}
      </Card>

      <ConfirmDialog
        open={Boolean(disableFor)}
        title="Disable policy"
        variant="danger"
        confirmLabel="Disable"
        busy={setStatus.isPending}
        onCancel={() => setDisableFor(null)}
        onConfirm={confirmDisable}
        message={
          <>
            Disable <span className="font-mono text-ink">{disableFor?.name}</span>?{' '}
            <strong className="text-pink">Every agent bound to this policy will have all tool calls blocked</strong>{' '}
            until it is re-enabled. ({formatNumber(disableFor?.agent_count ?? 0)} agents bound.)
          </>
        }
      />

      <ConfirmDialog
        open={Boolean(deleteFor)}
        title="Delete policy"
        variant="danger"
        confirmLabel="Delete"
        busy={del.isPending}
        onCancel={() => setDeleteFor(null)}
        onConfirm={confirmDelete}
        message={
          <>
            Delete <span className="font-mono text-ink">{deleteFor?.name}</span>? It is soft-disabled —
            same blocking effect as Disable, and it stops appearing as active.
          </>
        }
      />
    </div>
  )
}

function SigmaRuleRow({ rule, canRetire }: { rule: import('../../types/api').SigmaRule; canRetire: boolean }) {
  const [open, setOpen] = useState(false)
  const toggle = useToggleSigmaRule()
  const content = useSigmaRuleContent(open ? rule.rule_id : null)
  const enabled = rule.status === 'enabled'
  // FX-1.1: the Enabled toggle column only renders for a platform operator
  // (`sigma.retire`). Non-platform operators see the read-only rule row without a
  // fleet-global kill-switch they can't use — so the expanded detail spans one
  // fewer column.
  const colCount = canRetire ? 6 : 5

  return (
    <>
      <Tr onClick={() => setOpen((v) => !v)}>
        <Td className="text-muted">
          {open ? <IconChevronDown size={16} className="inline" /> : <IconChevronRight size={16} className="inline" />}
        </Td>
        <Td className="font-medium text-white">{rule.title}</Td>
        <Td className="font-mono text-xs text-secondary">{rule.category}</Td>
        <Td>
          <span className="text-xs font-mono uppercase" style={{ color: SEVERITY_COLOR[rule.severity] ?? '#8DA2AE' }}>{rule.severity}</span>
        </Td>
        <Td className="text-right font-mono text-secondary">{formatNumber(rule.match_count)}</Td>
        {canRetire && (
          <Td className="text-right">
            <button
              type="button"
              className="cursor-pointer disabled:opacity-40"
              disabled={toggle.isPending}
              onClick={(e) => {
                e.stopPropagation()
                toggle.mutate({ ruleId: rule.rule_id, status: enabled ? 'disabled' : 'enabled' })
              }}
              title={enabled ? 'Disable rule' : 'Enable rule'}
            >
              {enabled ? <IconToggleRight size={26} className="text-cyan" /> : <IconToggleLeft size={26} className="text-muted" />}
            </button>
          </Td>
        )}
      </Tr>
      {open && (
        <Tr>
          <Td colSpan={colCount} style={{ background: 'rgba(0,0,0,0.25)' }}>
            {content.isLoading ? (
              <LoadingState label="Loading patterns…" />
            ) : content.isError ? (
              <ErrorState error={content.error} onRetry={() => content.refetch()} />
            ) : content.data ? (
              <div className="py-2">
                {content.data.description && (
                  <p className="text-xs text-secondary mb-3">{content.data.description}</p>
                )}
                <div className="flex flex-wrap gap-x-6 gap-y-1 text-[11px] font-mono text-muted mb-3">
                  <span>Patterns: <span className="text-secondary">{content.data.patterns_total}</span></span>
                  {content.data.condition && <span>Condition: <span className="text-secondary">{content.data.condition}</span></span>}
                  {content.data.tags?.length > 0 && (
                    <span>Tags: <span className="text-secondary">{content.data.tags.join(', ')}</span></span>
                  )}
                </div>
                <div className="space-y-3">
                  {content.data.selections.map((sel) => (
                    <div key={`${sel.name}-${sel.field}`}>
                      <div className="text-[11px] font-mono text-cyan mb-1">
                        {sel.name} <span className="text-muted">· {sel.field} ({sel.patterns.length})</span>
                      </div>
                      <div className="flex flex-wrap gap-1.5">
                        {sel.patterns.map((p, i) => (
                          <code
                            key={i}
                            className="text-[11px] px-1.5 py-0.5 rounded text-secondary"
                            style={{ background: 'rgba(255,255,255,0.05)', border: '1px solid var(--color-line)' }}
                          >
                            {p}
                          </code>
                        ))}
                      </div>
                    </div>
                  ))}
                  {content.data.selections.length === 0 && (
                    <p className="text-xs text-muted">No detection patterns available for this rule.</p>
                  )}
                </div>
              </div>
            ) : null}
          </Td>
        </Tr>
      )}
    </>
  )
}
