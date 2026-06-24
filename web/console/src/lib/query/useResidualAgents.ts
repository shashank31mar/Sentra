import { useQuery } from '@tanstack/react-query'
import { identityApi } from '../api/identity'
import { queryKeys } from '../queryKeys'

/**
 * Residual uncredentialed agents on the WS-B B1 fallback window (WS-C C2).
 * Read-only operator view. Shorter staleTime than `/v1/me` — the list shifts as
 * agents are onboarded/retired and as windows expire — but not on the hot path.
 */
export function useResidualAgents() {
  return useQuery({
    queryKey: queryKeys.identity.residual(),
    queryFn: () => identityApi.listResidual(),
    staleTime: 2 * 60_000,
  })
}
