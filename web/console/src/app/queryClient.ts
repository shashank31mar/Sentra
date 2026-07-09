import { MutationCache, QueryClient } from '@tanstack/react-query'
import { handleAuthDegrade } from '../lib/degrade'
import { emitErrorToast } from '../lib/toastBridge'

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
 * FX-2.4: the centralized handler ALSO surfaces the SANITIZED, customer-safe 403
 * message (`ApiException.message` = `normalizeErrorBody` output — never a raw
 * server exception/stack/host) via the `toastBridge`, so a demoted operator sees
 * *why* the action was refused, not just a silently vanishing control. The bridge
 * forwards to the mounted `ToastProvider`; before mount (or in a provider-less
 * test) it is a safe no-op. The 404/501 PARTIAL path and the 401 reauth path are
 * unaffected — a non-403 status makes `handleAuthDegrade` return without touching
 * the cache or firing a toast.
 */
const mutationCache = new MutationCache({
  onError: (error) => {
    // `queryClient` is referenced before its declaration, but this closure only
    // runs at mutation time (long after module init) — the standard TanStack
    // pattern for a cache↔client back-reference.
    handleAuthDegrade(error, queryClient, emitErrorToast)
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
