"""Tenant lifecycle, membership, invites & RBAC (LLD-26 §6 / WS-D D2,D3,D4)."""
from __future__ import annotations

import asyncio

import boto3
import pytest
from fastapi import HTTPException
from moto import mock_aws

from app.config import settings
from app.utils import tenancy
from tests.mt_helpers import run, create_mt_tables


class FakeRequest:
    def __init__(self, headers=None):
        self.headers = {k.lower(): v for k, v in (headers or {}).items()}


@pytest.fixture
def mt_env(monkeypatch):
    for k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SECURITY_TOKEN", "AWS_SESSION_TOKEN"):
        monkeypatch.setenv(k, "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", settings.aws_region)
    with mock_aws():
        ddb = boto3.resource("dynamodb", region_name=settings.aws_region)
        create_mt_tables(ddb)
        import app.utils.clients as clients
        import app.services.tenant_service as ts
        clients._registry = None
        ts._tenant_store = None
        ts._member_store = None
        yield ddb


# --------------------------------------------------------------------------- #
# Tenant registry (D2/D4)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("reserved", ["default", "_unverified", "_platform"])
def test_reserved_ids_rejected(mt_env, reserved):
    from app.services.tenant_service import TenantError, get_tenant_store

    with pytest.raises(TenantError):
        get_tenant_store().create(display_name="X", tenant_id=reserved)


def test_free_text_id_rejected(mt_env):
    from app.services.tenant_service import TenantError, get_tenant_store

    with pytest.raises(TenantError):
        get_tenant_store().create(display_name="X", tenant_id="Acme Corp!")


def test_mint_is_derived_slug_and_immutable(mt_env):
    from app.services.tenant_service import get_tenant_store

    t = get_tenant_store().create(display_name="Acme")
    assert t.tenant_id.startswith("t_") and t.tenant_id == t.tenant_id.lower()
    # Re-creating the same id is rejected (immutability / idempotency guard).
    from app.services.tenant_service import TenantError

    with pytest.raises(TenantError):
        get_tenant_store().create(display_name="Acme2", tenant_id=t.tenant_id)


def test_purged_is_terminal(mt_env):
    from app.services.tenant_service import get_tenant_store

    store = get_tenant_store()
    t = store.create(display_name="Acme")
    store.set_status(t.tenant_id, "deleting")
    store.mark_purged(t.tenant_id)
    # A purged tombstone can never be flipped back to active.
    from botocore.exceptions import ClientError

    with pytest.raises(ClientError):
        store.set_status(t.tenant_id, "active")


def test_resolve_org_excludes_purged_tenant(mt_env):
    """WS-G G0.2 / D14: a tombstoned (``purged``) org must NOT resolve — otherwise
    org-first login would advance to Cognito for a purged tenant. Guards BOTH
    exclusion branches of ``resolve_org_to_tenant_id`` (tenant_service.py:240 the
    exact-slug fast path, :249 the name-scan loop). Non-vacuous: it asserts the
    org resolves BEFORE purge, so a green result post-purge can only mean the
    status check fired — dropping either check would let a purged tenant resolve."""
    from app.services.tenant_service import get_tenant_store

    store = get_tenant_store()
    t = store.create(display_name="Purged Org")
    # Pre-purge: both the name path and the t_-slug fast path resolve (this proves
    # the post-purge None assertions aren't trivially-None from a bad seed).
    assert store.resolve_org_to_tenant_id("Purged Org") == t.tenant_id
    assert store.resolve_org_to_tenant_id(t.tenant_id) == t.tenant_id

    store.set_status(t.tenant_id, "deleting")
    store.mark_purged(t.tenant_id)

    # Name-scan branch (:249): typed org NAME of a purged tenant → None.
    assert store.resolve_org_to_tenant_id("Purged Org") is None, (
        "a purged org resolved by display name — the :249 status check regressed"
    )
    # Exact-slug fast-path branch (:240): pasted t_-slug of a purged tenant → None.
    assert store.resolve_org_to_tenant_id(t.tenant_id) is None, (
        "a purged org resolved by t_-slug fast path — the :240 status check regressed"
    )


