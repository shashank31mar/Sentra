/** Display formatters — all data is formatted here, never pre-formatted in props. */

/**
 * Universal trust-score → color mapping (navy design-spec §1): `≥80` green,
 * `50–79` amber, `<50` pink. Returns the theme token hex so trust dots/bars are
 * consistent everywhere. A null/undefined score (no samples — §11.2) is treated
 * as "unknown" and renders faint, never as a misleading 0/red.
 */
export function trustColor(n: number | null | undefined): string {
  if (n === null || n === undefined || Number.isNaN(n)) return '#4E607E' // faint / unknown
  if (n >= 80) return '#22E58B' // green
  if (n >= 50) return '#FFB020' // amber
  return '#FF3D71' // pink
}

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

/**
 * Signed relative time from an epoch-ms timestamp, e.g. past → "3m ago", future
 * → "in 5h", now → "now". Unlike `formatRelativeTime` (which clamps the future to
 * 0s), this keeps direction — needed for the residual-agent fallback deadline,
 * which is usually in the future ("expires in …") until it lapses ("expired …").
 */
export function formatRelativeFromMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return '—'
  const deltaSec = Math.round((ms - Date.now()) / 1000)
  const future = deltaSec >= 0
  const abs = Math.abs(deltaSec)
  let mag: string
  if (abs < 60) mag = `${abs}s`
  else if (abs < 3600) mag = `${Math.round(abs / 60)}m`
  else if (abs < 86400) mag = `${Math.round(abs / 3600)}h`
  else mag = `${Math.round(abs / 86400)}d`
  if (abs < 5) return 'now'
  return future ? `in ${mag}` : `${mag} ago`
}
