import type { TrustStatus } from '../../types/enums'

const STATUS_COLOR: Partial<Record<TrustStatus, string>> = {
  healthy: '#22E58B',
  degraded: '#FFB020',
  critical: '#FF0080',
  unknown: '#51636E',
}

const STATUS_LABEL: Partial<Record<TrustStatus, string>> = {
  healthy: 'Healthy',
  degraded: 'Degraded',
  critical: 'Critical',
  unknown: 'No data',
}

export const trustStatusColor = (s: TrustStatus | string | null | undefined) =>
  STATUS_COLOR[s as TrustStatus] ?? '#51636E'

export const trustStatusLabel = (s: TrustStatus | string | null | undefined) =>
  STATUS_LABEL[s as TrustStatus] ?? 'No data'