def test_resolve_org_matches_exact_tenant_id_for_non_t_slug(mt_env):
    """WS-G G0.2 / D14 fix: a human-readable tenant_id (a verified-domain-style
    slug like ``acme`` — NOT the minted ``t_<...>`` form) must resolve when an
    operator types the org's own id, even though it does not match the fuller
    ``display_name``. This is the real prod case: the design-partner tenant is
    ``tenant_id="acme"`` / ``display_name="Acme (design partner)"``, so typing
    "Acme" (→ display_name miss) previously 404'd. The exact-id path must fire for
    ANY slug, not only ``t_``-prefixed ones.

    Non-vacuous: it asserts the id resolves AND that the un-typed-display substring
    still resolves, and that a genuine non-match still returns None (so a green
    result can't come from a resolver that matches everything)."""
    from app.services.tenant_service import get_tenant_store

    store = get_tenant_store()
    # Seed exactly the prod shape: human-readable id + fuller display name.
    store.create(display_name="Acme (design partner)", tenant_id="acme")

    # The fix: exact tenant_id resolves for a non-`t_` slug (case-insensitive).
    assert store.resolve_org_to_tenant_id("acme") == "acme"
    assert store.resolve_org_to_tenant_id("ACME") == "acme"
    assert store.resolve_org_to_tenant_id("  acme  ") == "acme"
    # The full display_name still resolves (name-scan branch unaffected).
    assert store.resolve_org_to_tenant_id("Acme (design partner)") == "acme"
    # A genuine non-match still misses (resolver is not matching everything).
    assert store.resolve_org_to_tenant_id("globex") is None


def test_identity_mode_validation(mt_env):
    from app.services.tenant_service import TenantError, get_tenant_store

    store = get_tenant_store()
    t = store.create(display_name="Acme")
    store.set_identity_mode(t.tenant_id, "shadow")
    assert store.get(t.tenant_id).identity_mode == "shadow"
    with pytest.raises(TenantError):
        store.set_identity_mode(t.tenant_id, "bogus")


def test_set_display_name_renames_and_rejects_blank(mt_env):
    from app.services.tenant_service import TenantError, get_tenant_store

    store = get_tenant_store()
    t = store.create(display_name="Acme")
    store.set_display_name(t.tenant_id, "Acme Renamed")
    assert store.get(t.tenant_id).display_name == "Acme Renamed"
    # trimmed
    store.set_display_name(t.tenant_id, "  Trimmed  ")
    assert store.get(t.tenant_id).display_name == "Trimmed"
    # a blank/whitespace name can't wipe the label
    with pytest.raises(TenantError):
        store.set_display_name(t.tenant_id, "   ")
    with pytest.raises(TenantError):
        store.set_display_name(t.tenant_id, "x" * 129)


def test_free_mail_domain_detection():
    from app.services.tenant_service import is_free_mail_domain

    assert is_free_mail_domain("gmail.com")
    assert not is_free_mail_domain("acme.com")


# --------------------------------------------------------------------------- #
# Membership + invites (D2/D3)
# --------------------------------------------------------------------------- #
def test_membership_lookups(mt_env):
    from app.services.tenant_service import get_member_store

    members = get_member_store()
    members.add("op1", "t_a", role="owner", is_primary=True)
    members.add("op1", "t_b", role="viewer")
    members.add("op2", "t_a", role="editor")

    by_op = members.by_operator("op1")
    assert {m.tenant_id for m in by_op} == {"t_a", "t_b"}
    primary = next(m for m in by_op if m.is_primary)
    assert primary.tenant_id == "t_a"

    by_tenant = members.by_tenant("t_a")  # GSI
    assert {m.operator_sub for m in by_tenant} == {"op1", "op2"}


def test_invite_is_single_use(mt_env):
    from app.services.tenant_service import TenantError, get_member_store

    members = get_member_store()
    token = members.create_invite("t_a", email="new@acme.com", role="editor", invited_by="op1")
    m = members.redeem_invite(token, "op_new", redeemer_email="new@acme.com")
    assert m.tenant_id == "t_a" and m.role == "editor"
    # The real membership now exists; the invite row is gone (filtered from list).
    assert "op_new" in {x.operator_sub for x in members.by_operator("op_new")}
    # Second redemption of the same token must fail (single-use).
    with pytest.raises(TenantError):
        members.redeem_invite(token, "op_other", redeemer_email="new@acme.com")


def test_invite_token_stored_hashed_and_email_bound(mt_env):
    """#7 — only sha256(token) is persisted, and redeem is email-bound."""
    import hashlib
    from app.services.tenant_service import TenantError, get_member_store

    members = get_member_store()
    token = members.create_invite("t_a", email="bound@acme.com", role="viewer", invited_by="op1")
    # The raw token must NOT appear as a stored PK; only its hash.
    raw_row = mt_env.Table(settings.dynamodb_tenant_members_table).get_item(
        Key={"operator_sub": f"_invite#{token}", "tenant_id": "t_a"}
    ).get("Item")
    assert raw_row is None
    hashed = mt_env.Table(settings.dynamodb_tenant_members_table).get_item(
        Key={"operator_sub": f"_invite#{hashlib.sha256(token.encode()).hexdigest()}", "tenant_id": "t_a"}
    ).get("Item")
    assert hashed is not None
    # Wrong redeemer email → rejected (the link alone is not enough).
    with pytest.raises(TenantError):
        members.redeem_invite(token, "intruder", redeemer_email="intruder@evil.com")


