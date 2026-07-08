import { MutationCache, QueryClient } from '@tanstack/react-query'
import { handleAuthDegrade } from '../lib/degrade'

/**
 * G2.8 / D6 — fail-secure auth-degrade wiring (ws-g-console.md §2.5, §5.4).
 *
 * A **403 on ANY mutation** means *authenticated-but-forbidden* — the operator was
 * likely demoted since the last `/v1/me` read. `MutationCache.onError` runs for
 * EVERY mutation, centrally and exactly once per failure, so the 403 here forces
 * the operator-context re-read (`invalidateQueries(['auth','context'])`) and the
 * gated controls disappear on the next render. This MUST live on the cache, not
 * per-page: a per-page `onError` is trivial to forget on a newly added mutation —
 * that omission was the fail-secure gap this closes (`handleAuthDegrade` was dead
 * code, called by nothing on the real error path). It does NOT log the operator
 * out — that is the 401/opaque-redirect path in `http.ts:reauthenticate`,
 * deliberately kept separate (§2.5: a 403 is forbidden, not expired).
 *
 * Division of labor: the centralized handler owns only the fail-secure
 * invalidation; user-facing messaging stays with the page-level `onError` toasts
 * (UX lane), so the toast callback passed here is intentionally a no-op. The
 * 404/501 PARTIAL path and the 401 reauth path are unaffected — a non-403 status
 * makes `handleAuthDegrade` return without touching the cache.
 */
const mutationCache = new MutationCache({
  onError: (error) => {
    // `queryClient` is referenced before its declaration, but this closure only
    // runs at mutation time (long after module init) — the standard TanStack
    // pattern for a cache↔client back-reference.
    handleAuthDegrade(error, queryClient, () => {})
  },
})

export const queryClient = new QueryClient({
  mutationCache,
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
})
