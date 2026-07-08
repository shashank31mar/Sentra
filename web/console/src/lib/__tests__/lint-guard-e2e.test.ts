import { describe, it, expect } from 'vitest'
import { ESLint } from 'eslint'
import path from 'node:path'

/**
 * G1.2 integ (build gate) — runs the REAL `eslint.config.js` (the same config
 * `npm run lint` uses) over fixture source. Proves a scoping-misuse of the tenant
 * label produces a non-zero lint result, and clean code lints green — i.e. the
 * guard actually gates CI, not just a hand-rolled Linter in the unit test.
 */
// Vitest runs with cwd = the console package root (where vitest.config.ts lives),
// which is also where eslint.config.js resolves from.
const consoleRoot = process.cwd()

async function lintFixture(code: string) {
  const eslint = new ESLint({ cwd: consoleRoot })
  // A path under the console root so the flat config's `**/*.{ts,tsx}` glob applies.
  const results = await eslint.lintText(code, {
    filePath: path.join(consoleRoot, 'src', '__lint_fixture__.tsx'),
  })
  return results[0]
}

describe('FR-13.1 lint guard — real config build gate (G1.2 integ)', () => {
  it('fails lint on a fixture that scopes a query key on the tenant label', async () => {
    const res = await lintFixture(
      `import { queryKeys } from './lib/queryKeys'\n` +
        `import { tenantLabelForDisplay } from './lib/auth'\n` +
        `export const k = (user: unknown) => queryKeys.decisions.list(tenantLabelForDisplay(user as never))\n`,
    )
    expect(res.errorCount).toBeGreaterThanOrEqual(1)
    expect(res.messages.some((m) => /FR-13\.1/.test(m.message ?? ''))).toBe(true)
  })

  it('lints clean when the label is only used for display', async () => {
    const res = await lintFixture(
      `import { tenantLabelForDisplay } from './lib/auth'\n` +
        `export function Chip({ user }: { user: unknown }) {\n` +
        `  const tenant = tenantLabelForDisplay(user as never)\n` +
        `  return tenant\n` +
        `}\n`,
    )
    expect(res.messages.some((m) => /FR-13\.1/.test(m.message ?? ''))).toBe(false)
  })
})
