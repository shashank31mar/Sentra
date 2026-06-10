import { useNavigate } from 'react-router-dom'
import {
  IconActivityHeartbeat,
  IconBolt,
  IconDotsVertical,
  IconLockX,
  IconRobot,
  IconShieldX,
  IconTarget,
  IconTrendingUp,
} from '@tabler/icons-react'
import { Card } from '../../components/ui/Card'
import { StatusDot } from '../../components/ui/StatusDot'
import { ROUTES } from '../../app/routes'
import { formatDelta, formatNumber, formatPercent } from '../../lib/format'
import type { MetricsOverview } from '../../types/api'
import { TrustScoreDonut } from './TrustScoreDonut'
import { trustStatusLabel } from './trustStatus'

const labelCls = 'text-sm font-medium uppercase tracking-widest text-secondary'

function SmallStat({
  icon,
  label,
  children,
  accent = false,
  onClick,
  title,
}: {
  icon: React.ReactNode
  label: string
  children: React.ReactNode
  accent?: boolean
  onClick?: () => void
  title?: string
}) {
  const body = (
    <>
      <div className="flex items-center gap-2 text-[10px] uppercase tracking-[0.2em] text-secondary">
        {icon} {label}
      </div>
      <div className="font-display text-3xl font-bold mt-4 tracking-tight">{children}</div>
    </>
  )
  if (onClick) {
    return (
      <button
        type="button"
        onClick={onClick}
        title={title}
        className="rounded-2xl bg-surface-2 p-5 text-left w-full cursor-pointer transition-all hover:border-pink/40"
        style={{ border: accent ? '1px solid rgba(255,0,128,0.18)' : '1px solid var(--color-line)' }}
      >
        {body}
      </button>
    )
  }
  return (
    <Card className="p-5" accent={accent ? 'danger' : 'default'}>
      {body}
    </Card>
  )
}

export function KpiGrid({ data }: { data: MetricsOverview }) {
  const navigate = useNavigate()
  const delta = formatDelta(data.threats_blocked_delta_pct)

  return (
    <div className="flex flex-col gap-5 mb-5">
      {/* Top row: hero threats + active agents + trust score */}
      <div className="grid gap-5 grid-cols-1 lg:grid-cols-3 lg:grid-rows-2">
        {/* Hero — Total Threats Blocked */}
        <button
          type="button"
          onClick={() => navigate(ROUTES.threats)}
          title="View blocked threats"
          className="lg:col-span-2 lg:row-span-2 text-left rounded-2xl p-6 sm:p-7 relative overflow-hidden flex flex-col cursor-pointer transition-all hover:border-pink/40"
          style={{ background: '#0B141C', border: '1px solid rgba(255,0,128,0.18)', boxShadow: '0 0 60px -30px rgba(255,0,128,.5)' }}
        >
          <div
            className="absolute -top-16 -right-16 w-56 h-56 rounded-full blur-3xl"
            style={{ background: 'radial-gradient(circle,rgba(255,0,128,0.18),transparent 70%)' }}
          />
          <div className="flex items-center justify-between relative">
            <div className="flex items-center gap-2.5">
              <div className="w-9 h-9 rounded-lg flex items-center justify-center" style={{ background: 'rgba(255,0,128,0.1)', border: '1px solid rgba(255,0,128,0.2)' }}>
                <IconShieldX size={20} className="text-pink" />
              </div>
              <span className={labelCls}>Total Threats Blocked</span>
            </div>
            {delta && (
              <span className="text-xs font-mono px-2 py-1 rounded-md flex items-center gap-1 text-green" style={{ background: 'rgba(34,229,139,0.1)', border: '1px solid rgba(34,229,139,0.2)' }}>
                <IconTrendingUp size={14} /> {delta} vs prev
              </span>
            )}
          </div>
          <div className="relative mt-6">
            <div className="font-display font-bold tracking-tight text-pink" style={{ fontSize: 'clamp(3rem, 12vw, 5.5rem)', lineHeight: 1, textShadow: '0 0 28px rgba(255,0,128,.45)' }}>
              {formatNumber(data.threats_blocked)}
            </div>
            <div className="text-sm mt-4 font-mono uppercase tracking-[0.2em] text-muted">
              across {data.range} · {data.attack_categories} attack categories
            </div>
          </div>
        </button>

        {/* Active Agents */}
        <button
          type="button"
          onClick={() => navigate(ROUTES.agents)}
          title="View Agent Inventory"
          className="text-left rounded-2xl p-5 relative overflow-hidden cursor-pointer transition-all hover:border-cyan/40 bg-surface-2"
          style={{ border: '1px solid var(--color-line)' }}
        >
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg flex items-center justify-center" style={{ background: 'rgba(15,255,255,0.08)', border: '1px solid rgba(15,255,255,0.18)' }}>
                <IconRobot size={16} className="text-cyan" />
              </div>
              <span className={labelCls}>Active Agents</span>
            </div>
            <IconDotsVertical size={18} className="text-muted" />
          </div>
          <div className="flex items-end gap-3 mt-4">
            <div className="font-display text-5xl font-bold tracking-tight text-cyan">{formatNumber(data.active_agents)}</div>
            <div className="text-xs font-mono mb-1.5 text-muted">across {data.clouds} clouds</div>
          </div>
        </button>

        {/* Global Trust Score */}
        <Card className="p-5 flex items-center gap-5">
          <TrustScoreDonut score={data.trust_score} status={data.trust_status} />
          <div>
            <div className={labelCls}>Global Trust Score</div>
            <div className="text-xs font-mono mt-1 flex items-center gap-2" style={{ color: data.trust_status === 'healthy' ? '#22E58B' : '#8DA2AE' }}>
              <StatusDot color={data.trust_status === 'healthy' ? '#22E58B' : '#8DA2AE'} pulse /> {trustStatusLabel(data.trust_status)}
            </div>
            <div className="text-[11px] mt-3 font-mono leading-relaxed text-muted">
              {formatNumber(data.agents_below_threshold)} agents below threshold
            </div>
          </div>
        </Card>
      </div>

      {/* Small stat row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-5">
        <SmallStat icon={<IconActivityHeartbeat size={13} />} label="Total Requests">
          {formatNumber(data.requests_total, true)}
        </SmallStat>
        <SmallStat icon={<IconBolt size={13} />} label="Avg Latency">
          <span className="text-cyan">{formatNumber(data.avg_latency_ms)}<span className="text-xl ml-1 text-muted">ms</span></span>
        </SmallStat>
        <SmallStat
          icon={<IconLockX size={13} />}
          label="Quarantined"
          accent
          onClick={() => navigate(ROUTES.quarantine)}
          title="View quarantined sessions"
        >
          <span className="text-pink">{formatNumber(data.quarantined)}</span>
        </SmallStat>
        <SmallStat icon={<IconTarget size={13} />} label="False Positive">
          {/* P0: false_positive_pct is null/hidden per LLD §11.2 */}
          <span className="text-amber">{data.false_positive_pct === null ? '—' : formatPercent(data.false_positive_pct)}</span>
        </SmallStat>
      </div>
    </div>
  )
}
