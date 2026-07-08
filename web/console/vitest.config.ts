import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Test harness (WS-G G2.0). Reuses the app's @vitejs/plugin-react transform so
// component tests see the same JSX/TSX pipeline as the Vite build. jsdom + the
// jest-dom matchers are wired in src/test/setup.ts. No MSW — network is faked
// per-test via the in-repo mock router / spies (see docs/frontend-stack.md).
export default defineConfig({
  plugins: [react()],
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['src/test/setup.ts'],
    // Keep the type-only build out of the test run; tsc -b is the typecheck gate.
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'html'],
    },
  },
})