def test_redeem_cannot_replace_existing_membership(mt_env):
    """#1 — an owner redeeming any invite can't be silently re-roled (add is
    create-only), closing the admin→owner self-escalation via invite."""
    from app.services.tenant_service import TenantError, get_member_store

    members = get_member_store()
    members.add("op_admin", "t_a", role="admin", is_primary=True)
    # An owner invite to the same operator must NOT overwrite their admin row.
    token = members.create_invite("t_a", email="a@acme.com", role="owner", invited_by="op1")
    with pytest.raises(TenantError):
        members.redeem_invite(token, "op_admin", redeemer_email="a@acme.com")
    assert members.get("op_admin", "t_a").role == "admin"  # unchanged


def test_invite_rows_excluded_from_membership(mt_env):
    from app.services.tenant_service import get_member_store

    members = get_member_store()
    members.create_invite("t_a", email="x@acme.com", role="viewer", invited_by="op1")
    # An un-redeemed invite must not appear as a real member of the tenant.
    assert members.by_tenant("t_a") == []


# --------------------------------------------------------------------------- #
# RBAC (D3b)
# --------------------------------------------------------------------------- #
def test_role_hierarchy():
    from app.api.deps import role_satisfies

    assert role_satisfies("owner", "viewer")
    assert role_satisfies("admin", "editor")
    assert role_satisfies("editor", "editor")
    assert not role_satisfies("viewer", "editor")
    assert not role_satisfies("editor", "admin")


def test_require_role_blocks_insufficient(mt_env):
    from app.api.deps import OperatorContext, require_role

    dep = require_role("admin")
    viewer = OperatorContext(sub="op", tenant_id="t_a", role="viewer")
    with pytest.raises(HTTPException) as exc:
        run(dep(ctx=viewer))
    assert exc.value.status_code == 403
    admin = OperatorContext(sub="op", tenant_id="t_a", role="admin")
    assert run(dep(ctx=admin)) is admin


# --------------------------------------------------------------------------- #
# ALB OIDC + operator→tenant resolution (D3a/D3b)
# --------------------------------------------------------------------------- #
def test_verify_alb_oidc_missing_header_401():
    from app.api.deps import verify_alb_oidc

    with pytest.raises(HTTPException) as exc:
        verify_alb_oidc(FakeRequest({}))
    assert exc.value.status_code == 401


def test_resolve_operator_tenant_primary_and_switch(mt_env, monkeypatch):
    import app.api.deps as deps
    from app.services.tenant_service import get_member_store

    members = get_member_store()
    members.add("opX", "t_a", role="owner", is_primary=True)
    members.add("opX", "t_b", role="viewer")

    monkeypatch.setattr(deps, "_alb_claims_override", lambda req: {"sub": "opX", "email": "x@acme.com"})

    async def scenario():
        # No header → primary tenant; set_current_tenant must be wired (asserted
        # inside the coroutine — asyncio.run discards contextvar state on return).
        ctx = await deps.resolve_operator_tenant(FakeRequest({}))
        assert ctx.tenant_id == "t_a" and ctx.role == "owner"
        assert tenancy.current_tenant() == "t_a"

        # Valid switch header → that tenant.
        ctx2 = await deps.resolve_operator_tenant(FakeRequest({"X-Aegion-Tenant": "t_b"}))
        assert ctx2.tenant_id == "t_b" and ctx2.role == "viewer"
        assert tenancy.current_tenant() == "t_b"

        # Switch to a tenant the operator is NOT a member of → 403.
        with pytest.raises(HTTPException) as exc:
            await deps.resolve_operator_tenant(FakeRequest({"X-Aegion-Tenant": "t_zzz"}))
        assert exc.value.status_code == 403

    run(scenario())


def test_resolve_operator_no_membership_403(mt_env, monkeypatch):
    import app.api.deps as deps

    monkeypatch.setattr(deps, "_alb_claims_override", lambda req: {"sub": "nobody", "email": ""})
    with pytest.raises(HTTPException) as exc:
        run(deps.resolve_operator_tenant(FakeRequest({})))
    assert exc.value.status_code == 403


