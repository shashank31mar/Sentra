"""
Generic OIDC JWT verifier for customer-deployed SSO (ADR-SSO).

Verifies Bearer tokens from any OIDC-compliant IdP (Azure AD, Okta, Keycloak,
Cognito standalone, etc.) using the IdP's published JWKS. This replaces the
ALB-specific `verify_alb_oidc` path when customers deploy with their own IdP.

SECURITY:
  - Tokens are verified SERVER-SIDE against the IdP's JWKS — never trust
    client-only validation.
  - `iss` (issuer) and `aud` (audience) are PINNED to configured values.
  - JWKS is cached with TTL to handle key rotation gracefully.
  - Clock skew leeway is configurable (default 60s).
"""

import time
import httpx
import jwt
from dataclasses import dataclass


class OidcVerificationError(Exception):
    """Exception raised for any OIDC verification failure."""
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(f"OIDC Verification failed: {reason}")


@dataclass
class OperatorIdentity:
    """Standardized identity extracted from an OIDC token."""
    sub: str
    email: str | None
    name: str | None
    groups: list[str]
    raw_claims: dict


def extract_identity(
    claims: dict,
    email_claim: str = 'email',
    name_claim: str = 'name',
    groups_claim: str = 'groups'
) -> OperatorIdentity:
    """Extract standard identity attributes from raw OIDC claims."""
    # Handle groups if it's a string instead of a list
    groups_val = claims.get(groups_claim, [])
    if isinstance(groups_val, str):
        groups = [groups_val]
    elif isinstance(groups_val, list):
        groups = [str(g) for g in groups_val]
    else:
        groups = []

    return OperatorIdentity(
        sub=str(claims.get('sub', '')),
        email=claims.get(email_claim) or claims.get('upn'),  # fallback to UPN for AAD
        name=claims.get(name_claim),
        groups=groups,
        raw_claims=claims
    )


class OidcVerifier:
    """Verifies OIDC tokens against the configured IdP."""
    
    def __init__(
        self,
        issuer: str,
        audience: str,
        allowed_issuers: list[str] | None = None,
        jwks_cache_ttl: int = 3600,
        clock_skew: int = 60
    ):
        self.issuer = issuer.rstrip('/')
        self.audience = audience
        
        self.allowed_issuers = []
        if allowed_issuers:
            self.allowed_issuers = [i.rstrip('/') for i in allowed_issuers]
        if self.issuer and self.issuer not in self.allowed_issuers:
            self.allowed_issuers.append(self.issuer)
            
        self.jwks_cache_ttl = jwks_cache_ttl
        self.clock_skew = clock_skew
        
        # Caches
        self._jwks_cache: dict | None = None
        self._jwks_cache_time: float = 0
        self._discovery_cache: dict | None = None

    async def _fetch_jwks(self) -> dict:
        """Fetch the JWKS from the IdP. Uses cache if valid."""
        now = time.time()
        
        if self._jwks_cache and (now - self._jwks_cache_time) < self.jwks_cache_ttl:
            return self._jwks_cache

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # 1. Fetch discovery doc if not cached
                if not self._discovery_cache:
                    discovery_url = f"{self.issuer}/.well-known/openid-configuration"
                    r = await client.get(discovery_url)
                    r.raise_for_status()
                    self._discovery_cache = r.json()

                jwks_uri = self._discovery_cache.get("jwks_uri")
                if not jwks_uri:
                    raise OidcVerificationError("IdP discovery document missing jwks_uri")

                # 2. Fetch JWKS
                r = await client.get(jwks_uri)
                r.raise_for_status()
                jwks = r.json()
                
                self._jwks_cache = jwks
                self._jwks_cache_time = now
                return jwks
                
        except httpx.HTTPError as e:
            raise OidcVerificationError(f"Failed to fetch JWKS: {str(e)}")
        except Exception as e:
            raise OidcVerificationError(f"Unexpected error fetching JWKS: {str(e)}")

    async def verify(self, token: str) -> dict:
        """
        Verify the OIDC token signature and standard claims.
        Returns the decoded claims dictionary.
        """
        if not token:
            raise OidcVerificationError("Token is missing")

        # Extract unverified header to get the key ID
        try:
            unverified_header = jwt.get_unverified_header(token)
        except jwt.PyJWTError as e:
            raise OidcVerificationError(f"Invalid token format: {str(e)}")

        kid = unverified_header.get("kid")
        if not kid:
            raise OidcVerificationError("Token header missing 'kid'")

        # Fetch JWKS and find the matching key
        jwks = await self._fetch_jwks()
        
        # Convert JWKS to PyJWT internal format
        # jwt.PyJWKClient could do this automatically, but we want full control
        # over the async HTTP fetch and caching.
        jwk_set = jwt.PyJWKSet.from_dict(jwks)
        
        try:
            # Find the key by kid
            jwk = None
            for key in jwk_set.keys:
                if key.key_id == kid:
                    jwk = key
                    break
            
            if not jwk:
                # If key not found, maybe it was rotated. Force a cache miss on next fetch.
                self._jwks_cache_time = 0
                raise OidcVerificationError(f"Key ID {kid} not found in JWKS")
                
            public_key = jwk.key

            # Verify and decode
            claims = jwt.decode(
                token,
                key=public_key,
                algorithms=["RS256", "ES256"],
                audience=self.audience,
                issuer=self.allowed_issuers,
                leeway=self.clock_skew,
                options={
                    "require": ["exp", "iss", "aud", "sub"],
                }
            )
            return claims
            
        except jwt.ExpiredSignatureError:
            raise OidcVerificationError("Token has expired")
        except jwt.InvalidAudienceError:
            raise OidcVerificationError("Invalid audience")
        except jwt.InvalidIssuerError:
            raise OidcVerificationError("Invalid issuer")
        except jwt.PyJWTError as e:
            raise OidcVerificationError(f"Token verification failed: {str(e)}")
