import type { MetricsRange, TimeseriesBucket } from '../types/enums'

/** Centralized React Query keys for cache consistency + invalidation. */
export const queryKeys = {
  metrics: {
    overview: (range: MetricsRange) => ['metrics', 'overview', range] as const,
    platformDistribution: () => ['metrics', 'platform-distribution'] as const,
    decisionsTimeseries: (range: MetricsRange, bucket: TimeseriesBucket) =>
      ['metrics', 'decisions-timeseries', range, bucket] as const,
  },
  decisions: {
    list: (filters: Record<string, unknown>) => ['decisions', filters] as const,
  },
  sessions: {
    list: (filters: Record<string, unknown>) => ['sessions', filters] as const,
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
  },
} as const
