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
