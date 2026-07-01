"""Redaction wired into the guard egress path (WS-E1, E1.3/E1.4).

Proves the redactor runs on the ACTUAL egress payload (what the client is asked
to POST), not just as a standalone function — and that a redactor failure fails
secure to a DENY, never sending raw.
"""
from __future__ import annotations

import re

import pytest

from aegion_guard import ToolDenied
from aegion_guard import redaction as R

_WIRE = re.compile(r"⟦AEGR:[0-9a-f]{16}:[A-Z_]+(?::[^⟧]+)?⟧")


def test_pii_in_tool_params_is_redacted_before_egress(make_guard, fake_client):
    guard = make_guard()
    fake_client.set_default({"decision": "ALLOW"})

    @guard.tool()
    def lookup(card_number, email):
        return "ran"

    with guard.session(session_id="s1", user_input="pay with my card"):
        lookup("4111111111111111", "bob@example.com")

    sent = fake_client.last
    # RELEASE-BLOCKING: the raw PAN + email must NOT appear anywhere in the egress.
    blob = str(sent)
    assert "4111111111111111" not in blob
    assert "bob@example.com" not in blob
    # ...and the egressed value carries the typed wire token instead.
    assert _WIRE.search(sent["tool_params"]["card_number"])
    assert _WIRE.search(sent["tool_params"]["email"])


def test_pii_in_user_input_is_redacted_before_egress(make_guard, fake_client):
    # E1.3 footgun: user_input (free-text surface) must be redacted, not just
    # tool_params. Send an SSN in the session user_input.
    guard = make_guard()
    fake_client.set_default({"decision": "ALLOW"})

    @guard.tool()
    def do_thing():
        return "ran"

    with guard.session(session_id="s1", user_input="my ssn is 123-45-6789"):
        do_thing()

    sent = fake_client.last
    assert "123-45-6789" not in sent["user_input"]
    assert _WIRE.search(sent["user_input"])


def test_redactor_failure_fails_secure_to_deny(make_guard, fake_client, monkeypatch):
    # E1.4: force the redactor to raise; the guard must DENY and NEVER call _send
    # with the raw payload. This MUST FAIL if the fail-secure branch is reverted.
    guard = make_guard()
    fake_client.set_default({"decision": "ALLOW"})  # would ALLOW if raw egressed

    def _boom(text, nonce):
        raise ValueError("crash")

    monkeypatch.setattr(R, "_ORDERED_MATCHERS", (("BOOM", _boom),))

    @guard.tool()
    def leaky(card_number):
        return "ran"

    with guard.session(session_id="s1", user_input="pay"):
        with pytest.raises(ToolDenied) as exc:
            leaky("4111111111111111")

    assert exc.value.reason == "redaction_failed"
    # Nothing was ever sent to the transport — no raw egress.
    assert fake_client.sent == []


def test_redaction_deny_fires_on_decision_hook(make_guard, fake_client, monkeypatch):
    # OBSERVABILITY (E1.5 / §3.8): the redaction fail-secure DENY branch
    # (`_redaction_denied`) MUST fire the `on_decision` hook, exactly like the
    # ALLOW/DENY and the transport-fail-secure paths — a redaction DENY is not a
    # silent drop; the SOC console/telemetry pipeline observes it via this hook.
    # This pins that contract on the REDACTION branch specifically (the generic
    # fail-secure hook test in test_hook_session_serialization.py covers the
    # TRANSPORT branch, a different code path). MUST FAIL if `_fire_hook` is
    # dropped from `_redaction_denied`.
    seen = []
    guard = make_guard(on_decision=seen.append)
    fake_client.set_default({"decision": "ALLOW"})  # would ALLOW if the hook were bypassed

    def _boom(text, nonce):
        raise ValueError("crash")

    monkeypatch.setattr(R, "_ORDERED_MATCHERS", (("BOOM", _boom),))

    @guard.tool()
    def leaky(card_number):
        return "ran"

    with guard.session(session_id="s1", user_input="pay"):
        with pytest.raises(ToolDenied):
            leaky("4111111111111111")

    # The hook fired exactly once, with the redaction-DENY Decision itself.
    assert len(seen) == 1
    assert seen[0].decision == "DENY"
    assert seen[0].reason == "redaction_failed"
    # And nothing egressed on the way to that DENY (belt-and-suspenders).
    assert fake_client.sent == []


