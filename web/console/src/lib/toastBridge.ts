/**
 * Toast bridge (FX-2.4) — a tiny module-level seam so code that lives OUTSIDE the
 * React tree (the singleton `queryClient`'s `MutationCache.onError`) can surface a
 * user-facing toast through the mounted `ToastProvider`.
 *
 * The provider registers its imperative `error(message)` on mount and clears it on
 * unmount; before registration (or after unmount) `emitErrorToast` is a safe no-op,
 * so a toast fired during a test with no provider never throws. This is deliberately
 * NOT a second toast system — it forwards to the same `ToastProvider` the pages use.
 */
type ErrorToastFn = (message: string) => void

let errorToast: ErrorToastFn | null = null

/** Called by `ToastProvider` on mount to expose its imperative `error()`. Returns
 *  an unregister fn so unmount clears the reference (no stale closure after teardown). */
export function registerErrorToast(fn: ErrorToastFn): () => void {
  errorToast = fn
  return () => {
    if (errorToast === fn) errorToast = null
  }
}

/** Fire a sanitized error toast if a provider is mounted; a no-op otherwise. */
export function emitErrorToast(message: string): void {
  errorToast?.(message)
}
