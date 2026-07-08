import { useQuery } from '@tanstack/react-query'
import { usageApi } from '../api/usage'

/**
 * Metered usage rollup (`GET /v1/usage`, WS-H). `retry:false` so the not-yet-live
 * state (404/501) surfaces immediately as a PARTIAL banner rather than retrying.
 */
export function useUsage() {
  return useQuery({
    queryKey: ['usage'],
    queryFn: usageApi.get,
    retry: false,
  })
}
