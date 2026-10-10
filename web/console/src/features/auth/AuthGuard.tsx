import { useEffect, useState, ReactNode } from 'react';
import { isOidcMode, getAuthConfig } from '../../lib/sso/config';
import { getOidcUser, oidcSignIn } from '../../lib/sso/oidcManager';
import { LoadingState } from '../../components/ui/states';

interface AuthGuardProps {
  children: ReactNode;
}

/**
 * Auth guard for OIDC-protected routes (ADR-SSO).
 *
 * In OIDC mode: checks if the user has a valid session via oidc-client-ts.
 * If not, redirects to the IdP login (or shows a login button if auto_redirect is off).
 *
 * In ALB-Cognito mode: renders children immediately (the ALB handles auth at the
 * infrastructure level — the SPA never sees an unauthenticated request).
 */
export function AuthGuard({ children }: AuthGuardProps) {
  const [isAuthenticated, setIsAuthenticated] = useState<boolean>(false);
  const [isLoading, setIsLoading] = useState<boolean>(true);

  useEffect(() => {
    let mounted = true;

    async function checkAuth() {
      if (!isOidcMode()) {
        if (mounted) {
          setIsAuthenticated(true);
          setIsLoading(false);
        }
        return;
      }

      try {
        const user = await getOidcUser();
        const config = getAuthConfig();
        
        if (user && !user.expired) {
          if (mounted) {
            setIsAuthenticated(true);
            setIsLoading(false);
          }
        } else {
          if (config.oidc?.auto_redirect ?? true) {
            await oidcSignIn();
          } else {
            if (mounted) {
              setIsAuthenticated(false);
              setIsLoading(false);
            }
          }
        }
      } catch (error) {
        console.error('Error checking auth state:', error);
        if (mounted) {
          setIsAuthenticated(false);
          setIsLoading(false);
        }
      }
    }

    checkAuth();

    return () => {
      mounted = false;
    };
  }, []);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-bg">
        <LoadingState label="Checking authentication…" />
      </div>
    );
  }

  if (!isAuthenticated && isOidcMode()) {
    return (
      <div className="flex flex-col items-center justify-center min-h-screen bg-bg text-ink p-4">
        <div className="max-w-md w-full text-center">
          <h2 className="text-2xl font-semibold mb-4 text-ink">Authentication Required</h2>
          <p className="text-muted mb-8">Please sign in to access this page.</p>
          <button
            onClick={() => oidcSignIn()}
            className="py-2 px-6 bg-cyan text-slate-900 font-medium rounded hover:opacity-90 transition-opacity"
          >
            Sign in with SSO
          </button>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
