import { IconShieldLock, IconToggleLeft, IconToggleRight } from '@tabler/icons-react'
import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { Table, TBody, Td, Th, THead, Tr } from '../../components/ui/Table'
import { EmptyState, ErrorState, LoadingState } from '../../components/ui/states'
import { usePolicies, useSigmaRules, useToggleSigmaRule } from '../../lib/query/usePolicies'
import { formatDateTime, formatNumber } from '../../lib/format'
import type { PolicyStatus } from '../../types/enums'

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

export function PolicyLibraryPage() {
  const policies = usePolicies()
  const sigma = useSigmaRules()
  const toggle = useToggleSigmaRule()

  const policyItems = policies.data?.pages.flatMap((p) => p.items) ?? []
  const ruleItems = sigma.data?.pages.flatMap((p) => p.items) ?? []

  return (
    <div className="p-4 sm:p-6 lg:p-8">
      <PageHeader title="Policy Library" subtitle="Cedar policies and Sigma detection rules governing your fleet." />

      {/* Policies */}
      <Card className="mb-5">
        <div className="flex items-center justify-between px-6 py-4" style={{ borderBottom: '1px solid var(--color-line)' }}>
          <span className="text-sm font-medium uppercase tracking-[0.2em] text-secondary flex items-center gap-2">
            <IconShieldLock size={16} className="text-cyan" /> Policies
          </span>
          <span className="text-xs font-mono text-muted">{policies.data?.pages[0]?.total ?? 0} total</span>
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
            </THead>
            <TBody>
              {policyItems.map((p) => (
                <Tr key={p.policy_id}>
                  <Td>
                    <div className="font-display font-bold text-white">{p.name}</div>
                    <div className="text-[11px] font-mono text-muted">{p.policy_id}</div>
                  </Td>
                  <Td>
                    <span className="text-xs font-mono capitalize" style={{ color: POLICY_STATUS_COLOR[p.status] ?? '#8DA2AE' }}>{p.status ?? '—'}</span>
                  </Td>
                  <Td className="text-right font-mono text-secondary">v{p.version}</Td>
                  <Td className="text-right font-mono text-secondary">{formatNumber(p.agent_count)}</Td>
                  <Td className="text-right font-mono text-muted">{formatDateTime(p.updated_at)}</Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>

      {/* Sigma rules */}
      <Card>
        <div className="flex items-center justify-between px-6 py-4" style={{ borderBottom: '1px solid var(--color-line)' }}>
          <span className="text-sm font-medium uppercase tracking-[0.2em] text-secondary">Sigma Detection Rules</span>
        </div>
        {sigma.isLoading ? (
          <LoadingState />
        ) : ruleItems.length === 0 ? (
          <EmptyState label="No rules" />
        ) : (
          <Table>
            <THead>
              <Th>Rule</Th>
              <Th>Category</Th>
              <Th>Severity</Th>
              <Th className="text-right">Matches</Th>
              <Th className="text-right">Enabled</Th>
            </THead>
            <TBody>
              {ruleItems.map((r) => {
                const enabled = r.status === 'enabled'
                return (
                  <Tr key={r.rule_id}>
                    <Td className="font-medium text-white">{r.title}</Td>
                    <Td className="font-mono text-xs text-secondary">{r.category}</Td>
                    <Td>
                      <span className="text-xs font-mono uppercase" style={{ color: SEVERITY_COLOR[r.severity] ?? '#8DA2AE' }}>{r.severity}</span>
                    </Td>
                    <Td className="text-right font-mono text-secondary">{formatNumber(r.match_count)}</Td>
                    <Td className="text-right">
                      <button
                        type="button"
                        className="cursor-pointer disabled:opacity-40"
                        disabled={toggle.isPending}
                        onClick={() => toggle.mutate({ ruleId: r.rule_id, status: enabled ? 'disabled' : 'enabled' })}
                        title={enabled ? 'Disable rule' : 'Enable rule'}
                      >
                        {enabled ? <IconToggleRight size={26} className="text-cyan" /> : <IconToggleLeft size={26} className="text-muted" />}
                      </button>
                    </Td>
                  </Tr>
                )
              })}
            </TBody>
          </Table>
        )}
      </Card>
    </div>
  )
}
