/**
 * OIDC claims → Sentra identity mapping (ADR-SSO).
 *
 * Different IdPs put identity attributes in different claim names:
 *  - Azure AD: `preferred_username` for email, `roles` for groups
 *  - Okta: `email`, `groups`
 *  - Keycloak: `email`, `realm_access.roles`
 *
 * The `claims_mapping` config lets operators remap without code changes.
 */

import { CurrentUser } from '../../types/api';
import { OidcConfig } from './config';

export function mapOidcClaims(profile: Record<string, unknown>, mapping?: OidcConfig['claims_mapping']): CurrentUser {
  const defaultMapping = {
    email: 'email',
    name: 'name',
    groups: 'groups',
    username: 'preferred_username'
  };

  const currentMapping = { ...defaultMapping, ...mapping };

  const getClaim = (key: string): unknown => {
    // Basic support for nested claims, e.g. "realm_access.roles"
    return key.split('.').reduce((acc: any, part: string) => acc?.[part], profile);
  };

  const emailValue = getClaim(currentMapping.email);
  const nameValue = getClaim(currentMapping.name);
  const usernameValue = getClaim(currentMapping.username);
  const groupsValue = getClaim(currentMapping.groups);

  let groups: string[] = [];
  if (Array.isArray(groupsValue)) {
    groups = groupsValue.map(String);
  } else if (typeof groupsValue === 'string') {
    groups = [groupsValue];
  }

  return {
    email: typeof emailValue === 'string' ? emailValue : null,
    name: typeof nameValue === 'string' ? nameValue : null,
    username: typeof usernameValue === 'string' ? usernameValue : null,
    groups: groups
  };
}
