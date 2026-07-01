"""The HARD PCI SAD/PAN 0-miss deterministic gate (WS-E1 E8.2; LLD 29 §15.4/§15.5).

RELEASE-BLOCKING and SEPARATE from any fuzzy recall corpus. Every Luhn-valid PAN
in ``corpus/pci_sad_pan.jsonl`` MUST emit ``<CARD:first6:last4>`` (middle digits
gone, no full PAN anywhere in the output); every label-anchored SAD MUST drop to
``<SAD>`` with no value; and every NEGATIVE row (Luhn-fail / unlabelled number)
MUST NOT be masked as a card or SAD. A SINGLE miss fails the whole gate — this is
never averaged into a WS-0-gated fuzzy number (§15.5).

The corpus is deliberately small, hand-curated, and correct-by-construction (the
PAN rows were Luhn-checked when authored). Add rows here to widen the always-on
deterministic floor; keep the fuzzy/obfuscated recall corpus (Appendix G, WS-0-
gated) elsewhere.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from aegion_guard import redact

_CORPUS = Path(__file__).resolve().parent / "corpus" / "pci_sad_pan.jsonl"
_WIRE = re.compile(r"⟦AEGR:([0-9a-f]{16}):([A-Z_]+)(?::([^⟧]+))?⟧")


def _tokens(text: str):
    return [(m.group(2), m.group(3)) for m in _WIRE.finditer(text)]


def _load():
    rows = []
    with _CORPUS.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


_ROWS = _load()
_PAN_ROWS = [r for r in _ROWS if r["kind"] == "PAN"]
_SAD_ROWS = [r for r in _ROWS if r["kind"] == "SAD"]
_NEG_ROWS = [r for r in _ROWS if r["kind"] == "NONE"]
# A SAD value immediately before a SEPARATED trailing PAN: BOTH must be redacted —
# the SAD value dropped to a no-meta <SAD> AND the trailing card tokenized (R3-H1).
_SAD_AND_PAN_ROWS = [r for r in _ROWS if r["kind"] == "SAD_AND_PAN"]


def test_corpus_has_all_classes():
    # Guard against a truncated/mis-shaped corpus silently making the gate vacuous.
    assert len(_PAN_ROWS) >= 15, "PAN corpus too small to be a real 0-miss gate"
    assert len(_SAD_ROWS) >= 5
    assert len(_NEG_ROWS) >= 3
    assert len(_SAD_AND_PAN_ROWS) >= 2  # R3-H1 combined SAD-before-separated-PAN rows


@pytest.mark.parametrize("row", _PAN_ROWS, ids=[r["id"] for r in _PAN_ROWS])
def test_pci_zero_miss_every_pan_carded_first6_last4(row):
    pan = re.sub(r"\D", "", row["pan"])
    out = redact(row["text"])
    toks = _tokens(out)
    cards = [(t, meta) for t, meta in toks if t == "CARD"]
    # Exactly one CARD token, masked to first6/last4.
    assert len(cards) == 1, f"[{row['id']}] expected one CARD, got {toks}: {out!r}"
    meta = cards[0][1]
    assert meta == f"{pan[:6]}:{pan[-4:]}", (
        f"[{row['id']}] wrong CARD meta {meta!r} (expected {pan[:6]}:{pan[-4:]})"
    )
    # RELEASE-BLOCKING: the full contiguous PAN is GONE. The middle digits survive
    # ONLY where they legitimately coincide with the retained first6/last4 (e.g. a
    # repunit-style test PAN) — so the load-bearing checks are (a) the full PAN
    # never appears, and (b) once the wire tokens (whose meta legitimately holds
    # first6/last4) are stripped, no card-length (13+) digit run survives in
    # cleartext. That is the exact PCI obligation: no full PAN egresses, tokenized
    # or not.
    assert pan not in out, f"[{row['id']}] full PAN leaked: {out!r}"
    stripped = _WIRE.sub("", out)
    assert not any(len(run) >= 13 for run in re.findall(r"\d+", stripped)), (
        f"[{row['id']}] a 13+ digit run survived in cleartext: {out!r}"
    )
    # A SEPARATED card (``4111 1111 1111 1111`` / ``4111-1111-...``) leaks its digits
    # WITHOUT any contiguous 13+ run (the separators break it into 4-digit groups), so
    # the contiguous scan above misses it. ALSO strip the PAN inter-group separators and
    # assert the full PAN digit sequence does not survive in the token-free cleartext.
    # This is what catches an R3-C1 revert: a spaced/dashed multi-group card that
    # egressed raw with no contiguous 13+ run still contains the PAN once despaced.
    despaced = re.sub(r"[ \t\r\n\-./,_]", "", stripped)
    assert pan not in despaced, (
        f"[{row['id']}] separated PAN survived in cleartext once despaced: {out!r}"
    )


@pytest.mark.parametrize("row", _SAD_ROWS, ids=[r["id"] for r in _SAD_ROWS])
def test_pci_zero_miss_every_sad_dropped_no_value(row):
    out = redact(row["text"])
    toks = _tokens(out)
    assert ("SAD", None) in toks, f"[{row['id']}] SAD not dropped: {out!r}"
    # SAD carries NO meta (never-store), and the raw digit value is gone.
    assert not re.search(r":SAD:", out), f"[{row['id']}] SAD carried meta: {out!r}"
    raw_digits = re.findall(r"\d{3,6}", row["text"])
    for d in raw_digits:
        assert d not in out, f"[{row['id']}] raw SAD value {d!r} leaked: {out!r}"


@pytest.mark.parametrize("row", _NEG_ROWS, ids=[r["id"] for r in _NEG_ROWS])
def test_negative_rows_not_masked_as_card_or_sad(row):
    # A Luhn-fail number / unlabelled number must NOT be masked as a card or SAD
    # (proves the gate isn't passing by over-masking everything).
    out = redact(row["text"])
    types = {t for t, _ in _tokens(out)}
    assert "CARD" not in types, f"[{row['id']}] false-positive CARD: {out!r}"
    assert "SAD" not in types, f"[{row['id']}] false-positive SAD: {out!r}"


@pytest.mark.parametrize(
    "row", _SAD_AND_PAN_ROWS, ids=[r["id"] for r in _SAD_AND_PAN_ROWS]
)
def test_pci_zero_miss_sad_before_separated_pan_redacts_both(row):
    # R3-H1: a SAD value (CVV/PIN) sitting immediately before a SEPARATED trailing PAN
    # (e.g. "cvv 999 4111 1111 1111 1111") must have BOTH redacted — the SAD value
    # dropped to a no-meta <SAD> AND the trailing card tokenized to <CARD:first6:last4>.
    # The pre-fix bug DECLINED the SAD match entirely (stepping aside for the PAN), so
    # the CVV egressed RAW while only the card masked — a SAD never-store violation.
    pan = re.sub(r"\D", "", row["pan"])
    out = redact(row["text"])
    toks = _tokens(out)
    # BOTH tokens present: a no-meta SAD and exactly one first6/last4 CARD.
    assert ("SAD", None) in toks, f"[{row['id']}] SAD value not dropped: {out!r}"
    cards = [(t, meta) for t, meta in toks if t == "CARD"]
    assert len(cards) == 1, f"[{row['id']}] expected one CARD, got {toks}: {out!r}"
    assert cards[0][1] == f"{pan[:6]}:{pan[-4:]}", (
        f"[{row['id']}] wrong CARD meta {cards[0][1]!r}: {out!r}"
    )
    # The raw SAD value is GONE (never-store); the full PAN never egresses; and no
    # 13+ digit run survives in cleartext once the wire tokens are stripped.
    assert row["sad"] not in out, f"[{row['id']}] raw SAD value leaked: {out!r}"
    assert not re.search(r":SAD:", out), f"[{row['id']}] SAD carried meta: {out!r}"
    assert pan not in out, f"[{row['id']}] full PAN leaked: {out!r}"
    stripped = _WIRE.sub("", out)
    assert not any(len(run) >= 13 for run in re.findall(r"\d+", stripped)), (
        f"[{row['id']}] a 13+ digit run survived in cleartext: {out!r}"
    )
