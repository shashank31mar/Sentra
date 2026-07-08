import type { QueryClient } from '@tanstack/react-query'
import { ApiException } from './http'
import { queryKeys } from './queryKeys'

/**
 * G2.8 — fail-secure UI degrade on an authorization change (D6).
 *
 * A **403** on a mutation means *authenticated-but-forbidden* (the operator was
 * likely demoted since the last `/v1/me` read). The correct response is NOT to log
 * them out (that's the 401/opaque-redirect path in `http.ts:reauthenticate`) — a
 * 403 must:
 *   1. surface the SANITIZED, customer-safe message (never the raw server
 *      exception/stack/host — `ApiException.message` is already the normalized
 *      `normalizeErrorBody` output), and
 *   2. force a re-read of the operator context by invalidating `['auth','context']`
 *      so the demoted role reloads and the gated controls disappear on next render.
 *
 * Returns `true` iff it handled a 403 (so callers can skip their generic error
 * toast). Any other status is left to the caller — this is the auth-change lane
 * only, deliberately narrow.
 */
export function handleAuthDegrade(
  err: unknown,
  qc: QueryClient,
  toastError: (message: string) => void,
): boolean {
  if (!(err instanceof ApiException) || err.status !== 403) return false
  // Sanitized message only (ApiException.message is normalizeErrorBody output).
  const safe = err.message || 'You no longer have permission to perform this action.'
  toastError(safe)
  // Force the role re-read; do NOT reauthenticate() and do NOT hard-navigate.
  void qc.invalidateQueries({ queryKey: queryKeys.auth.context() })
  return true
}
