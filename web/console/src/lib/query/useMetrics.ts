import { useQuery } from '@tanstack/react-query'
import type { MetricsRange, TimeseriesBucket } from '../../types/enums'
import { metricsApi } from '../api/metrics'
import { queryKeys } from '../queryKeys'

export function useOverview(range: MetricsRange = '24h') {
  return useQuery({
    queryKey: queryKeys.metrics.overview(range),
    queryFn: () => metricsApi.overview(range),
    refetchInterval: 30_000,
  })
}

export function usePlatformDistribution() {
  return useQuery({
    queryKey: queryKeys.metrics.platformDistribution(),
    queryFn: () => metricsApi.platformDistribution(),
  })
}

export function useDecisionsTimeseries(
  range: MetricsRange = '24h',
  bucket: TimeseriesBucket = '1h',
) {
  return useQuery({
    queryKey: queryKeys.metrics.decisionsTimeseries(range, bucket),
    queryFn: () => metricsApi.decisionsTimeseries(range, bucket),
  })
}

/** FX-1.5 — fleet-aggregate overview KPIs for the platform console. Sends NO
 *  `X-Aegion-Tenant` (code-enforced) so the server auto-aggregates for `is_platform`. */
export function useFleetOverview(range: MetricsRange = '24h') {
  return useQuery({
    queryKey: queryKeys.metrics.fleetOverview(range),
    queryFn: () => metricsApi.fleetOverview(range),
    refetchInterval: 30_000,
  })
}

/** FX-1.5 — fleet-aggregate allowed/blocked timeseries for the platform console. */
export function useFleetDecisionsTimeseries(
  range: MetricsRange = '24h',
  bucket: TimeseriesBucket = '1h',
) {
  return useQuery({
    queryKey: queryKeys.metrics.fleetDecisionsTimeseries(range, bucket),
    queryFn: () => metricsApi.fleetDecisionsTimeseries(range, bucket),
  })
}