def test_redactor_failure_denies_even_when_fail_open(make_guard, fake_client, monkeypatch):
    # fail_secure=False is an opt-out of failing closed on TRANSPORT loss, NOT a
    # license to leak raw PII. A redactor failure still DENYs (clause-(a) safety).
    guard = make_guard(fail_secure=False)

    def _boom(text, nonce):
        raise ValueError("crash")

    monkeypatch.setattr(R, "_ORDERED_MATCHERS", (("BOOM", _boom),))

    decision = guard.validate(
        tool_name="pay", tool_params={"card_number": "4111111111111111"},
        session_id="s1", user_input="pay",
    )
    assert decision.decision == "DENY"
    assert decision.reason == "redaction_failed"
    assert fake_client.sent == []


async def test_async_path_redacts_and_fails_secure(make_guard, fake_client, monkeypatch):
    guard = make_guard()

    def _boom(text, nonce):
        raise ValueError("crash")

    monkeypatch.setattr(R, "_ORDERED_MATCHERS", (("BOOM", _boom),))

    @guard.tool()
    async def apay(card_number):
        return "ran"

    with guard.session(session_id="s1", user_input="pay"):
        with pytest.raises(ToolDenied) as exc:
            await apay("4111111111111111")
    assert exc.value.reason == "redaction_failed"
    assert fake_client.sent == []


def test_pii_in_context_is_redacted_before_egress(make_guard, fake_client):
    # REGRESSION: the caller-supplied `context` dict ALSO egresses to the hosted
    # PDP; PII/PCI placed in it must be redacted like tool_params, not egress raw
    # (NFR-7 (a)). MUST FAIL if context skips the redactor.
    guard = make_guard()
    fake_client.set_default({"decision": "ALLOW"})

    @guard.tool()
    def do_thing():
        return "ran"

    ctx = {"user_email": "bob@example.com", "card": "4111111111111111", "tier": "gold"}
    with guard.session(session_id="s1", user_input="hello", context=ctx):
        do_thing()

    sent = fake_client.last
    blob = str(sent["context"])
    assert "bob@example.com" not in blob        # raw email gone
    assert "4111111111111111" not in blob        # raw PAN gone
    assert _WIRE.search(sent["context"]["user_email"])
    assert _WIRE.search(sent["context"]["card"])
    assert sent["context"]["tier"] == "gold"     # clean non-PII value untouched


def test_context_redactor_failure_fails_secure_to_deny(make_guard, fake_client, monkeypatch):
    # A redactor failure while redacting context must DENY, never egress raw (E1.4).
    guard = make_guard()
    fake_client.set_default({"decision": "ALLOW"})

    def _boom(text, nonce):
        raise ValueError("crash")

    monkeypatch.setattr(R, "_ORDERED_MATCHERS", (("BOOM", _boom),))

    @guard.tool()
    def do_thing():
        return "ran"

    with guard.session(
        session_id="s1", user_input="hi", context={"ssn": "123-45-6789"}
    ):
        with pytest.raises(ToolDenied) as exc:
            do_thing()
    assert exc.value.reason == "redaction_failed"
    assert fake_client.sent == []


# --------------------------------------------------------------------------- #
# Provenance + single per-egress nonce (§3.3/§3.5): redacted=True + one
# redaction_nonce stamping EVERY genuine marker in the payload.
# --------------------------------------------------------------------------- #
def _nonces_in(text: str):
    return {m.group(0)[len("⟦AEGR:"):].split(":", 1)[0]
            for m in _WIRE.finditer(text)} if text else set()


def test_payload_carries_provenance_flag_and_nonce(make_guard, fake_client):
    # E1.4/§3.5 acceptance: the egress payload declares it was edge-redacted and
    # carries the per-egress nonce the PDP uses to recognize genuine markers.
    guard = make_guard()
    fake_client.set_default({"decision": "ALLOW"})

    @guard.tool()
    def lookup(email):
        return "ran"

    with guard.session(session_id="s1", user_input="my ssn is 123-45-6789"):
        lookup("bob@example.com")

    sent = fake_client.last
    assert sent["redacted"] is True
    assert re.fullmatch(r"[0-9a-f]{16}", sent["redaction_nonce"])


