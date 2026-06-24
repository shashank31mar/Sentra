import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'
import { Table, TBody, Td, Th, THead, Tr } from '../../components/ui/Table'
import { StatusDot } from '../../components/ui/StatusDot'
import { EmptyState, ErrorState, LoadingState } from '../../components/ui/states'
import { useResidualAgents } from '../../lib/query/useResidualAgents'
import { formatRelativeFromMs } from '../../lib/format'

const ACTIVE_COLOR = '#22E58B'
const EXPIRED_COLOR = '#FF0080'

export function ResidualAgentsPage() {
  const query = useResidualAgents()
  const residual = query.data?.residual_agents ?? []

  return (
    <div className="p-4 sm:p-6 lg:p-8">
      <PageHeader
        title="Residual Agents"
        subtitle="Uncredentialed agents riding the legacy fallback window. Onboard or retire them before the window closes — once it expires their tool calls are denied."
      />

      <Card>
        <div
          className="flex items-center justify-between px-6 py-4"
          style={{ borderBottom: '1px solid var(--color-line)' }}
        >
          <span className="text-sm font-medium uppercase tracking-[0.2em] text-secondary">
            On Fallback Window
          </span>
          <span className="text-xs font-mono text-muted">{query.data?.count ?? 0} agents</span>
        </div>

        {query.isLoading ? (
          <LoadingState />
        ) : query.isError ? (
          <ErrorState error={query.error} onRetry={() => query.refetch()} />
        ) : residual.length === 0 ? (
          <EmptyState label="No residual agents — every enforced agent has a credential." />
        ) : (
          <Table>
            <THead>
              <Th>Agent</Th>
              <Th>Tenant</Th>
              <Th className="text-right">First seen</Th>
              <Th className="text-right">Window {/* deadline */}</Th>
              <Th className="text-right">Status</Th>
            </THead>
            <TBody>
              {residual.map((a) => (
                <Tr key={a.agent_id}>
                  <Td>
                    <div className="font-mono text-sm text-white">{a.agent_id}</div>
                  </Td>
                  <Td className="font-mono text-xs text-secondary">{a.tenant_id}</Td>
                  <Td className="text-right font-mono text-muted">
                    {formatRelativeFromMs(a.first_seen_ms)}
                  </Td>
                  <Td className="text-right font-mono text-secondary">
                    {a.expired ? 'lapsed' : formatRelativeFromMs(a.deadline_ms)}
                  </Td>
                  <Td className="text-right">
                    <span className="inline-flex items-center gap-2 text-xs font-mono">
                      <StatusDot color={a.expired ? EXPIRED_COLOR : ACTIVE_COLOR} />
                      <span style={{ color: a.expired ? EXPIRED_COLOR : ACTIVE_COLOR }}>
                        {a.expired ? 'Expired — denied' : 'Active'}
                      </span>
                    </span>
                  </Td>
                </Tr>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    </div>
  )
}
