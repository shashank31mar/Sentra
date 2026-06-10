import { useQuery } from '@tanstack/react-query'
import { authApi } from '../api/auth'
import { queryKeys } from '../queryKeys'

/** Logged-in operator identity (from the `/whoami` edge endpoint). */
export function useCurrentUser() {
  return useQuery({
    queryKey: queryKeys.auth.me(),
    queryFn: authApi.me,
    staleTime: 5 * 60_000,
    retry: false,
  })
}
