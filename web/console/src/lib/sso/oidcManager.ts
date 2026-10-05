/**
 * OIDC authentication manager (ADR-SSO).
 *
 * Wraps `oidc-client-ts` UserManager with the config from `/auth/config.json`.
 * Only instantiated in OIDC mode — in ALB-Cognito mode this module is never imported
 * (tree-shaken out of the production bundle).
 *
 * SECURITY: Uses PKCE (Proof Key for Code Exchange) — the only acceptable flow for
 * public SPA clients. No client secret is stored in the browser.
 */

import { UserManager, WebStorageStateStore, User } from 'oidc-client-ts';
import { OidcConfig } from './config';

let userManager: UserManager | null = null;

export function initOidcManager(config: OidcConfig): void {
  if (userManager) {
    return;
  }

  const storage = config.token_storage === 'localStorage' ? window.localStorage : window.sessionStorage;

  userManager = new UserManager({
    authority: config.authority,
    client_id: config.client_id,
    redirect_uri: config.redirect_uri,
    post_logout_redirect_uri: config.post_logout_redirect_uri,
    response_type: config.response_type ?? 'code',
    scope: config.scope ?? 'openid profile email',
    automaticSilentRenew: config.silent_renew ?? true,
    silent_redirect_uri: window.location.origin + '/auth/silent-renew.html',
    userStore: new WebStorageStateStore({ store: storage }),
    extraQueryParams: config.extra_authorize_params ?? {}
  });
}

export function getOidcManager(): UserManager | null {
  return userManager;
}

export function getAccessToken(): string | null {
  // oidc-client-ts stores the token, but we can only get it synchronously if we read from storage,
  // or via getUser() asynchronously. However, userManager doesn't expose a sync get token method.
  // Actually, we can read the user from session/local storage, but the best practice with oidc-client-ts
  // is to await getUser(). Since getAccessToken is usually needed synchronously for fetch interceptors,
  // we might need a workaround or rely on the cached user if any.
  // We can fetch from storage manually or use userManager.getUser() sync hack, but let's try reading from storage.
  // Alternatively, return null and make it async, but the prompt asks for `getAccessToken(): string | null`.
  
  // A simple hack to get it synchronously is to parse the user from the storage store we defined.
  // If userManager is initialized, we can use it.
  if (!userManager) return null;
  
  try {
    const key = `oidc.user:${userManager.settings.authority}:${userManager.settings.client_id}`;
    const storageStore = userManager.settings.userStore;
    // userStore is async, wait. WebStorageStateStore is sync underneath.
    // For a sync getAccessToken we might just read window.sessionStorage or window.localStorage directly
    const storage = window.sessionStorage.getItem(key) || window.localStorage.getItem(key);
    if (storage) {
      const parsed = JSON.parse(storage);
      return parsed.access_token || null;
    }
  } catch (e) {
    console.error('Error getting access token synchronously', e);
  }
  return null;
}

export async function getOidcUser(): Promise<User | null> {
  if (!userManager) return null;
  return userManager.getUser();
}

export async function handleCallback(): Promise<User> {
  if (!userManager) throw new Error('OIDC Manager not initialized');
  return userManager.signinCallback();
}

export async function oidcSignIn(): Promise<void> {
  if (!userManager) throw new Error('OIDC Manager not initialized');
  return userManager.signinRedirect();
}

export async function oidcSignOut(): Promise<void> {
  if (!userManager) throw new Error('OIDC Manager not initialized');
  return userManager.signoutRedirect();
}
