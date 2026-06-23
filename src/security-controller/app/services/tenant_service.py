"""Tenant registry, operator↔tenant membership & invites (LLD-26 §6 / WS-D).

This is the *foundation* the rest of multi-tenancy depends on:

* :class:`TenantStore` — ``sentra-tenants``: the registry row that, crucially,
  carries the authoritative per-tenant ``identity_mode`` (the rollout control
  WS-A/WS-B read) and ``status`` (active|suspended|deleting|purged).
* :class:`MemberStore` — ``sentra-tenant-members``: the (operator_sub, tenant)
  pairs + role that the control-plane dependency resolves a request's tenant
  from. Invites are time-boxed rows in the same table (TTL'd, single-use).

Tenant ids are **Sentra-derived immutable slugs** (``t_<base32>``), never
customer free text, and reserved ids are rejected at creation (§6.2 anti-takeover).
"""
from __future__ import annotations

import hashlib
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from botocore.exceptions import ClientError

from app.config import settings
from app.utils import tenancy
from app.utils.clients import get_clients

logger = logging.getLogger(__name__)

VALID_STATUSES = ("active", "suspended", "deleting", "purged")
VALID_PLANS = ("trial", "dedicated", "enterprise")
VALID_ROLES = ("owner", "admin", "editor", "viewer")
_INVITE_PREFIX = "_invite#"

# Free-mail domains may never be used for a verified-domain claim (§6.2) — they
# would let anyone mint a tenant for "gmail.com". They join only via invite.
FREE_MAIL_DOMAINS = frozenset(
    {
        "gmail.com", "googlemail.com", "yahoo.com", "outlook.com", "hotmail.com",
        "live.com", "icloud.com", "aol.com", "proton.me", "protonmail.com",
        "gmx.com", "mail.com", "yandex.com", "zoho.com", "pm.me",
    }
)


def _now_ms() -> int:
    return int(time.time() * 1000)


class TenantError(ValueError):
    """A tenant-lifecycle precondition failed (reserved id, bad status, …)."""


def mint_tenant_id() -> str:
    """A short, collision-resistant, immutable slug. Lowercase base32 of 64 bits
    of randomness → ``t_<13 chars>``. Never customer-chosen (§6.2)."""
    alphabet = "0123456789abcdefghjkmnpqrstvwxyz"  # Crockford-ish, no i/l/o/u
    n = secrets.randbits(64)
    out = []
    for _ in range(13):
        n, rem = divmod(n, 32)
        out.append(alphabet[rem])
    return "t_" + "".join(reversed(out))


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
@dataclass
class Tenant:
    tenant_id: str
    display_name: str
    status: str = "active"
    plan: str = "trial"
    identity_mode: str = "off"
    quota: Dict[str, int] = field(default_factory=lambda: {"max_agents": 25, "max_validate_rps": 50})
    deletion_cursor: Dict[str, str] = field(default_factory=dict)
    created_at: int = 0
    created_by: str = ""

    @classmethod
    def from_item(cls, item: dict) -> "Tenant":
        return cls(
            tenant_id=item["tenant_id"],
            display_name=item.get("display_name", ""),
            status=item.get("status", "active"),
            plan=item.get("plan", "trial"),
            identity_mode=item.get("identity_mode", "off"),
            quota={k: int(v) for k, v in (item.get("quota") or {}).items()},
            deletion_cursor=dict(item.get("deletion_cursor") or {}),
            created_at=int(item.get("created_at", 0)),
            created_by=item.get("created_by", ""),
        )


@dataclass
class Membership:
    operator_sub: str
    tenant_id: str
    role: str
    is_primary: bool = False
    invited_by: str = ""
    created_at: int = 0

    @classmethod
    def from_item(cls, item: dict) -> "Membership":
        return cls(
            operator_sub=item["operator_sub"],
            tenant_id=item["tenant_id"],
            role=item.get("role", "viewer"),
            is_primary=bool(item.get("is_primary", False)),
            invited_by=item.get("invited_by", ""),
            created_at=int(item.get("created_at", 0)),
        )