def test_single_nonce_binds_all_fields(make_guard, fake_client):
    # SECURITY (§3.3): ONE nonce per egress — every genuine marker across
    # tool_params, user_input, and context shares payload["redaction_nonce"], so
    # the PDP can tell a genuine marker (this call's nonce) from a replayed one.
    # MUST FAIL if _build_request mints a fresh nonce per field.
    guard = make_guard()
    fake_client.set_default({"decision": "ALLOW"})

    @guard.tool()
    def lookup(card_number):
        return "ran"

    ctx = {"user_email": "carol@example.com"}
    with guard.session(
        session_id="s1", user_input="ssn 123-45-6789", context=ctx
    ):
        lookup("4111111111111111")

    sent = fake_client.last
    egress_nonce = sent["redaction_nonce"]
    seen = set()
    seen |= _nonces_in(sent["tool_params"]["card_number"])
    seen |= _nonces_in(sent["user_input"])
    seen |= _nonces_in(sent["context"]["user_email"])
    assert seen, "expected genuine markers across the payload"
    assert seen == {egress_nonce}, (
        f"every marker must carry the single egress nonce; got {seen} vs {egress_nonce}"
    )


# --------------------------------------------------------------------------- #
# content_text seam (WS-B multiphase contract, LLD 30 §4.2 + lld/29 §3.5) — the
# egressing phases (content/output/memory) carry their content in the SINGLE
# `content_text` wire field (disambiguated by `phase`), which MUST be redacted like
# any other egressing field. WS-E consumes WS-B's seam: the `phase` flows via the
# per-phase DECORATOR (@guard.content/output/memory), NOT via session()/RequestContext,
# and unknown phases are a 422 server-side — NOT a client-side ConfigError. These
# tests pin the redaction onto that canonical seam (do NOT reintroduce per-phase
# content fields / session(phase=...) — that divergence was reverted).
# --------------------------------------------------------------------------- #
_PHASE_DECORATOR = {
    "content": lambda g: g.content(),
    "output": lambda g: g.output(),
    "memory": lambda g: g.memory(),
}


@pytest.mark.parametrize("phase", ["content", "output", "memory"])
def test_content_text_field_is_redacted_before_egress(make_guard, fake_client, phase):
    # §3.5 footgun: an egressing phase carries its content in the single
    # `content_text` field (the richest PII surface). That field MUST be redacted,
    # not egressed raw. MUST FAIL if only the request branch is redacted. WS-B
    # sources content_text from the resolved user_input the decorator already has.
    guard = make_guard()
    fake_client.set_default({"decision": "ALLOW"})

    @_PHASE_DECORATOR[phase](guard)
    def ingest():
        return "ran"

    content = "retrieved doc: card 4111111111111111, email eve@example.com"
    with guard.session(session_id="s1", user_input=content):
        ingest()

    sent = fake_client.last
    assert sent["phase"] == phase
    # The single content_text field is redacted (no raw PII survives).
    assert "4111111111111111" not in sent["content_text"]
    assert "eve@example.com" not in sent["content_text"]
    assert _WIRE.search(sent["content_text"])
    # ...and it shares the single egress nonce (same nonce as user_input etc.).
    assert _nonces_in(sent["content_text"]) == {sent["redaction_nonce"]}


def test_request_phase_has_no_content_text_field(make_guard, fake_client):
    # The default "request" phase (@guard.tool) has NO `content_text` on the wire —
    # its content is tool_params/user_input. The request payload stays byte-identical
    # to pre-WS-B aside from the redaction provenance stamped on every payload.
    guard = make_guard()
    fake_client.set_default({"decision": "ALLOW"})

    @guard.tool()
    def do_thing():
        return "ran"

    with guard.session(session_id="s1", user_input="hi"):
        do_thing()

    sent = fake_client.last
    # No `phase` key emitted for the request path (server defaults it to "request").
    assert "phase" not in sent
    assert "content_text" not in sent


def test_content_text_image_blob_is_tagged_not_sent_raw(make_guard, fake_client):
    # E6.1: an inlined image blob egressing as content_text is TAGGED to an IMAGE
    # marker + routed, never pixel-redacted and never egressed raw.
    guard = make_guard()
    fake_client.set_default({"decision": "ALLOW"})

    @guard.content()
    def ingest():
        return "ran"

    blob = "data:image/png;base64," + ("A" * 800)
    with guard.session(session_id="s1", user_input=blob):
        ingest()

    sent = fake_client.last
    assert sent["phase"] == "content"
    assert "A" * 800 not in sent["content_text"]  # raw blob NOT egressed
    m = _WIRE.search(sent["content_text"])
    assert m and ":IMAGE" in m.group(0)           # tagged as IMAGE, routed to Tier-2
