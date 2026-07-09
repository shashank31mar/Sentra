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
  if (!isAuthDegrade403(err)) return false
  // Sanitized message only (ApiException.message is normalizeErrorBody output).
  const safe = (err as ApiException).message || 'You no longer have permission to perform this action.'
  toastError(safe)
  // Force the role re-read; do NOT reauthenticate() and do NOT hard-navigate.
  void qc.invalidateQueries({ queryKey: queryKeys.auth.context() })
  return true
}

/**
 * FXR-1 — a **disabled-policy 403** is a RESOURCE-STATE refusal, NOT an operator
 * demotion. The server raises `ForbiddenException("Cannot update disabled policy.
 * Enable it first.")` (policy_service.py:521) — the operator still holds the editor
 * role; the *policy* is disabled. It must therefore be EXCLUDED from the auth-degrade
 * lane so the global `MutationCache` bridge does NOT (a) fire a second sanitized toast
 * on top of PolicyEditor's specific "Enable it first" banner (the "one surface, not
 * two" intent) nor (b) spuriously invalidate `['auth','context']` — treating a
 * disabled-policy refusal as a role change would force a needless operator-context
 * re-read. This is the canonical predicate; both {@link isAuthDegrade403} and the
 * PolicyEditor banner key off it, so the reason has a single spelling.
 *
 * Fail-safe by construction: an UNRECOGNIZED 403 does NOT match here → it is treated
 * as a genuine auth-degrade (the sanitized bridge toast still fires), never swallowed.
 */
const DISABLED_POLICY_403_RE = /disabled policy|policy is disabled/i
export function isDisabledPolicyState403(err: unknown): boolean {
  return err instanceof ApiException && err.status === 403 && DISABLED_POLICY_403_RE.test(err.message ?? '')
}

/**
 * FXR-1 — a mutation **403** is ALREADY surfaced exactly once by the global
 * `MutationCache.onError` (queryClient.ts → {@link handleAuthDegrade}) as a single
 * sanitized toast. A page-level `onError` handler MUST therefore defer to that
 * global toast and NOT add its own toast/banner for a 403, or the operator sees the
 * same refusal twice. This is the one predicate pages key off to skip their
 * duplicate surface. Non-403 errors are still the page's own to report.
 *
 * The disabled-policy 403 is deliberately EXCLUDED (see {@link isDisabledPolicyState403}):
 * that reason is not an auth-degrade — PolicyEditor owns its single actionable banner
 * for it, and the global bridge must neither double-surface it nor spuriously
 * invalidate the operator context.
 */
export function isAuthDegrade403(err: unknown): boolean {
  return err instanceof ApiException && err.status === 403 && !isDisabledPolicyState403(err)
}
