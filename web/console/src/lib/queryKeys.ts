import type { MetricsRange, TimeseriesBucket } from '../types/enums'

/** Centralized React Query keys for cache consistency + invalidation. */
export const queryKeys = {
  auth: {
    me: () => ['auth', 'me'] as const,
    // Server-derived tenant + role + memberships (LLD-26 GET /v1/me). Distinct
    // from `me()` (the cosmetic /whoami identity).
    context: () => ['auth', 'context'] as const,
  },
  metrics: {
    overview: (range: MetricsRange) => ['metrics', 'overview', range] as const,
    platformDistribution: () => ['metrics', 'platform-distribution'] as const,
    decisionsTimeseries: (range: MetricsRange, bucket: TimeseriesBucket) =>
      ['metrics', 'decisions-timeseries', range, bucket] as const,
    // FX-1.5 fleet-mode aggregates (distinct keys so the fleet cache never collides
    // with the customer-scoped read).
    fleetOverview: (range: MetricsRange) => ['metrics', 'fleet', 'overview', range] as const,
    fleetDecisionsTimeseries: (range: MetricsRange, bucket: TimeseriesBucket) =>
      ['metrics', 'fleet', 'decisions-timeseries', range, bucket] as const,
  },
  decisions: {
    list: (filters: Record<string, unknown>) => ['decisions', filters] as const,
  },
  sessions: {
    list: (filters: Record<string, unknown>) => ['sessions', filters] as const,
    // WS-D recomputed decision trail for one request (FX-1.2).
    trail: (sessionId: string, requestId: string) =>
      ['sessions', 'trail', sessionId, requestId] as const,
  },
  logs: {
    list: (filters: Record<string, unknown>) => ['logs', filters] as const,
    conversation: (id: string) => ['logs', 'conversation', id] as const,
  },
  agents: {
    list: () => ['agents', 'list'] as const,
    detail: (id: string) => ['agents', 'detail', id] as const,
    tools: (id: string) => ['agents', 'tools', id] as const,
  },
  identity: {
    // Residual uncredentialed agents on the WS-B B1 fallback window (WS-C C2).
    residual: () => ['identity', 'residual-agents'] as const,
  },
  connections: {
    list: () => ['connections', 'list'] as const,
    detail: (id: string) => ['connections', 'detail', id] as const,
  },
  discovery: {
    summary: () => ['discovery', 'summary'] as const,
    platforms: () => ['discovery', 'platforms'] as const,
    agents: (filters: Record<string, unknown>) => ['discovery', 'agents', filters] as const,
  },
  policies: {
    list: (filters: Record<string, unknown>) => ['policies', filters] as const,
    detail: (id: string) => ['policies', 'detail', id] as const,
  },
  sigma: {
    list: (filters: Record<string, unknown>) => ['sigma-rules', filters] as const,
    content: (id: string) => ['sigma-rules', 'content', id] as const,
  },
  platform: {
    tenants: (params: Record<string, unknown>) => ['platform', 'tenants', params] as const,
    tenantDetail: (id: string) => ['platform', 'tenants', 'detail', id] as const,
  },
} as const
