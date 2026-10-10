import { useEffect, useState } from 'react'
import { QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider } from 'react-router-dom'
import { queryClient } from './queryClient'
import { router } from './router'
import { loadAuthConfig } from '../lib/sso/config'
import { initOidcManager } from '../lib/sso/oidcManager'
import { LoadingState } from '../components/ui/states'

/**
 * Root application component.
 *
 * On mount, loads the SSO config from `/auth/config.json`. In OIDC mode,
 * initialises the oidc-client-ts UserManager before rendering the router
 * (so auth state is available before any guarded route mounts). In ALB-Cognito
 * mode (or when the config file is missing), the existing flow is unchanged.
 */
export default function App() {
  const [ready, setReady] = useState(false)

  useEffect(() => {
    loadAuthConfig().then((config) => {
      if (config.auth_mode === 'oidc' && config.oidc) {
        initOidcManager(config.oidc)
      }
      setReady(true)
    })
  }, [])

  if (!ready) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-bg">
        <LoadingState label="Loading…" />
      </div>
    )
  }

  return (
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  )
}