# --------------------------------------------------------------------------- #
# Tenant registry
# --------------------------------------------------------------------------- #
class TenantStore:
    def __init__(self) -> None:
        self._dynamodb = get_clients().dynamodb_resource()

    def _table(self):
        return self._dynamodb.Table(settings.dynamodb_tenants_table)

    def create(
        self,
        display_name: str,
        plan: str = "trial",
        created_by: str = "",
        tenant_id: Optional[str] = None,
        identity_mode: str = "off",
        quota: Optional[Dict[str, int]] = None,
    ) -> Tenant:
        """Mint (or accept a pre-derived) tenant id and persist the row.
        Rejects reserved ids and customer free-text ids (must match the minted
        slug shape). Idempotency: a put with ``attribute_not_exists`` so a retried
        create can't silently clobber an existing tenant."""
        tid = tenant_id or mint_tenant_id()
        if tenancy.is_reserved_tenant(tid):
            raise TenantError(f"reserved tenant id rejected: {tid!r}")
        if not _is_valid_slug(tid):
            raise TenantError(f"tenant id must be a Sentra-derived slug, got {tid!r}")
        if plan not in VALID_PLANS:
            raise TenantError(f"invalid plan {plan!r}")
        t = Tenant(
            tenant_id=tid,
            display_name=display_name,
            plan=plan,
            identity_mode=identity_mode if identity_mode in tenancy.IDENTITY_MODES else "off",
            quota=quota or {"max_agents": 25, "max_validate_rps": 50},
            created_at=_now_ms(),
            created_by=created_by,
        )
        try:
            self._table().put_item(
                Item={
                    "tenant_id": t.tenant_id,
                    "display_name": t.display_name,
                    "status": t.status,
                    "plan": t.plan,
                    "identity_mode": t.identity_mode,
                    "quota": t.quota,
                    "deletion_cursor": {},
                    "created_at": t.created_at,
                    "created_by": t.created_by,
                },
                ConditionExpression="attribute_not_exists(tenant_id)",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise TenantError(f"tenant {tid!r} already exists") from exc
            raise
        return t

    def get(self, tenant_id: str) -> Optional[Tenant]:
        item = self._table().get_item(Key={"tenant_id": tenant_id}).get("Item")
        return Tenant.from_item(item) if item else None

    def list_all(self, limit: int = 200) -> List[Tenant]:
        """Cross-tenant scan — only the platform-admin console (`_platform`) path
        may call this."""
        resp = self._table().scan(Limit=limit)
        return [Tenant.from_item(i) for i in resp.get("Items", [])]

    def set_status(self, tenant_id: str, status: str) -> None:
        if status not in VALID_STATUSES:
            raise TenantError(f"invalid status {status!r}")
        # `purged` is a terminal tombstone — never resurrect a purged tenant.
        self._table().update_item(
            Key={"tenant_id": tenant_id},
            UpdateExpression="SET #s = :s, updated_at = :u",
            ConditionExpression="attribute_exists(tenant_id) AND #s <> :purged",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": status, ":u": _now_ms(), ":purged": "purged"},
        )

    def set_identity_mode(self, tenant_id: str, mode: str) -> None:
        if mode not in tenancy.IDENTITY_MODES:
            raise TenantError(f"invalid identity_mode {mode!r}")
        self._table().update_item(
            Key={"tenant_id": tenant_id},
            UpdateExpression="SET identity_mode = :m, updated_at = :u",
            ConditionExpression="attribute_exists(tenant_id)",
            ExpressionAttributeValues={":m": mode, ":u": _now_ms()},
        )

    def set_deletion_cursor(self, tenant_id: str, cursor: Dict[str, str]) -> None:
        self._table().update_item(
            Key={"tenant_id": tenant_id},
            UpdateExpression="SET deletion_cursor = :c",
            ExpressionAttributeValues={":c": cursor},
        )

    def mark_purged(self, tenant_id: str) -> None:
        self._table().update_item(
            Key={"tenant_id": tenant_id},
            UpdateExpression="SET #s = :s, purged_at = :u",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "purged", ":u": _now_ms()},
        )


