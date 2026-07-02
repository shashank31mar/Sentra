"""WS-E3 — the served `phi-ner` endpoint contract (LLD 29 §4 / §9.6 / §11).

Covers the code-respond fixes on the SERVED side of the Tier-2 redactor
(app.redaction.phi_ner.create_served_app):

  * F4 honesty — `redact_free_text_fields` discards the raw and returns only the
    redacted view (no raw substrings, `redacted=True`); the removed buffer-zeroing
    theater is gone (no `_zero_buffer` / `ctypes` left in the module).
  * §11 defense-in-depth — when `PHI_NER_CALLER_SECRET` is set, an unauthenticated
    / mis-secret caller is 401 BEFORE redaction; the correct secret is 200; unset ⇒
    the network layer is the sole control (header not required).
  * §9.6 DoS bound — an over-count / over-length body is rejected 413 before any
    regex pass runs.
  * Perf/quality — the precompiled clinical-condition alternation still tokenizes
    every lexicon term in one pass.

Non-vacuous: each assertion fails if the corresponding fix regresses (e.g. drop
the caller check → the no-secret POST would 200; drop the bound → the huge body
would 200; re-introduce a raw echo → the raw-substring assertion fails).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.redaction import phi_ner
from app.redaction.phi_ner import create_served_app, redact_free_text_fields


_RAW = "Patient John Smith has diabetes at 42 Oak Street"


def test_theater_removed_no_ctypes_or_zero_buffer():
    """The inert buffer-zeroing theater (F4) is gone — no false 'scrub' claim."""
    assert not hasattr(phi_ner, "_zero_buffer")
    assert "ctypes" not in dir(phi_ner)


def test_redact_discards_raw_and_tokenizes():
    """Core: raw discarded, tokens emitted, NO raw substring survives in output."""
    out = redact_free_text_fields({"a": _RAW}, nonce="n1", tenant_id="t1")
    assert out["redacted"] is True
    text = out["fields"]["a"]
    for raw_word in ("John", "Smith", "diabetes", "Oak"):
        assert raw_word not in text, f"raw {raw_word!r} leaked into redacted output"
    assert set(out["found_classes"]) == {"NAME", "CONDITION", "ADDRESS"}


def test_precompiled_conditions_all_match():
    """Perf fix: the single precompiled alternation still catches every condition."""
    conditions = "diabetes hypertension asthma cancer hiv depression schizophrenia pregnancy"
    out = redact_free_text_fields({"c": conditions}, nonce=None, tenant_id="t")
    # every whitespace-separated token becomes a CONDITION token — none left raw
    for term in conditions.split():
        assert term not in out["fields"]["c"]
    assert out["found_classes"] == ["CONDITION"]


def test_health_ok():
    client = TestClient(create_served_app())
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["service"] == "phi-ner"


def test_caller_secret_required_when_configured(monkeypatch):
    """§11: with a secret configured, no/wrong header is 401; correct is 200."""
    monkeypatch.setenv("PHI_NER_CALLER_SECRET", "s3cr3t")
    client = TestClient(create_served_app())
    body = {"fields": {"a": "John Smith"}, "tenant_id": "t"}
    assert client.post("/v1/redact", json=body).status_code == 401
    assert client.post(
        "/v1/redact", json=body, headers={"X-Aegion-Caller-Secret": "wrong"}
    ).status_code == 401
    ok = client.post(
        "/v1/redact", json=body, headers={"X-Aegion-Caller-Secret": "s3cr3t"}
    )
    assert ok.status_code == 200
    assert "John" not in str(ok.json()["fields"])  # raw never echoed


def test_no_secret_configured_is_open(monkeypatch):
    """Unset secret ⇒ header NOT required (network layer is the sole control)."""
    monkeypatch.delenv("PHI_NER_CALLER_SECRET", raising=False)
    client = TestClient(create_served_app())
    r = client.post("/v1/redact", json={"fields": {"a": "hello"}, "tenant_id": "t"})
    assert r.status_code == 200


def test_oversized_body_rejected_413(monkeypatch):
    """§9.6: over field-count or over per-field length → 413 before redaction.

    Patches the module-level bound constants directly (the validator reads them at
    call time) — deliberately NOT `importlib.reload`, which would rebind
    `NerUnavailable`/models to fresh identities and poison already-imported callers
    (e.g. the barrier node) elsewhere in the session.
    """
    monkeypatch.delenv("PHI_NER_CALLER_SECRET", raising=False)
    monkeypatch.setattr(phi_ner, "_MAX_FIELDS", 3)
    monkeypatch.setattr(phi_ner, "_MAX_FIELD_CHARS", 50)
    client = TestClient(create_served_app())
    too_many = {"fields": {f"f{i}": "x" for i in range(10)}, "tenant_id": "t"}
    r = client.post("/v1/redact", json=too_many)
    assert r.status_code == 413, r.text
    too_long = {"fields": {"a": "z" * 100}, "tenant_id": "t"}
    r = client.post("/v1/redact", json=too_long)
    assert r.status_code == 413, r.text
