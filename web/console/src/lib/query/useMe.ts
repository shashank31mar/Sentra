import { useQuery } from '@tanstack/react-query'
import { meApi } from '../api/me'
import { queryKeys } from '../queryKeys'
import {
  can as rbacCan,
  platformCan as rbacPlatformCan,
  type Capability,
  type PlatformCapability,
} from '../rbac'

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
    // G2.8 fail-secure degrade: a demoted operator's role re-reads on tab focus
    // (≤5-min staleness accepted). On a lower role, gated controls disappear on
    // the next render — the UI never lingers showing a control the server 403s.
    refetchOnWindowFocus: true,
  })
}

/** `can(capability)` bound to the current operator's role (render gate only). */
export function useCan(): (cap: Capability) => boolean {
  const { data } = useMe()
  return (cap: Capability) => rbacCan(data?.role, cap)
}

/** `platformCan(capability)` bound to the operator's `is_platform` flag (render
 *  gate only; the server `require_platform` remains the boundary). */
export function usePlatformCan(): (cap: PlatformCapability) => boolean {
  const { data } = useMe()
  return (cap: PlatformCapability) => rbacPlatformCan(data?.is_platform, cap)
}
