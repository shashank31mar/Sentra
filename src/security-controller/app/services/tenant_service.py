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


def _normalize_org_name(name: str) -> str:
    """Case/whitespace-insensitive key for org-name resolution (D14). Collapses
    internal runs of whitespace and lowercases so "Acme  Corp" == "acme corp"."""
    return " ".join((name or "").split()).lower()


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
    # Cross-tenant consent (WS-E E3): a platform-admin per-tenant read DENIES unless
    # this tenant has explicitly opted in. Defaults to False — deny-by-default.
    platform_read_consent: bool = False
    # Deterministic local-floor kill-switch, per-tenant override (WS-I I5.3 / LLD 28
    # §5.6). None = inherit the fleet `local_floor_enabled` flag; False = force this
    # tenant onto the hosted /v1/validate path (incident escape hatch for one bad
    # bundle, without a fleet-wide fallback). NEVER means "skip validation".
    local_floor_enabled: Optional[bool] = None
    # DPA-scoped opt-in for the redacted feedback store (WS-E2 / LLD 29 §6.5).
    # Default False — DENY-BY-DEFAULT: a non-opted-in tenant produces NO feedback
    # record (an accidental default-ON is a clause-(b) + consent breach, §6.5
    # FOOTGUN; mirrors the platform_read_consent / local_floor conservative-off
    # posture). Gates ONLY the persisted store; transient PHI redaction is
    # always-on under the BAA (§4.2, no consent gate).
    feedback_opt_in: bool = False
    # Per-tenant high-assurance decision-trail mode (WS-D / LLD 33 §8.1, D3 OPEN
    # ITEM — founder-resolved 2026-07-02). Default False — DENY-BY-DEFAULT, matching
    # the platform_read_consent / feedback_opt_in / local_floor conservative-off
    # posture. When ON, the request runs the whole frontier verdict-neutrally
    # (mode=evaluate_all) so the trail records the deep tier — a VERDICT-NEUTRAL
    # recording knob (invariant vi), NEVER a decision change. Per-session escalate-
    # only override is `request.context["high_assurance_trail"]` (agent-supplied,
    # untrusted → escalate-only). NOT config.py, NOT a global env flag.
    high_assurance_trail: bool = False
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
            platform_read_consent=bool(item.get("platform_read_consent", False)),
            # Absent attribute → None → inherit the fleet flag (WS-I I5.3).
            local_floor_enabled=(None if item.get("local_floor_enabled") is None
                                 else bool(item.get("local_floor_enabled"))),
            # Absent attribute → False (deny-by-default opt-in, §6.5).
            feedback_opt_in=bool(item.get("feedback_opt_in", False)),
            # Absent attribute → False (deny-by-default high-assurance, §8.1).
            high_assurance_trail=bool(item.get("high_assurance_trail", False)),
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

    def resolve_org_to_tenant_id(self, org: str) -> Optional[str]:
        """WS-G G0.2 / D14 (ADR-039): resolve a typed ORG NAME to its opaque
        ``tenant_id`` slug for the public org-first login resolver.

        The typed name is matched against a tenant's ``display_name`` (the one
        human-facing label) OR — belt-and-suspenders — an exact ``tenant_id``.
        Matching is case/space-insensitive on the display name so "Acme Corp",
        "acme corp" and "ACME  CORP" all resolve. Returns ONLY the slug (the
        caller returns nothing else — zero tenant-data leak) or ``None`` on a miss.

        Purged tenants are excluded (a tombstoned org must not resolve). This is a
        table Scan — acceptable at the current small fleet and off the auth hot
        path; if the fleet grows, back it with a normalized-name GSI (follow-up)."""
        needle = _normalize_org_name(org)
        if not needle:
            return None
        # Exact-slug fast path (an operator who pasted / typed the id) — a single
        # get_item. Covers BOTH the minted `t_<slug>` form AND a human-readable
        # tenant_id (e.g. a design-partner slug like "acme"), so an operator who
        # types the org's own id resolves without needing the full display_name.
        # Case-insensitive on the id: tenant_ids are lowercase slugs, so we match
        # the lowercased-trimmed needle. Purged tenants never resolve (fail-secure).
        row = self._table().get_item(Key={"tenant_id": needle}).get("Item")
        if row and row.get("status") != "purged":
            return row["tenant_id"]
        # Name match: scan display_name (small fleet). Deterministic — first row
        # whose normalized display_name equals the needle wins.
        resp = self._table().scan(
            ProjectionExpression="tenant_id, display_name, #s",
            ExpressionAttributeNames={"#s": "status"},
        )
        for item in resp.get("Items", []):
            if item.get("status") == "purged":
                continue
            if _normalize_org_name(item.get("display_name", "")) == needle:
                return item["tenant_id"]
        return None

    def list_all(self) -> List[Tenant]:
        """Return EVERY tenant in the registry — only the platform-admin console
        (`_platform`) path may call this.

        Paginates through ALL scan pages (accumulating ``LastEvaluatedKey``) rather
        than returning an arbitrary first ``Limit=200`` window. The platform list
        route sorts/filters/pages over the TRUE fleet, so ``count``/``total`` must be
        the real tenant count — a single truncated page would silently under-report a
        >200-tenant fleet (contradicting the route's "large fleet served in stable
        pages" contract) and hide most tenants from sort/filter.

        This is ONE logical batched scan of a SINGLE table (bounded by fleet size),
        NOT a per-tenant fan-out — that O(N)-round-trips pattern is the overview-latency
        incident this deliberately avoids. A DynamoDB scan page truncates at 1 MB and
        returns ``LastEvaluatedKey`` for the remainder, so the loop is required for
        correctness; without a hard ceiling the fleet size is the only bound (that is
        the intended semantics — the platform console must see every tenant)."""
        table = self._table()
        tenants: List[Tenant] = []
        start_key: Optional[Dict] = None
        while True:
            kwargs: Dict = {}
            if start_key is not None:
                kwargs["ExclusiveStartKey"] = start_key
            resp = table.scan(**kwargs)
            tenants.extend(Tenant.from_item(i) for i in resp.get("Items", []))
            start_key = resp.get("LastEvaluatedKey")
            if not start_key:
                break
        return tenants

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

    def set_display_name(self, tenant_id: str, display_name: str) -> None:
        """Rename a tenant (the one free-text, human-facing tenant attribute).
        Trimmed + length-bounded; a blank name is rejected so a PATCH can't wipe
        the label to empty."""
        name = (display_name or "").strip()
        if not name:
            raise TenantError("display_name must not be blank")
        if len(name) > 128:
            raise TenantError("display_name must be <= 128 characters")
        self._table().update_item(
            Key={"tenant_id": tenant_id},
            UpdateExpression="SET display_name = :n, updated_at = :u",
            ConditionExpression="attribute_exists(tenant_id)",
            ExpressionAttributeValues={":n": name, ":u": _now_ms()},
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

    def set_platform_read_consent(self, tenant_id: str, consent: bool) -> None:
        """Grant/revoke this tenant's consent for platform-admin cross-tenant reads
        (WS-E E3). Owner- or platform-gated at the route; deny-by-default."""
        self._table().update_item(
            Key={"tenant_id": tenant_id},
            UpdateExpression="SET platform_read_consent = :c, updated_at = :u",
            ConditionExpression="attribute_exists(tenant_id)",
            ExpressionAttributeValues={":c": bool(consent), ":u": _now_ms()},
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
