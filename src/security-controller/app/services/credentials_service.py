"""Agent credential store + hot-path public-key cache (LLD-26 §3 / WS-A A1, A2, A3.1).

Trust model (read before changing anything here)
------------------------------------------------
Credentials are **asymmetric**: an agent holds its private ES256 (P-256) signing
key; Sentra stores only the **public** key. The controller can therefore
*verify* an agent token but can **never mint** one — a compromised controller DB
cannot forge agent identity.

Two collaborators live here:

* :class:`CredentialStore` — DynamoDB CRUD on ``sentra-agent-credentials``
  (PK ``tenant_id`` / SK ``key_id`` = ``{agent_id}#{kid}``) plus the
  ``kid-index`` GSI lookup that is the ONE pre-tenant read (it establishes the
  tenant). Issuance writes the base table; verify reads the GSI.
* :class:`CredentialCache` — an in-process, TTL-bounded LRU keyed by ``kid`` so
  ``/v1/validate`` (the highest-QPS path) does **not** hit the GSI per request
  (a global GSI would funnel every tenant through one partition). A shared
  ``revoked-since`` epoch lets revocation propagate faster than the cache TTL.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from typing import List, Optional

from botocore.exceptions import ClientError

from app.config import settings
from app.utils import tenancy
from app.utils.clients import get_clients

logger = logging.getLogger(__name__)

# Only ES256 (ECDSA P-256) is accepted. Fixed at issuance and re-asserted at
# verify — an attacker must not be able to downgrade `alg` (e.g. to "none").
ALLOWED_ALG = "ES256"

# The revoked-since signal lives as a single reserved row in the credentials
# table itself (PK is a reserved tenant id that can never be a real customer, SK
# fixed). One get_item per refresh interval per task — never per request.
_REVOCATION_PK = "_revocation"
_REVOCATION_SK = "epoch"


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(frozen=True)
class CredentialRecord:
    """A registered public key. Carries no private material."""

    tenant_id: str
    agent_id: str
    kid: str
    public_key: str
    alg: str
    status: str  # active | rotating | revoked
    not_before: int  # epoch ms
    not_after: int  # epoch ms

    @property
    def key_id(self) -> str:
        return f"{self.agent_id}#{self.kid}"

    @property
    def is_usable(self) -> bool:
        """`active` or `rotating` keys can still verify a token (rotation is
        overlap-based); `revoked` never can."""
        return self.status in ("active", "rotating")

    @classmethod
    def from_item(cls, item: dict) -> "CredentialRecord":
        return cls(
            tenant_id=item["tenant_id"],
            agent_id=item["agent_id"],
            kid=item["kid"],
            public_key=item["public_key"],
            alg=item.get("alg", ALLOWED_ALG),
            status=item.get("status", "active"),
            not_before=int(item.get("not_before", 0)),
            not_after=int(item.get("not_after", 0)),
        )


class CredentialValidationError(ValueError):
    """Caller-supplied credential material is malformed (→ HTTP 400)."""


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #
class CredentialStore:
    """DynamoDB access for ``sentra-agent-credentials``. Synchronous (boto3);
    callers on the async hot path must offload via ``asyncio.to_thread`` so the
    request's tenant contextvar is carried (LLD-26 §4.6)."""

    def __init__(self) -> None:
        self._dynamodb = get_clients().dynamodb_resource()

    def _table(self):
        return self._dynamodb.Table(settings.dynamodb_agent_credentials_table)

    # ---- verify path (GSI) ------------------------------------------------ #
    def get_by_kid(self, kid: str) -> Optional[CredentialRecord]:
        """O(1) lookup by the token's `kid` via the ``kid-index`` GSI. This is
        the single pre-tenant read — it *establishes* the tenant."""
        resp = self._table().query(
            IndexName="kid-index",
            KeyConditionExpression="kid = :k",
            ExpressionAttributeValues={":k": kid},
            Limit=1,
        )
        items = resp.get("Items") or []
        if not items:
            return None
        return CredentialRecord.from_item(items[0])

    # ---- issuance / management (base table, tenant-scoped) ---------------- #
    def register(
        self,
        tenant_id: str,
        agent_id: str,
        public_key: str,
        alg: str = ALLOWED_ALG,
        not_after: Optional[int] = None,
        created_by: str = "operator",
    ) -> str:
        """Register a public key; returns the generated globally-unique ``kid``.
        Validates the key is a real ES256/P-256 public key before persisting."""
        if alg != ALLOWED_ALG:
            raise CredentialValidationError(f"alg must be {ALLOWED_ALG}, got {alg!r}")
        _assert_es256_public_key(public_key)

        kid = str(uuid.uuid4())
        now = _now_ms()
        # Default validity: ~1 year. The token lifetime (≤15 min) is the real
        # revocation budget; this is just an outer key-rotation bound.
        na = int(not_after) if not_after else now + 365 * 24 * 3600 * 1000
        item = {
            "tenant_id": tenant_id,
            "key_id": f"{agent_id}#{kid}",
            "kid": kid,
            "agent_id": agent_id,
            "public_key": public_key,
            "alg": ALLOWED_ALG,
            "status": "active",
            "not_before": now,
            "not_after": na,
            "created_at": now,
            "created_by": created_by,
        }
        self._table().put_item(Item=item)
        return kid

    def list_for_agent(self, tenant_id: str, agent_id: str) -> List[CredentialRecord]:
        """All keys for one agent (no private material). Scoped by the base PK so
        a tenant can never list another tenant's keys."""
        resp = self._table().query(
            KeyConditionExpression="tenant_id = :t AND begins_with(key_id, :p)",
            ExpressionAttributeValues={":t": tenant_id, ":p": f"{agent_id}#"},
        )
        return [CredentialRecord.from_item(i) for i in resp.get("Items", [])]

    def get(self, tenant_id: str, agent_id: str, kid: str) -> Optional[CredentialRecord]:
        item = self._table().get_item(
            Key={"tenant_id": tenant_id, "key_id": f"{agent_id}#{kid}"}
        ).get("Item")
        return CredentialRecord.from_item(item) if item else None

    def set_status(self, tenant_id: str, agent_id: str, kid: str, status: str) -> bool:
        """Flip a key's status. ``ConditionExpression`` guards against creating a
        ghost row for a key the tenant doesn't own. Returns False if absent."""
        try:
            self._table().update_item(
                Key={"tenant_id": tenant_id, "key_id": f"{agent_id}#{kid}"},
                UpdateExpression="SET #s = :s, updated_at = :u",
                ConditionExpression="attribute_exists(key_id)",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": status, ":u": _now_ms()},
            )
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise

    def revoke_all_for_tenant(self, tenant_id: str) -> int:
        """Mark every credential for a tenant ``revoked`` (WS-D deletion step 2).
        Idempotent; returns the count touched."""
        table = self._table()
        touched = 0
        start_key = None
        while True:
            kwargs = {
                "KeyConditionExpression": "tenant_id = :t",
                "ExpressionAttributeValues": {":t": tenant_id},
            }
            if start_key:
                kwargs["ExclusiveStartKey"] = start_key
            resp = table.query(**kwargs)
            for item in resp.get("Items", []):
                table.update_item(
                    Key={"tenant_id": tenant_id, "key_id": item["key_id"]},
                    UpdateExpression="SET #s = :s",
                    ExpressionAttributeNames={"#s": "status"},
                    ExpressionAttributeValues={":s": "revoked"},
                )
                touched += 1
            start_key = resp.get("LastEvaluatedKey")
            if not start_key:
                break
        return touched

    # ---- revoked-since shared signal (A3.1) ------------------------------- #
    def read_revocation_epoch(self) -> int:
        item = self._table().get_item(
            Key={"tenant_id": _REVOCATION_PK, "key_id": _REVOCATION_SK}
        ).get("Item")
        return int(item.get("epoch", 0)) if item else 0

    def bump_revocation_epoch(self) -> None:
        """Atomic monotonic bump so every task's cache learns a revoke happened
        within one refresh interval, regardless of which task served the revoke."""
        self._table().update_item(
            Key={"tenant_id": _REVOCATION_PK, "key_id": _REVOCATION_SK},
            UpdateExpression="ADD epoch :one",
            ExpressionAttributeValues={":one": 1},
        )


