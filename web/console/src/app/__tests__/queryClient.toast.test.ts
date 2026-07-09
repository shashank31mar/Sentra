import { describe, it, expect, vi, afterEach } from 'vitest'
import { MutationObserver } from '@tanstack/react-query'
import { registerErrorToast } from '../../lib/toastBridge'
import { queryClient } from '../queryClient'
import { ApiException } from '../../lib/http'

/**
 * FX-2.4 — the production `queryClient`'s MutationCache surfaces the SANITIZED 403
 * message through the toastBridge (previously a no-op — the message was dropped).
 * This drives a real 403 mutation through the real singleton client and asserts the
 * registered error-toast fired with the sanitized message. It asserts against the
 * WIRED cache path (not an injected vi.fn passed to the helper), so it FAILS if the
 * MutationCache stops forwarding to the bridge.
 */
async function runMutation(err?: unknown): Promise<void> {
  const observer = new MutationObserver(queryClient, {
    mutationFn: async () => {
      if (err) throw err
      return 'ok'
    },
    retry: false,
  })
  await observer.mutate().catch(() => {})
}

describe('queryClient MutationCache sanitized-403 toast wiring (FX-2.4)', () => {
  afterEach(() => vi.restoreAllMocks())

  it('a 403 mutation fires the registered error toast with the sanitized message', async () => {
    const toastSpy = vi.fn()
    const unregister = registerErrorToast(toastSpy)
    try {
      await runMutation(new ApiException(403, { error: 'You no longer have permission.', error_code: 'FORBIDDEN' }))
      expect(toastSpy).toHaveBeenCalledWith('You no longer have permission.')
    } finally {
      unregister()
    }
  })

  it('a 500 mutation does NOT fire the 403 toast (403-only lane)', async () => {
    const toastSpy = vi.fn()
    const unregister = registerErrorToast(toastSpy)
    try {
      await runMutation(new ApiException(500, { error: 'boom', error_code: 'INTERNAL' }))
      expect(toastSpy).not.toHaveBeenCalled()
    } finally {
      unregister()
    }
  })

  it('a successful mutation fires no toast', async () => {
    const toastSpy = vi.fn()
    const unregister = registerErrorToast(toastSpy)
    try {
      await runMutation()
      expect(toastSpy).not.toHaveBeenCalled()
    } finally {
      unregister()
    }
  })
})
