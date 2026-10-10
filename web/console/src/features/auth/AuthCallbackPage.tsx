import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { handleCallback, oidcSignIn } from '../../lib/sso/oidcManager'
import { LoadingState } from '../../components/ui/states'

/**
 * OIDC authorization callback page (ADR-SSO).
 *
 * The IdP redirects here after the operator authenticates. This page:
 *  1. Exchanges the authorization code for tokens (via oidc-client-ts).
 *  2. On success, navigates to /overview (the console home).
 *  3. On error, shows a retry prompt — never leaves the operator stranded.
 *
 * This page is only reached in OIDC mode; ALB-Cognito handles callbacks at the
 * infrastructure level and never routes through the SPA.
 */
export default function AuthCallbackPage() {
  const navigate = useNavigate()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let mounted = true

    async function processCallback() {
      try {
        await handleCallback()
        if (mounted) {
          navigate('/overview', { replace: true })
        }
      } catch (err) {
        console.error('[SSO] Callback processing failed:', err)
        if (mounted) {
          setError(
            err instanceof Error
              ? err.message
              : 'Sign-in failed. Please try again.',
          )
        }
      }
    }

    processCallback()
    return () => { mounted = false }
  }, [navigate])

  if (error) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-bg text-ink">
        <div className="max-w-md w-full text-center p-6">
          <div
            className="mx-auto w-14 h-14 rounded-2xl grid place-items-center mb-5"
            style={{
              background: 'rgba(255,0,128,0.1)',
              border: '1px solid rgba(255,0,128,0.25)',
            }}
          >
            <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-[#FF0080]">
              <circle cx="12" cy="12" r="10" />
              <line x1="15" y1="9" x2="9" y2="15" />
              <line x1="9" y1="9" x2="15" y2="15" />
            </svg>
          </div>

          <h2 className="text-xl font-semibold font-display text-white mb-2">
            Sign-in failed
          </h2>
          <p className="text-sm text-muted mb-6 font-mono">{error}</p>

          <div className="flex flex-col gap-3">
            <button
              type="button"
              onClick={() => oidcSignIn()}
              className="w-full h-10 inline-flex items-center justify-center gap-2 rounded-xl text-sm font-bold text-white transition-all cursor-pointer"
              style={{
                background: '#0FFFFF',
                color: '#0B141C',
              }}
            >
              Try again
            </button>
            <a
              href="/"
              className="text-sm text-secondary hover:text-white transition-colors"
            >
              Back to home
            </a>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex items-center justify-center min-h-screen bg-bg">
      <LoadingState label="Completing sign-in…" />
    </div>
  )
}
