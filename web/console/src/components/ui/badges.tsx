import type { ReactNode } from 'react'
import type { CloudProvider, Decision, DiscoveryStatus, Risk } from '../../types/enums'

interface PillProps {
  children: ReactNode
  color: string
  className?: string
}

function Pill({ children, color, className = '' }: PillProps) {
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-mono font-bold uppercase tracking-tight ${className}`}
      style={{ color, background: `${color}1a`, border: `1px solid ${color}33` }}
    >
      {children}
    </span>
  )
}

const NEUTRAL = '#8DA2AE'

/** Safe label for an unknown/undefined enum value coming from live data. */
function rawLabel(value: unknown, max = 6): string {
  if (value === null || value === undefined || value === '') return '—'
  return String(value).toUpperCase().slice(0, max)
}

const CLOUD: Partial<Record<CloudProvider, { label: string; color: string }>> = {
  aws: { label: 'AWS', color: '#FF9900' },
  gcp: { label: 'GCP', color: '#4285F4' },
  azure: { label: 'AZR', color: '#37A0E8' },
}

export function CloudBadge({ provider }: { provider: CloudProvider | string | null | undefined }) {
  const c = CLOUD[provider as CloudProvider] ?? { label: rawLabel(provider, 4), color: NEUTRAL }
  return <Pill color={c.color}>{c.label}</Pill>
}

const DECISION: Partial<Record<Decision, { label: string; color: string }>> = {
  ALLOW: { label: 'Allowed', color: '#0FFFFF' },
  DENY: { label: 'Blocked', color: '#FF0080' },
}

export function DecisionBadge({ decision }: { decision: Decision | string | null | undefined }) {
  const d = DECISION[decision as Decision] ?? { label: rawLabel(decision, 10), color: NEUTRAL }
  return <Pill color={d.color}>{d.label}</Pill>
}

const RISK: Partial<Record<Risk, { label: string; color: string }>> = {
  high: { label: 'High', color: '#FF0080' },
  med: { label: 'Med', color: '#FFB020' },
  low: { label: 'Low', color: '#22E58B' },
}

export function RiskBadge({ risk }: { risk: Risk | string | null | undefined }) {
  const r = RISK[risk as Risk] ?? { label: rawLabel(risk, 6), color: NEUTRAL }
  return <Pill color={r.color}>{r.label}</Pill>
}

const DISCOVERY: Partial<Record<DiscoveryStatus, { label: string; color: string }>> = {
  managed: { label: 'Managed', color: '#22E58B' },
  unmanaged: { label: 'Unmanaged', color: NEUTRAL },
}

export function DiscoveryStatusBadge({ status }: { status: DiscoveryStatus | string | null | undefined }) {
  const s = DISCOVERY[status as DiscoveryStatus] ?? { label: rawLabel(status, 10), color: NEUTRAL }
  return <Pill color={s.color}>{s.label}</Pill>
}