# --------------------------------------------------------------------------- #
# Security-boundary regressions (Kiro review #1, #2, #3, #8)
# --------------------------------------------------------------------------- #
def test_admin_cannot_invite_owner(mt_env):
    """#1 — an admin cannot mint a role above their own (no self-escalation)."""
    from app.api.deps import OperatorContext
    from app.api.tenancy_routes import InviteCreateRequest, create_invite

    admin = OperatorContext(sub="op_admin", tenant_id="t_a", role="admin")
    with pytest.raises(HTTPException) as exc:
        run(create_invite("t_a", InviteCreateRequest(email="x@acme.com", role="owner"), ctx=admin))
    assert exc.value.status_code == 403
    # An admin CAN invite an editor (at-or-below their level).
    res = run(create_invite("t_a", InviteCreateRequest(email="y@acme.com", role="editor"), ctx=admin))
    assert res["role"] == "editor"


def test_create_tenant_always_mints_opaque_slug(mt_env, monkeypatch):
    """#2 — self-serve tenant creation never honors a domain claim; opaque t_ id."""
    import app.api.deps as deps
    from app.api.tenancy_routes import TenantCreateRequest, create_tenant

    monkeypatch.setattr(deps, "_alb_claims_override", lambda req: {"sub": "founder", "email": "f@acme.com"})
    # Even if a client crafts extra fields, the model has no verified_domain and
    # the id is always a minted t_ slug — never "microsoft-com".
    res = run(create_tenant(TenantCreateRequest(display_name="Acme"), FakeRequest({})))
    assert res["tenant_id"].startswith("t_") and res["role"] == "owner"


def test_update_tenant_applies_display_name_rename(mt_env):
    """A PATCH with display_name actually renames the tenant (it used to be a
    silent 200 no-op) and echoes the new name back."""
    from app.api.deps import OperatorContext
    from app.api.tenancy_routes import TenantUpdateRequest, update_tenant
    from app.services.tenant_service import get_tenant_store

    store = get_tenant_store()
    t = store.create(display_name="Old Name")
    admin = OperatorContext(sub="op_admin", tenant_id=t.tenant_id, role="admin")
    res = run(update_tenant(t.tenant_id, TenantUpdateRequest(display_name="New Name"), ctx=admin))
    assert res["display_name"] == "New Name"
    assert store.get(t.tenant_id).display_name == "New Name"


def test_platform_break_glass_is_read_only(mt_env, monkeypatch):
    """#3 — a _platform operator switching into a non-member tenant gets viewer,
    not admin (the comment's intent; closes the cross-tenant write bypass)."""
    import app.api.deps as deps
    from app.services.tenant_service import get_member_store

    get_member_store().add("op_staff", tenancy.PLATFORM_TENANT, role="admin")

    monkeypatch.setattr(deps, "_alb_claims_override", lambda req: {"sub": "op_staff", "email": "s@sentra.io"})

    async def scenario():
        ctx = await deps.resolve_operator_tenant(FakeRequest({"X-Aegion-Tenant": "t_customer"}))
        assert ctx.is_platform is True
        assert ctx.role == "viewer"  # read-only break-glass, never admin

    run(scenario())


def test_cannot_remove_higher_privileged_member(mt_env):
    """#8 — an admin cannot remove an owner."""
    from app.api.deps import OperatorContext
    from app.api.tenancy_routes import remove_member
    from app.services.tenant_service import get_member_store

    members = get_member_store()
    members.add("op_owner", "t_a", role="owner", is_primary=True)
    members.add("op_admin", "t_a", role="admin")
    admin = OperatorContext(sub="op_admin", tenant_id="t_a", role="admin")
    with pytest.raises(HTTPException) as exc:
        run(remove_member("t_a", "op_owner", ctx=admin))
    assert exc.value.status_code == 403


def test_cannot_remove_last_owner(mt_env):
    """#8 — the last owner can't be removed (tested via platform break-glass,
    which bypasses the higher-privilege guard but not the last-owner guard)."""
    from app.api.deps import OperatorContext
    from app.api.tenancy_routes import remove_member
    from app.services.tenant_service import get_member_store

    get_member_store().add("op_owner", "t_a", role="owner", is_primary=True)
    platform = OperatorContext(sub="op_staff", tenant_id="t_a", role="viewer", is_platform=True)
    with pytest.raises(HTTPException) as exc:
        run(remove_member("t_a", "op_owner", ctx=platform))
    assert exc.value.status_code == 400
