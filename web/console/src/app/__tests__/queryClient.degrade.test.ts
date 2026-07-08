import { describe, it, expect, vi, afterEach } from 'vitest'
import { MutationObserver } from '@tanstack/react-query'
import { queryClient } from '../queryClient'
import { ApiException } from '../../lib/http'
import { queryKeys } from '../../lib/queryKeys'

/**
 * G2.8 / D6 — the FAIL-SECURE WIRING, not the helper in isolation.
 *
 * `degrade.test.ts` already proves `handleAuthDegrade()` invalidates the
 * me/context query when handed a 403. THIS proves the *production* `queryClient`'s
 * `MutationCache.onError` actually CALLS it — i.e. a real 403 mutation, driven
 * through the real singleton client, forces the `['auth','context']` re-read so a
 * demoted operator's gated controls disappear on the next render.
 *
 * That wiring (a `MutationCache` on `queryClient.ts`) was the gap the finding
 * flagged: without it, `handleAuthDegrade` was dead code — nothing on the mutation
 * error path called it, so the documented fail-secure degrade (ws-g-console.md
 * §2.5, §5.4 D6) never fired. This test FAILS if the `MutationCache` is removed.
 */
async function runMutation(err?: unknown): Promise<void> {
  const observer = new MutationObserver(queryClient, {
    mutationFn: async () => {
      if (err) throw err
      return 'ok'
    },
    retry: false,
  })
  // The mutation promise rejects on error — that is expected; we assert the
  // side-effect (cache invalidation) the MutationCache.onError produced.
  await observer.mutate().catch(() => {})
}

describe('queryClient MutationCache fail-secure wiring (G2.8/D6)', () => {
  afterEach(() => vi.restoreAllMocks())

  it('a 403 mutation invalidates the me/context query through the real client', async () => {
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
    await runMutation(new ApiException(403, { error: 'forbidden', error_code: 'FORBIDDEN' }))
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.auth.context() })
  })

  it('a 500 mutation does NOT invalidate the me/context query (403-only, no reauth churn)', async () => {
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
    await runMutation(new ApiException(500, { error: 'boom', error_code: 'INTERNAL' }))
    expect(invalidate).not.toHaveBeenCalledWith({ queryKey: queryKeys.auth.context() })
  })

  it('a successful mutation does not invalidate the me/context query', async () => {
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
    await runMutation()
    expect(invalidate).not.toHaveBeenCalledWith({ queryKey: queryKeys.auth.context() })
  })
})
