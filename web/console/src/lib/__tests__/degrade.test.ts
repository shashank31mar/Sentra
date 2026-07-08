import { describe, it, expect, vi } from 'vitest'
import { QueryClient } from '@tanstack/react-query'
import { handleAuthDegrade } from '../degrade'
import { ApiException } from '../http'
import { queryKeys } from '../queryKeys'

/**
 * G2.8 — a 403 on a mutation toasts the SANITIZED message + invalidates
 * `['auth','context']` (force role re-read) and does NOT reauthenticate. A non-403
 * is left to the caller (returns false).
 */
describe('handleAuthDegrade (G2.8)', () => {
  it('403 → sanitized toast + invalidates the me/context query, returns true', () => {
    const qc = new QueryClient()
    const invalidate = vi.spyOn(qc, 'invalidateQueries')
    const toastError = vi.fn()

    const handled = handleAuthDegrade(
      new ApiException(403, { error: 'You no longer have permission.', error_code: 'FORBIDDEN' }),
      qc,
      toastError,
    )

    expect(handled).toBe(true)
    expect(toastError).toHaveBeenCalledWith('You no longer have permission.')
    expect(invalidate).toHaveBeenCalledWith({ queryKey: queryKeys.auth.context() })
  })

  it('non-403 (e.g. 500) is not handled here → returns false, no toast', () => {
    const qc = new QueryClient()
    const toastError = vi.fn()
    const handled = handleAuthDegrade(
      new ApiException(500, { error: 'server error', error_code: 'INTERNAL' }),
      qc,
      toastError,
    )
    expect(handled).toBe(false)
    expect(toastError).not.toHaveBeenCalled()
  })

  it('a non-ApiException error is not handled', () => {
    const qc = new QueryClient()
    const toastError = vi.fn()
    expect(handleAuthDegrade(new Error('boom'), qc, toastError)).toBe(false)
  })
})
