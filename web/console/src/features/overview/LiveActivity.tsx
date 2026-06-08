import { useNavigate } from 'react-router-dom'
import { IconShieldCheck, IconShieldX } from '@tabler/icons-react'
import { Card } from '../../components/ui/Card'
import { StatusDot } from '../../components/ui/StatusDot'
import { CloudBadge } from '../../components/ui/badges'
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
      {blocked ? <IconShieldX size={18} className="mt-0.5 text-pink" /> : <IconShieldCheck size={18} className="mt-0.5 text-cyan" />}
      <div className="min-w-0 flex-1">
        <div className="text-sm font-mono font-bold truncate">{item.agent_name}</div>
        <div className="text-xs mt-1 text-secondary truncate">{item.reason ?? item.tool_name ?? '—'}</div>
      </div>
      <div className="text-right shrink-0">
        <CloudBadge provider={item.cloud_provider} />
        <div className="text-[10px] mt-1.5 font-mono text-muted">{formatRelativeTime(item.timestamp)}</div>
      </div>
    </button>
  )
}

export function LiveActivity({ items, isLoading }: { items: DecisionItem[]; isLoading: boolean }) {
  const navigate = useNavigate()
  return (
    <Card className="flex flex-col overflow-hidden" style={{ maxHeight: 420 }}>
      <div className="flex items-center justify-between px-6 py-5 bg-white/[0.01]" style={{ borderBottom: '1px solid var(--color-line)' }}>
        <h3 className="font-display text-lg font-bold tracking-tight flex items-center gap-2.5">
          Live Activity <StatusDot color="#0FFFFF" pulse />
        </h3>
        <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-muted">Streaming</span>
      </div>
      <div className="flex-1 overflow-y-auto scrollbar-thin">
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
