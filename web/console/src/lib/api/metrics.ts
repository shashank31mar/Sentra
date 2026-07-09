import { http } from '../http'
import type { MetricsRange, TimeseriesBucket } from '../../types/enums'
import type {
  DecisionsTimeseries,
  MetricsOverview,
  PlatformDistribution,
} from '../../types/api'

/**
 * FX-1.5 / FX-2.3: fleet-mode metrics for the platform console MUST NOT attach
 * `X-Aegion-Tenant` — code-enforced via `omitTenant`, so the server's
 * `_operator_read_scope` takes the fleet aggregate path (`tenant_id=None`, audited)
 * for an `is_platform` operator by construction, not by the luck of having no bound
 * tenant. The customer-scoped calls above intentionally KEEP the header.
 */
const FLEET_OPTS = { omitTenant: true } as const

export const metricsApi = {
  overview: (range: MetricsRange) =>
    http.get<MetricsOverview>('/metrics/overview', { range }),

  platformDistribution: () =>
    http.get<PlatformDistribution>('/metrics/platform-distribution'),

  decisionsTimeseries: (range: MetricsRange, bucket: TimeseriesBucket) =>
    http.get<DecisionsTimeseries>('/metrics/decisions-timeseries', { range, bucket }),

  fleetOverview: (range: MetricsRange) =>
    http.get<MetricsOverview>('/metrics/overview', { range }, FLEET_OPTS),

  fleetDecisionsTimeseries: (range: MetricsRange, bucket: TimeseriesBucket) =>
    http.get<DecisionsTimeseries>('/metrics/decisions-timeseries', { range, bucket }, FLEET_OPTS),
}