# --------------------------------------------------------------------------- #
# Membership + invites
# --------------------------------------------------------------------------- #
class MemberStore:
    def __init__(self) -> None:
        self._dynamodb = get_clients().dynamodb_resource()

    def _table(self):
        return self._dynamodb.Table(settings.dynamodb_tenant_members_table)

    def by_operator(self, operator_sub: str) -> List[Membership]:
        """All real memberships for an operator (PK query). Invite rows are
        filtered out — they live under a synthetic ``_invite#`` PK and never
        match a real Cognito ``sub``."""
        resp = self._table().query(
            KeyConditionExpression="operator_sub = :o",
            ExpressionAttributeValues={":o": operator_sub},
        )
        return [
            Membership.from_item(i)
            for i in resp.get("Items", [])
            if not i["operator_sub"].startswith(_INVITE_PREFIX)
        ]

    def by_tenant(self, tenant_id: str) -> List[Membership]:
        """All operators in a tenant via the ``tenant-members-index`` GSI."""
        resp = self._table().query(
            IndexName="tenant-members-index",
            KeyConditionExpression="tenant_id = :t",
            ExpressionAttributeValues={":t": tenant_id},
        )
        return [
            Membership.from_item(i)
            for i in resp.get("Items", [])
            if not i["operator_sub"].startswith(_INVITE_PREFIX)
        ]

    def get(self, operator_sub: str, tenant_id: str) -> Optional[Membership]:
        item = self._table().get_item(
            Key={"operator_sub": operator_sub, "tenant_id": tenant_id}
        ).get("Item")
        return Membership.from_item(item) if item else None

    def add(
        self,
        operator_sub: str,
        tenant_id: str,
        role: str,
        is_primary: bool = False,
        invited_by: str = "",
        allow_replace: bool = False,
    ) -> Membership:
        """Write a membership. **Create-only by default** — a put can never
        silently overwrite (and thus re-role) an existing (sub, tenant) row, which
        is what made invite-redeem an escalation vector (#1). A deliberate role
        change must go through an explicit path with `allow_replace=True`."""
        if role not in VALID_ROLES:
            raise TenantError(f"invalid role {role!r}")
        item = {
            "operator_sub": operator_sub,
            "tenant_id": tenant_id,
            "role": role,
            "is_primary": is_primary,
            "invited_by": invited_by,
            "created_at": _now_ms(),
        }
        kwargs = {"Item": item}
        if not allow_replace:
            kwargs["ConditionExpression"] = "attribute_not_exists(operator_sub)"
        try:
            self._table().put_item(**kwargs)
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise TenantError("operator already a member of tenant") from exc
            raise
        return Membership.from_item(item)

    def remove(self, operator_sub: str, tenant_id: str) -> None:
        self._table().delete_item(Key={"operator_sub": operator_sub, "tenant_id": tenant_id})

    # ---- invites (single-use, time-boxed) --------------------------------- #
    def create_invite(
        self,
        tenant_id: str,
        email: str,
        role: str,
        invited_by: str,
        ttl_seconds: int = 7 * 24 * 3600,
    ) -> str:
        """Mint an opaque single-use invite token carrying (tenant, role) and
        bound to an email. Only the **sha256** of the token is persisted (the
        token is a bearer secret — a DB read must not yield a usable invite, #7);
        the raw token is returned to the caller once."""
        if role not in VALID_ROLES:
            raise TenantError(f"invalid role {role!r}")
        token = secrets.token_urlsafe(24)
        now = int(time.time())
        self._table().put_item(
            Item={
                "operator_sub": f"{_INVITE_PREFIX}{_hash_token(token)}",
                "tenant_id": tenant_id,
                "role": role,
                "email": email.strip().lower(),
                "invited_by": invited_by,
                "created_at": _now_ms(),
                "ttl": now + ttl_seconds,
            }
        )
        return token

    def redeem_invite(self, token: str, operator_sub: str, redeemer_email: str = "") -> Membership:
        """Consume an invite: verify it, write the membership (create-only), and
        delete the invite (single-use). The invite is **email-bound** — the
        redeemer's verified Cognito email must match the invited email (#7) — and
        it can never replace an existing membership (#1: no silent re-role)."""
        resp = self._table().query(
            KeyConditionExpression="operator_sub = :o",
            ExpressionAttributeValues={":o": f"{_INVITE_PREFIX}{_hash_token(token)}"},
            Limit=1,
        )
        items = resp.get("Items") or []
        if not items:
            raise TenantError("invite invalid or expired")
        invite = items[0]
        # Expired-but-not-yet-reaped (DDB TTL deletion is best-effort/delayed).
        if int(invite.get("ttl", 0)) and int(invite["ttl"]) < int(time.time()):
            raise TenantError("invite invalid or expired")
        # Email binding: the invite is for a specific person, not whoever holds
        # the link. A blank invite email (legacy) is treated as unbound.
        # NOTE (coupling): `redeemer_email` comes from the ALB OIDC token
        # (Cognito `email` claim; the pool requests scope `openid email`). We do
        # NOT yet check `email_verified` — acceptable while Cognito is the sole
        # IdP, but revisit if a federated IdP can assert an unverified email.
        invited_email = (invite.get("email") or "").strip().lower()
        if invited_email and invited_email != (redeemer_email or "").strip().lower():
            raise TenantError("invite is bound to a different email")
        try:
            self._table().delete_item(
                Key={"operator_sub": invite["operator_sub"], "tenant_id": invite["tenant_id"]},
                ConditionExpression="attribute_exists(operator_sub)",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise TenantError("invite already redeemed") from exc
            raise
        # add() is create-only → redeeming an invite for a tenant you already
        # belong to cannot downgrade/upgrade your existing role.
        return self.add(
            operator_sub=operator_sub,
            tenant_id=invite["tenant_id"],
            role=invite["role"],
            is_primary=False,
            invited_by=invite.get("invited_by", ""),
        )


def _hash_token(token: str) -> str:
    """sha256 hex of an invite token — only the hash is stored, so a DB read can
    never yield a redeemable invite (#7). Entropy is in the token (192 bits)."""
    return hashlib.sha256(token.encode()).hexdigest()


def is_free_mail_domain(domain: str) -> bool:
    return (domain or "").strip().lower() in FREE_MAIL_DOMAINS


def _is_valid_slug(tenant_id: str) -> bool:
    """A minted slug is ``t_`` + lowercase base32. Verified-domain labels are
    also accepted (lowercase alnum + dashes, ≤63). Anything else (free text,
    uppercase, ``#``/``/`` delimiters that would corrupt keys) is rejected."""
    # `tenant_id == tenant_id.lower()` is the robust "no uppercase" test —
    # `str.islower()` is False for an all-digit suffix (no cased chars), which a
    # minted `t_<base32>` can legitimately be.
    lower = tenant_id == tenant_id.lower()
    if tenant_id.startswith("t_") and tenant_id[2:].isalnum() and lower:
        return True
    if 1 <= len(tenant_id) <= 63 and all(c.isalnum() or c == "-" for c in tenant_id):
        return lower and not tenant_id.startswith("-")
    return False


# Process-wide singletons.
_tenant_store: Optional[TenantStore] = None
_member_store: Optional[MemberStore] = None


def get_tenant_store() -> TenantStore:
    global _tenant_store
    if _tenant_store is None:
        _tenant_store = TenantStore()
    return _tenant_store


def get_member_store() -> MemberStore:
    global _member_store
    if _member_store is None:
        _member_store = MemberStore()
    return _member_store
