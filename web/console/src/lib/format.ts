/** Display formatters — all data is formatted here, never pre-formatted in props. */

export function formatNumber(n: number | null | undefined, compact = false): string {
  if (n === null || n === undefined) return '—'
  if (compact) {
    return new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 }).format(n)
  }
  return new Intl.NumberFormat('en').format(n)
}

export function formatPercent(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined) return '—'
  return `${n.toFixed(digits)}%`
}

export function formatDelta(n: number | null | undefined): string | null {
  if (n === null || n === undefined) return null
  const sign = n >= 0 ? '+' : ''
  return `${sign}${n.toFixed(0)}%`
}

/** Short relative time, e.g. "3s", "12m", "5h", "2d". */
export function formatRelativeTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return '—'
  const sec = Math.max(0, Math.round((Date.now() - then) / 1000))
  if (sec < 60) return `${sec}s`
  const min = Math.round(sec / 60)
  if (min < 60) return `${min}m`
  const hr = Math.round(min / 60)
  if (hr < 24) return `${hr}h`
  return `${Math.round(hr / 24)}d`
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleString('en', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}
