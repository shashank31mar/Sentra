import { http } from '../http'
import type { MetricsRange, TimeseriesBucket } from '../../types/enums'
import type {
  DecisionsTimeseries,
  MetricsOverview,
  PlatformDistribution,
} from '../../types/api'

export const metricsApi = {
  overview: (range: MetricsRange) =>
    http.get<MetricsOverview>('/metrics/overview', { range }),

  platformDistribution: () =>
    http.get<PlatformDistribution>('/metrics/platform-distribution'),

  decisionsTimeseries: (range: MetricsRange, bucket: TimeseriesBucket) =>
    http.get<DecisionsTimeseries>('/metrics/decisions-timeseries', { range, bucket }),
}
