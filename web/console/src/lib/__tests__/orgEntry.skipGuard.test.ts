import { describe, it, expect } from 'vitest'
import fs from 'node:fs'
import path from 'node:path'

/**
 * WS-G / lld/40 — the org.html skip-if-authenticated LOOP-BREAK contract.
 *
 * RCA (confirmed): the pre-fix `skipIfAuthenticated()` redirected to `/overview`
 * on Cognito LIVENESS ALONE (a non-empty `/whoami` email). But the ALB session
 * cookie OUTLIVES the per-tab `sessionStorage` tenant binding, so a signed-in
 * multi-membership operator who reopens the tab was simultaneously
 * "authenticated" (skip → `/overview`) AND "unbound multi-membership"
 * (`RequireBoundTenant` → back to `/org.html`): an INFINITE `org.html ⇄ /overview`
 * loop.
 *
 * The fix makes the skip predicate the NEGATION of that loop condition, which
 * requires `is_platform` + `memberships` — fields `/whoami` does NOT carry — so the
 * guard MUST consult `GET /v1/me` (the same MeContext the SPA's
 * `RequireBoundTenant`/`RequireCustomerRoot` guards read) and gate the `/overview`
 * redirect on a `needsToPick`-style condition instead of a bare email check.
 *
 * This test reads the inline `<script>` (org.html is un-bundled static HTML, same
 * fs-read idiom as `orgEntry.parity.test.ts`) and asserts the guard consults
 * membership/platform state. It is NON-VACUOUS by construction: EVERY assertion
 * below fails against the pre-fix `/whoami`-liveness-only guard (verified by
 * pointing it at the reverted org.html — see the file's test report).
 */

const ORG_HTML_PATH = path.join(process.cwd(), 'public', 'org.html')

function loadOrgHtmlScript(): string {
  const html = fs.readFileSync(ORG_HTML_PATH, 'utf-8')
  const m = /<script>([\s\S]*?)<\/script>/.exec(html)
  if (!m) throw new Error(`no inline <script> found in ${ORG_HTML_PATH}`)
  return m[1]
}

/** Isolate the skip guard so an assertion can't accidentally match the submit handler. */
function loadSkipGuard(): string {
  const script = loadOrgHtmlScript()
  const start = script.indexOf('function skipIfAuthenticated()')
  if (start < 0) throw new Error('skipIfAuthenticated() guard not found in org.html')
  const end = script.indexOf("form.addEventListener('submit'")
  if (end < 0) throw new Error('submit handler not found in org.html (guard boundary)')
  return script.slice(start, end)
}

describe('org.html skip-if-authenticated loop-break (WS-G / lld/40)', () => {
  const guard = loadSkipGuard()

  it('consults GET /v1/me for the skip decision (NOT /whoami-liveness-only)', () => {
    // /v1/me carries is_platform + memberships; /whoami does not — the loop-break
    // predicate is un-computable from /whoami. FAILS against the pre-fix guard,
    // which fetched '/whoami'.
    expect(guard).toContain("fetch('/v1/me'")
    expect(guard).not.toMatch(/fetch\(\s*['"]\/whoami['"]/)
  })

  it('reads membership state (memberships.length) to decide the skip', () => {
    // The bug case is memberships.length > 1. FAILS against the pre-fix guard,
    // which never referenced memberships.
    expect(guard).toContain('memberships')
    // The bug case is a membership count > 1 (derived defensively from me.memberships).
    expect(guard).toMatch(/me\.memberships/)
    expect(guard).toMatch(/membershipCount\s*>\s*1/)
  })

  it('honors the platform carve-out (is_platform) so a platform op is never stranded', () => {
    // Persona 5: is_platform operators have no org to type — they must skip in
    // (→ /overview → RequireCustomerRoot → /platform), never stay on the form.
    // FAILS against the pre-fix guard, which never referenced is_platform.
    expect(guard).toContain('is_platform')
  })

  it('checks the per-tab binding (sessionStorage[TENANT_KEY]) before skipping', () => {
    // A multi-membership operator WITH a binding (persona 4) must skip in; the
    // pre-fix guard never read the binding for the skip decision.
    expect(guard).toMatch(/sessionStorage\.getItem\(\s*TENANT_KEY\s*\)/)
  })

  it('gates the /overview redirect on a needsToPick condition, not an unconditional liveness skip', () => {
    // The redirect must be guarded by a computed skip condition (NOT reachable on
    // liveness alone). We assert the redirect is inside a conditional that
    // references the pick decision. FAILS against the pre-fix guard, whose
    // window.location.replace('/overview') fired whenever the email was non-empty.
    expect(guard).toContain("window.location.replace('/overview')")
    expect(guard).toMatch(/needsToPick/)
    // The redirect fires in the NOT-needsToPick branch (skip in), never uncoditionally.
    expect(guard).toMatch(/if\s*\(\s*!\s*needsToPick\s*\)/)
    // Regression pin: the redirect must NOT be gated on a bare non-empty email check.
    expect(guard).not.toMatch(/email\s*\.\s*trim\(\)\s*!==\s*['"]{2}/)
  })

  it('fails open to the org form on an invalid/unreadable body (never traps a user)', () => {
    // Defensive validation mirrors submitOrg: a non-object body ⇒ do not redirect.
    expect(guard).toMatch(/typeof\s+me\s*!==?\s*['"]object['"]/)
  })
})