# --------------------------------------------------------------------------- #
# Hot-path cache
# --------------------------------------------------------------------------- #
@dataclass
class _Entry:
    record: Optional[CredentialRecord]  # None = negative (kid miss)
    created_at: float
    created_epoch: int


class CredentialCache:
    """In-process LRU keyed by ``kid``. Public keys are immutable per ``kid`` so
    caching them is safe; the only freshness concern is **revocation**, bounded
    by ``min(token TTL, cache TTL, refresh interval)``.

    The fleet-wide revocation bound is the *refresh interval* (≤10s by default),
    NOT a local cache-bust: a bust only helps the one task that served the
    revoke, so it is explicitly **not** load-bearing across N tasks (LLD-26 §3.5).
    """

    def __init__(
        self,
        store: Optional[CredentialStore] = None,
        ttl_seconds: Optional[int] = None,
        negative_ttl_seconds: Optional[int] = None,
        max_size: Optional[int] = None,
        refresh_interval_seconds: Optional[int] = None,
    ) -> None:
        self._store = store or CredentialStore()
        self._ttl = ttl_seconds if ttl_seconds is not None else settings.credential_cache_ttl_seconds
        self._neg_ttl = (
            negative_ttl_seconds
            if negative_ttl_seconds is not None
            else settings.credential_negative_cache_ttl_seconds
        )
        self._max = max_size if max_size is not None else settings.credential_cache_max_size
        self._refresh = (
            refresh_interval_seconds
            if refresh_interval_seconds is not None
            else settings.revoked_since_refresh_seconds
        )
        self._entries: "OrderedDict[str, _Entry]" = OrderedDict()
        self._epoch = 0
        self._epoch_at = 0.0
        self._lock = asyncio.Lock()

    async def get(self, kid: str) -> Optional[CredentialRecord]:
        """Return the cached/looked-up credential for ``kid`` (None on miss).
        Never raises on a store error — a transient lookup failure is a miss
        (fail-secure: the caller treats None as unverified)."""
        await self._maybe_refresh_epoch()
        now = time.monotonic()
        entry = self._entries.get(kid)
        if entry is not None and self._fresh(entry, now):
            self._entries.move_to_end(kid)
            return entry.record  # may be None (cached negative)

        try:
            record = await asyncio.to_thread(self._store.get_by_kid, kid)
        except Exception:  # noqa: BLE001 — a lookup error is a verify miss
            logger.warning("credential lookup failed for kid=%s", kid, exc_info=True)
            return None

        ttl_for = self._neg_ttl if record is None else self._ttl
        self._put(kid, _Entry(record, now, self._epoch), ttl_for)
        return record

    def _fresh(self, entry: _Entry, now: float) -> bool:
        ttl = self._neg_ttl if entry.record is None else self._ttl
        if now - entry.created_at > ttl:
            return False
        # Any entry minted before the current revocation epoch is suspect.
        return entry.created_epoch >= self._epoch

    def _put(self, kid: str, entry: _Entry, _ttl: float) -> None:
        self._entries[kid] = entry
        self._entries.move_to_end(kid)
        while len(self._entries) > self._max:
            self._entries.popitem(last=False)

    async def _maybe_refresh_epoch(self) -> None:
        now = time.monotonic()
        if now - self._epoch_at < self._refresh:
            return
        async with self._lock:
            if time.monotonic() - self._epoch_at < self._refresh:
                return
            try:
                self._epoch = await asyncio.to_thread(self._store.read_revocation_epoch)
            except Exception:  # noqa: BLE001
                logger.warning("revoked-since refresh failed", exc_info=True)
            finally:
                self._epoch_at = time.monotonic()

    def invalidate_local(self, kid: str) -> None:
        """Best-effort local bust (NOT load-bearing across tasks)."""
        self._entries.pop(kid, None)


