import { useNavigate } from 'react-router-dom'
import { IconRefresh } from '@tabler/icons-react'
import { Card } from '../../components/ui/Card'
import { StatusDot } from '../../components/ui/StatusDot'
import { CloudBadge, DecisionBadge } from '../../components/ui/badges'
import { EmptyState, LoadingState } from '../../components/ui/states'
import { ROUTES } from '../../app/routes'
import { formatRelativeTime } from '../../lib/format'
import type { DecisionItem } from '../../types/api'

function FeedRow({ item, onClick }: { item: DecisionItem; onClick: () => void }) {
  const blocked = item.decision === 'DENY'
  const color = blocked ? '#FF0080' : '#0FFFFF'
  return (
    <button
      type="button"
      onClick={onClick}
      className="feed-row w-full text-left px-6 py-4 flex items-start gap-4 border-l-2 transition-colors"
      style={{ borderLeftColor: color }}
    >
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <DecisionBadge decision={item.decision} />
          <span className="text-sm font-mono font-bold truncate">{item.agent_name}</span>
        </div>
        <div className="text-xs mt-1 text-secondary truncate">{item.reason ?? item.tool_name ?? '—'}</div>
      </div>
      <div className="text-right shrink-0">
        <CloudBadge provider={item.cloud_provider} />
        <div className="text-[10px] mt-1.5 font-mono text-muted">{formatRelativeTime(item.timestamp)}</div>
      </div>
    </button>
  )
}

export function LiveActivity({
  items,
  isLoading,
  isFetching = false,
  onRefresh,
}: {
  items: DecisionItem[]
  isLoading: boolean
  isFetching?: boolean
  onRefresh?: () => void
}) {
  const navigate = useNavigate()
  return (
    <Card className="flex flex-col overflow-hidden" style={{ maxHeight: 420 }}>
      <div className="flex items-center justify-between px-6 py-5 bg-white/[0.01]" style={{ borderBottom: '1px solid var(--color-line)' }}>
        <h3 className="font-display text-lg font-bold tracking-tight flex items-center gap-2.5">
          Recent Activity <StatusDot color="#0FFFFF" pulse />
        </h3>
        <div className="flex items-center gap-3">
          {/* FX-3.2: data is a 15s TanStack poll, not a push stream — label it honestly. */}
          <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-muted">near-real-time (≤15s pull)</span>
          {onRefresh && (
            <button
              type="button"
              onClick={onRefresh}
              disabled={isFetching}
              title="Refresh"
              aria-label="Refresh live activity"
              className="text-muted hover:text-cyan transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <IconRefresh size={15} className={isFetching ? 'animate-spin' : ''} />
            </button>
          )}
        </div>
      </div>
      <div className="flex-1 overflow-y-auto scrollbar-thin" role="log" aria-live="polite" aria-relevant="additions" aria-label="Near-real-time decision activity feed">
        {isLoading && items.length === 0 ? (
          <LoadingState label="Loading activity…" />
        ) : items.length === 0 ? (
          <EmptyState label="No recent activity" />
        ) : (
          items.map((item) => (
            <FeedRow key={item.decision_id} item={item} onClick={() => navigate(ROUTES.threats)} />
          ))
        )}
      </div>
    </Card>
  )
}
