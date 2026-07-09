import { describe, it, expect, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { QueryClientProvider, useMutation } from '@tanstack/react-query'
import { queryClient } from '../queryClient'
import { ToastProvider, useToast } from '../../components/ui/Toast'
import { ApiException } from '../../lib/http'
import { isAuthDegrade403 } from '../../lib/degrade'

/**
 * FXR-1 — a mutation 403 must produce EXACTLY ONE sanitized toast, not two.
 *
 * The production singleton `queryClient` carries a `MutationCache.onError` that
 * surfaces the sanitized 403 message ONCE via the toastBridge (FX-2.4). A page-level
 * `onError` that ALSO toasts on a 403 is the double-toast bug (the operator sees the
 * same refusal twice). The fix: page handlers defer via {@link isAuthDegrade403}.
 *
 * This drives a real 403 mutation through the REAL wired client + a REAL mounted
 * `ToastProvider` (which registers the bridge on mount). The guarded button mirrors
 * the fixed pages (defer to the bridge for a 403); the CONTROL button mirrors the old
 * bug (toast unconditionally) and MUST show two toasts — proving the assertion below
 * is load-bearing, not vacuous.
 */

const forbidden = () =>
  new ApiException(403, { error: 'You no longer have permission.', error_code: 'FORBIDDEN' })

function GuardedMutationButton() {
  const { error } = useToast()
  const m = useMutation({
    mutationFn: async () => {
      throw forbidden()
    },
    retry: false,
    // The FIXED page pattern: a 403 is already surfaced by the global bridge — skip
    // the page toast; only report non-403 failures.
    onError: (e) => {
      if (!isAuthDegrade403(e)) error('Could not perform the action. Please try again.')
    },
  })
  return <button onClick={() => m.mutate()}>run</button>
}

function UnguardedMutationButton() {
  const { error } = useToast()
  const m = useMutation({
    mutationFn: async () => {
      throw forbidden()
    },
    retry: false,
    // The OLD buggy pattern: toast on EVERY error, including a 403 → double toast.
    onError: () => error('Could not perform the action. Please try again.'),
  })
  return <button onClick={() => m.mutate()}>run</button>
}

function mount(ui: React.ReactElement) {
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>{ui}</ToastProvider>
    </QueryClientProvider>,
  )
}

describe('mutation 403 double-toast suppression (FXR-1)', () => {
  afterEach(() => vi.restoreAllMocks())

  it('a guarded page handler yields EXACTLY ONE sanitized toast on a 403 (global bridge only)', async () => {
    const user = userEvent.setup()
    mount(<GuardedMutationButton />)

    await user.click(screen.getByRole('button', { name: 'run' }))

    // One toast — the global bridge's sanitized message; the page adds none.
    const toasts = await screen.findAllByRole('status')
    expect(toasts).toHaveLength(1)
    expect(toasts[0]).toHaveTextContent('You no longer have permission.')
    // The page's generic message must NOT appear (it deferred).
    expect(screen.queryByText(/Could not perform the action/i)).not.toBeInTheDocument()
  })

  it('CONTROL: an UNGUARDED handler produces TWO toasts (proves the guard is load-bearing)', async () => {
    const user = userEvent.setup()
    mount(<UnguardedMutationButton />)

    await user.click(screen.getByRole('button', { name: 'run' }))

    // The buggy path: global bridge toast + the page toast = TWO. This is exactly the
    // state the guard prevents, so the guarded test above is not vacuous.
    await waitFor(() => expect(screen.getAllByRole('status')).toHaveLength(2))
  })
})
