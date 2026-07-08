import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

// FR-13.1 (G1.2) — the cosmetic email-domain tenant label (`tenantLabelForDisplay`,
// formerly `tenantOf`) is DISPLAY-ONLY. These `no-restricted-syntax` selectors make
// its re-introduction into any scoping sink (query keys / http layer / RBAC / the
// tenant-header setter) un-mergeable: `npm run lint` (the CI gate) fails on it.
//
// LIMIT (documented, not over-claimed): argument selectors catch the DIRECT-call
// form `http.get(k, tenantOf(u))`. They do NOT catch launder-through-a-variable
// (`const t = tenantOf(u); http.get(k, t)`). The real authority guard is
// server-side (G1.3 — resolution derives from membership, never the domain); this
// lint is defense-in-depth against the obvious re-introduction, not interprocedural
// proof. The label callee alternation matches both the new and old names so a
// stray re-add of `tenantOf` is also flagged.
const LABEL_CALLEE = /^(tenantLabelForDisplay|tenantOf)$/
const FR131_MSG =
  'FR-13.1: the cosmetic tenant label (tenantLabelForDisplay) is display-only — it must NEVER flow into a query key, the http layer, an RBAC check, or the tenant header. The authoritative tenant is server-derived from membership.'

const tenantLabelGuardRules = {
  'no-restricted-syntax': [
    'error',
    // Passed into a query key (queryKeys.<domain>.<fn>(… label(u) …)).
    {
      selector: `CallExpression[callee.object.object.name='queryKeys'] > CallExpression[callee.name=${LABEL_CALLEE}]`,
      message: FR131_MSG,
    },
    {
      selector: `CallExpression[callee.object.name='queryKeys'] > CallExpression[callee.name=${LABEL_CALLEE}]`,
      message: FR131_MSG,
    },
    // Passed into the fetch layer (http.{get,post,put,patch,del}(…, label(u))). `del` is the real name.
    {
      selector: `CallExpression[callee.object.name='http'][callee.property.name=/^(get|post|put|patch|del)$/] > CallExpression[callee.name=${LABEL_CALLEE}]`,
      message: FR131_MSG,
    },
    // Passed into an RBAC check (can/rbacCan/roleSatisfies(label(u), …) or useCan().can(…)).
    {
      selector: `CallExpression[callee.name=/^(can|rbacCan|roleSatisfies)$/] > CallExpression[callee.name=${LABEL_CALLEE}]`,
      message: FR131_MSG,
    },
    {
      selector: `CallExpression[callee.property.name='can'] > CallExpression[callee.name=${LABEL_CALLEE}]`,
      message: FR131_MSG,
    },
    // Passed into the tenant-header setter (setActiveTenant(label(u))).
    {
      selector: `CallExpression[callee.name='setActiveTenant'] > CallExpression[callee.name=${LABEL_CALLEE}]`,
      message: FR131_MSG,
    },
  ],
}

export default defineConfig([
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    languageOptions: {
      globals: globals.browser,
    },
    // NOTE: M-G2/§5.5 extends THIS SAME `rules` object (do not add a second config
    // object for the `**/*.{ts,tsx}` glob — last-wins would silently drop these).
    rules: {
      ...tenantLabelGuardRules,
    },
  },
])