# --------------------------------------------------------------------------- #
# ES256 key validation
# --------------------------------------------------------------------------- #
def _assert_es256_public_key(public_key: str) -> None:
    """Reject anything that is not a P-256 (secp256r1) EC public key. Accepts PEM
    or a JWK (EC, crv P-256). Raises :class:`CredentialValidationError`."""
    try:
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.serialization import load_pem_public_key
    except Exception as exc:  # pragma: no cover - dependency missing
        raise CredentialValidationError("crypto backend unavailable") from exc

    text = (public_key or "").strip()
    if not text:
        raise CredentialValidationError("public_key is empty")

    if text.startswith("{"):
        import json

        try:
            jwk = json.loads(text)
        except Exception as exc:
            raise CredentialValidationError("public_key JWK is not valid JSON") from exc
        if jwk.get("kty") != "EC" or jwk.get("crv") != "P-256":
            raise CredentialValidationError("public_key JWK must be EC / P-256")
        # Reject an incomplete JWK at registration (missing/invalid x,y) instead
        # of accepting it and failing verify forever. PyJWK builds the real key.
        try:
            import jwt

            jwt.PyJWK.from_json(text)
        except Exception as exc:  # noqa: BLE001
            raise CredentialValidationError("public_key JWK is incomplete or invalid") from exc
        return

    try:
        key = load_pem_public_key(text.encode())
    except Exception as exc:
        raise CredentialValidationError("public_key is not valid PEM") from exc
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(
        key.curve, ec.SECP256R1
    ):
        raise CredentialValidationError("public_key must be EC P-256 (ES256)")


# Process-wide singletons (built lazily, reused — see clients.py rationale).
_cache: Optional[CredentialCache] = None
_store: Optional[CredentialStore] = None


def get_credential_cache() -> CredentialCache:
    global _cache
    if _cache is None:
        _cache = CredentialCache()
    return _cache


def get_credential_store() -> CredentialStore:
    global _store
    if _store is None:
        _store = CredentialStore()
    return _store
