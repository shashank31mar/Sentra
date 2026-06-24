import { useQuery } from '@tanstack/react-query'
import { meApi } from '../api/me'
import { queryKeys } from '../queryKeys'
import { can as rbacCan, type Capability } from '../rbac'

/**
 * Server-derived operator context (LLD-26 WS-C). The authority for the active
 * tenant + RBAC role + the membership set that drives the tenant switcher.
 * Falls back to non-throwing so the shell still renders if /v1/me is unavailable
 * (the server still enforces every write regardless of what the UI shows).
 */
export function useMe() {
  return useQuery({
    queryKey: queryKeys.auth.context(),
    queryFn: meApi.get,
    staleTime: 5 * 60_000,
    retry: false,
  })
}

/** `can(capability)` bound to the current operator's role (render gate only). */
export function useCan(): (cap: Capability) => boolean {
  const { data } = useMe()
  return (cap: Capability) => rbacCan(data?.role, cap)
}
