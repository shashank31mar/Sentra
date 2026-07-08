# Frontend Stack — `web/console` (approved)

**Status**: Approved (records the established stack of the live `web/console` SPA; not a fresh pick).
**Consumed by**: `senior-sde-frontend` (code-loop) as its approved-stack artifact for WS-G (lld/40).
**Last updated**: 2026-07-08

## Why this doc exists
`web/console` is a mature, in-production React SPA. WS-G **extends** it — it does **not** re-pick the
stack. This file records the already-shipped choices so the frontend coder builds in-idiom and does not
stop to ask. The only genuinely net-new stack decision is the **test harness** (none existed) — dictated
by WS-G task **G2.0** (`tasks/serverless-edition/ws-g-console.md:262-268`).

## The stack (verified against `web/console/package.json`)
| Concern | Choice | Version | Notes |
|---|---|---|---|
| UI framework | **React** | `^19.2.6` | function components + hooks |
| Language | **TypeScript** | `~6.0.2` | `verbatimModuleSyntax`, strict-ish (`noUnusedLocals`) |
| Build | **Vite** | `^8.0.12` + `@vitejs/plugin-react ^6` | dev proxy injects `x-api-key` for `/v1` |
| Router | **react-router-dom** | `^7.1.1` | `createBrowserRouter` **data router** (`app/router.tsx`) |
| Server state | **@tanstack/react-query** | `^5.62.0` | the only data/state lib; local state = `useState` |
| Styling | **Tailwind CSS v4** | `^4.3.0` (`@tailwindcss/vite`) | **CSS-first**, tokens in `src/styles/index.css` `@theme`; **dark-only** |
| Charts | **chart.js** + **react-chartjs-2** | `^4.4.7` / `^5.3.0` | |
| Icons | **@tabler/icons-react** | `^3.34.0` | |
| Lint | **ESLint** flat config | `^10.3.0` + `typescript-eslint ^8.59` | `eslint.config.js` |
| UI primitives | **hand-rolled** in `src/components/ui/` | — | Button/Card/Table/Modal/Toast/badges/states/… — reuse, no new lib |

**No** redux/zustand/swr, **no** MUI/shadcn/radix, **no** aws-amplify/oidc lib (auth is the ALB Cognito
edge; the SPA holds no bearer token — same-origin cookie + `X-Aegion-Tenant` preference header only).

## Test harness (net-new — WS-G G2.0 mandate)
| Concern | Choice | Rationale |
|---|---|---|
| Test runner | **Vitest** | native Vite integration; shares the app's transform/resolve config |
| Component testing | **@testing-library/react** + `@testing-library/user-event` + `@testing-library/jest-dom` | idiomatic React 19 testing; behavior over implementation |
| DOM env | **jsdom** | required for component tests |
| Coverage | **@vitest/coverage-v8** | |
| API/network mocking | in-repo **`src/mocks/mockRouter.ts` fetch adapter** (already exists) + per-test fakes | **no MSW** — reuse the existing code-level mock router; keep the dep surface minimal |

Config: new `vitest.config.ts` (reuse the Vite plugin/resolve config), new `src/test/setup.ts`
(jest-dom matchers + a `renderWithProviders` that mounts a **fresh per-test `QueryClient` with `retry:false`**).
Add `"test": "vitest run"` (+ `"test:watch": "vitest"`) to `package.json`. G2.0 lands **first** — every other
WS-G Vitest is un-runnable without it.

## Conventions the coder must follow (in-idiom)
- **API layer**: one module per domain in `src/lib/api/*`, mirrored by a hook in `src/lib/query/*`, with
  keys registered in `src/lib/queryKeys.ts`. New endpoints follow this triple.
- **HTTP**: go through `src/lib/http.ts` (`http.get/post/put/patch/del`) — never raw `fetch`. Errors are
  `ApiException` normalized via `normalizeErrorBody`.
- **RBAC render-gate**: `src/lib/rbac.ts` + `useCan()`/`usePlatformCan()` — **UX only, never the security
  boundary** (server `require_role`/`require_platform` is the boundary). Gated control = **not rendered**,
  not disabled.
- **Routing**: paths in `app/routes.ts`, lazy imports in `app/lazyPages.ts`, nav in `app/navConfig.ts`,
  route objects in `app/router.tsx`. Static routes precede param routes.
- **Styling**: use the existing `@theme` tokens + `components/ui/` primitives; do not introduce a new CSS
  system.
- **Build gate** (per milestone): `npm run build` (`tsc -b && vite build`) + `npm run lint` + `npm run test`
  must all pass.
