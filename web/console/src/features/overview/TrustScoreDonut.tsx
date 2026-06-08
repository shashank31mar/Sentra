import type { TrustStatus } from '../../types/enums'
import { trustStatusColor, trustStatusLabel } from './trustStatus'

interface TrustScoreDonutProps {
  score: number | null
  status: TrustStatus
}

export function TrustScoreDonut({ score, status }: TrustScoreDonutProps) {
  const radius = 42
  const circumference = 2 * Math.PI * radius
  const pct = score === null ? 0 : Math.max(0, Math.min(100, score)) / 100
  const color = trustStatusColor(status)

  return (
    <div className="relative w-24 h-24 shrink-0">
      <svg viewBox="0 0 100 100" className="w-24 h-24 -rotate-90">
        <circle cx="50" cy="50" r={radius} fill="none" stroke="rgba(255,255,255,0.06)" strokeWidth="8" />
        <circle
          cx="50"
          cy="50"
          r={radius}
          fill="none"
          stroke={color}
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - pct)}
          style={{ transition: 'stroke-dashoffset 0.6s ease', filter: `drop-shadow(0 0 6px ${color})` }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="font-display text-2xl font-bold text-cyan">{score === null ? '—' : score}</span>
        <span className="text-[10px] font-mono text-muted">/100</span>
      </div>
      <span className="sr-only">{trustStatusLabel(status)}</span>
    </div>
  )
}
