import type { ReactElement, ReactNode } from 'react'
import { render, type RenderOptions, type RenderResult } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'

/**
 * Mount a component under the two providers every console page needs: a FRESH
 * per-call TanStack `QueryClient` (with `retry:false` so a mocked 4xx surfaces on
 * the first attempt instead of retry-storming a test) and a `MemoryRouter` so
 * `Link`/`useParams`/`useNavigate` resolve. A fresh client per test is
 * load-bearing: a shared client would leak the `['auth','context']` cache across
 * the RBAC role-swap tests and make gate assertions flaky (G2.0 footgun).
 */
export function makeTestQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0, staleTime: 0 },
      mutations: { retry: false },
    },
  })
}

export interface RenderWithProvidersOptions extends Omit<RenderOptions, 'wrapper'> {
  /** Initial router history entries (default `['/']`). */
  routerEntries?: string[]
  /** Reuse a specific client (e.g. to pre-seed `['auth','context']`). */
  queryClient?: QueryClient
}

export interface RenderWithProvidersResult extends RenderResult {
  queryClient: QueryClient
}

export function renderWithProviders(
  ui: ReactElement,
  options: RenderWithProvidersOptions = {},
): RenderWithProvidersResult {
  const { routerEntries = ['/'], queryClient = makeTestQueryClient(), ...rest } = options

  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={routerEntries}>{children}</MemoryRouter>
      </QueryClientProvider>
    )
  }

  return { ...render(ui, { wrapper: Wrapper, ...rest }), queryClient }
}
