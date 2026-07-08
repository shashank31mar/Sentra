import { describe, it, expect, beforeAll } from 'vitest'
import { Linter, ESLint } from 'eslint'
import path from 'node:path'

/**
 * G1.2 — proves the FR-13.1 `no-restricted-syntax` guard flags the cosmetic tenant
 * label flowing into a scoping sink (query key / http / RBAC / tenant header), and
 * does NOT false-positive on the legitimate display assignment (the AccountMenu shape).
 *
 * The rule config is pulled from the REAL `eslint.config.js` via ESLint's resolved
 * config (calculateConfigForFile) — not a hand-copied duplicate — so the unit test
 * can never drift from what CI runs. We then replay just the `no-restricted-syntax`
 * option through a bare `Linter` for fast per-snippet assertions.
 */
const linter = new Linter()
let guardRules: Linter.RulesRecord

beforeAll(async () => {
  const consoleRoot = process.cwd()
  const eslint = new ESLint({ cwd: consoleRoot })
  const cfg = await eslint.calculateConfigForFile(path.join(consoleRoot, 'src', 'probe.tsx'))
  const opt = cfg.rules?.['no-restricted-syntax']
  expect(opt, 'no-restricted-syntax must be configured in eslint.config.js').toBeTruthy()
  guardRules = { 'no-restricted-syntax': opt as Linter.RuleEntry }
})

function lint(code: string) {
  return linter.verify(code, {
    languageOptions: { ecmaVersion: 2023, sourceType: 'module' },
    rules: guardRules,
  })
}

describe('FR-13.1 tenant-label lint guard (G1.2)', () => {
  it('flags tenantLabelForDisplay passed to http.get', () => {
    const msgs = lint(`http.get(queryKeys.decisions.list({}), tenantLabelForDisplay(user))`)
    expect(msgs.length).toBeGreaterThanOrEqual(1)
    expect(msgs[0].message).toMatch(/FR-13\.1/)
  })

  it('flags the old tenantOf name passed into a query key', () => {
    const msgs = lint(`queryKeys.decisions.list(tenantOf(user))`)
    expect(msgs.length).toBeGreaterThanOrEqual(1)
  })

  it('flags the label passed to can()', () => {
    const msgs = lint(`can(tenantLabelForDisplay(user), 'policies.delete')`)
    expect(msgs.length).toBeGreaterThanOrEqual(1)
  })

  it('flags the label passed to useCan().can()', () => {
    const msgs = lint(`useCan().can(tenantLabelForDisplay(user))`)
    expect(msgs.length).toBeGreaterThanOrEqual(1)
  })

  it('flags the label passed to setActiveTenant', () => {
    const msgs = lint(`setActiveTenant(tenantLabelForDisplay(user))`)
    expect(msgs.length).toBeGreaterThanOrEqual(1)
  })

  it('allows tenantLabelForDisplay assigned to a local var (the AccountMenu display shape)', () => {
    const msgs = lint(`const tenant = tenantLabelForDisplay(user); render(tenant)`)
    expect(msgs).toHaveLength(0)
  })
})
