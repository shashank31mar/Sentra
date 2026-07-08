import '@testing-library/jest-dom/vitest'
import { afterEach } from 'vitest'
import { cleanup } from '@testing-library/react'

// Unmount React trees between tests so DOM queries never bleed across cases.
afterEach(() => {
  cleanup()
})

// jsdom lacks ResizeObserver, which @tanstack/react-virtual needs to measure the
// scroll element. Stub one that fires the callback once on observe with a non-zero
// content rect, so the virtualizer windows real rows (a no-op stub + jsdom's
// 0-height rects would collapse it to zero rows — the exact mis-set-container bug
// the TenantGrid test guards against).
if (!('ResizeObserver' in globalThis)) {
  class ResizeObserverStub {
    cb: ResizeObserverCallback
    constructor(cb: ResizeObserverCallback) {
      this.cb = cb
    }
    observe(target: Element) {
      const rect = { width: 960, height: 480, top: 0, left: 0, right: 960, bottom: 480, x: 0, y: 0 }
      this.cb(
        [{ target, contentRect: rect as DOMRectReadOnly } as ResizeObserverEntry],
        this as unknown as ResizeObserver,
      )
    }
    unobserve() {}
    disconnect() {}
  }
  ;(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = ResizeObserverStub
}
