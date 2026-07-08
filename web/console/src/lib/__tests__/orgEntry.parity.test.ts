import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'
import { RESOLVE_ORG_PATH, POST_BIND_REDIRECT } from '../orgEntry'
import { ACTIVE_TENANT_STORAGE_KEY } from '../tenant'

/**
 * G2.12 / ADR-039 — enforce the org.html ↔ orgEntry.ts LOCKSTEP the docstrings claim.
 *
 * `public/org.html` is a standalone, un-bundled static page (it loads NO hashed
 * `/assets/*` chunk — those fall through to the priority-10 Cognito auth rule and
 * would 401 an unauthenticated visitor), so it CANNOT import `orgEntry.ts`; it
 * re-implements the resolve→stash→redirect flow inline. That duplication is a
 * silent-drift hazard for a SECURITY-SENSITIVE path (the org-first tenant bind):
 * if one side changes the storage key / resolve endpoint / redirect target / the
 * stash-only-`tenant_id` rule / the 404-vs-non-ok branch and the other doesn't,
 * the bind breaks or leaks with nothing catching it.
 *
 * Before this test, `orgEntry.test.ts` only exercised the TS functions and never
 * read `org.html`, so the docstring's "kept in lockstep by the test contract"
 * claim was FALSE. This is that contract: it READS the inline `<script>` and
 * asserts every load-bearing invariant matches the TS source. Tweak one side and
 * this fails. (Mirrors the fs-read cross-artifact gate in `rbac.parity.test.ts`.)
 */

const ORG_HTML_PATH = path.join(process.cwd(), 'public', 'org.html')

function loadOrgHtmlScript(): string {
  const html = fs.readFileSync(ORG_HTML_PATH, 'utf-8')
  const m = /<script>([\s\S]*?)<\/script>/.exec(html)
  if (!m) throw new Error(`no inline <script> found in ${ORG_HTML_PATH}`)
  return m[1]
}

describe('org.html ↔ orgEntry.ts parity (G2.12 / ADR-039)', () => {
  const script = loadOrgHtmlScript()

  it('uses the SAME sessionStorage key as tenant.ts (aegion.activeTenant)', () => {
    // The canonical key — asserted literally so a typo on either side is caught,
    // and cross-checked against the TS module's exported constant.
    expect(ACTIVE_TENANT_STORAGE_KEY).toBe('aegion.activeTenant')
    expect(script).toMatch(/var\s+TENANT_KEY\s*=\s*['"]aegion\.activeTenant['"]/)
    // The stash is keyed by that same variable, not a hardcoded second string.
    expect(script).toMatch(/sessionStorage\.setItem\(\s*TENANT_KEY\s*,/)
  })

  it('resolves against the SAME public endpoint path as RESOLVE_ORG_PATH', () => {
    expect(RESOLVE_ORG_PATH).toBe('/public/resolve-org')
    expect(script).toContain(`fetch('${RESOLVE_ORG_PATH}?org=' + encodeURIComponent(`)
  })

  it('stashes ONLY the resolved tenant_id — never the typed org name', () => {
    // What is written to storage must be data.tenant_id.
    expect(script).toMatch(/sessionStorage\.setItem\(\s*TENANT_KEY\s*,\s*data\.tenant_id\s*\)/)
    // Fail-secure: the typed org (the `org` var / input value) must NEVER be the
    // stashed value — that would leak the human-typed name as if it were authority.
    expect(script).not.toMatch(/setItem\([^)]*,\s*org\s*\)/)
    expect(script).not.toMatch(/setItem\([^)]*input\.value/)
  })

  it('redirects to the SAME post-bind target as POST_BIND_REDIRECT', () => {
    expect(POST_BIND_REDIRECT).toBe('/overview')
    expect(script).toContain(`window.location = '${POST_BIND_REDIRECT}'`)
  })

  it('keeps the 404 "not found" branch distinct from the non-ok "unavailable" branch', () => {
    // 404 → friendly "not found", stay put, stash nothing (never advance to Cognito).
    expect(script).toMatch(/res\.status\s*===?\s*404/)
    expect(script).toContain('org not found — check spelling')
    // Any other non-ok → "temporarily unavailable" (a different message + branch).
    expect(script).toMatch(/if\s*\(\s*!res\.ok\s*\)/)
    expect(script).toContain('sign-in temporarily unavailable — try again')
    // The two messages must not be the same string (the branch distinction is the point).
    const notFound = 'org not found — check spelling'
    const unavailable = 'sign-in temporarily unavailable — try again'
    expect(notFound).not.toBe(unavailable)
  })

  it('never advances (no stash/redirect) when the body lacks a tenant_id', () => {
    // Guard mirrors submitOrg: `if (!data || !data.tenant_id) return;` before stash.
    expect(script).toMatch(/if\s*\(\s*!data\s*\|\|\s*!data\.tenant_id\s*\)\s*return/)
  })
})
