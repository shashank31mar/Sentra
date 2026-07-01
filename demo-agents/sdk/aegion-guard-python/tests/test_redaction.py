"""Tier-1 edge redactor unit tests (WS-E1, FR-3.13).

These are the arbiter for the deterministic redactor. Several are RELEASE-
BLOCKING / negative-control tests (WS-E acceptance §5):

* ``test_pci_zero_miss_*`` — a single missed Luhn-valid PAN or SAD fails it.
* ``test_planted_token_cannot_forge_marker`` — negative control for M-4; must
  FAIL if token neutralization is reverted.
* ``test_fail_secure_*`` — the redactor raises rather than returning raw.
* ``test_matcher_order_is_frozen`` — the order is a security control.
"""
from __future__ import annotations

import re

import pytest

from aegion_guard import RedactionError, redact, redact_detailed, redact_params
from aegion_guard import redaction as R


# --------------------------------------------------------------------------- #
# Wire-token grammar (M-4): ⟦AEGR:{nonce}:TYPE[:meta]⟧ with a per-call nonce.
# --------------------------------------------------------------------------- #
_WIRE = re.compile(r"⟦AEGR:([0-9a-f]{16}):([A-Z_]+)(?::([^⟧]+))?⟧")


def _tokens(text: str):
    """Return [(TYPE, meta_or_None), ...] for every wire token in ``text``."""
    return [(m.group(2), m.group(3)) for m in _WIRE.finditer(text)]


# ---- PCI: PAN -> first6/last4 ONLY (release-blocking) ---------------------- #
# A spread of well-known Luhn-valid test PANs (Visa/MC/Amex/Discover) + grouped.
_VALID_PANS = [
    "4111111111111111",         # Visa test
    "4111 1111 1111 1111",      # Visa, space-grouped
    "4012-8888-8888-1881",      # Visa, hyphen-grouped
    "5555555555554444",         # Mastercard test
    "5105105105105100",         # Mastercard test
    "378282246310005",          # Amex (15 digit)
    "6011111111111117",         # Discover
]


@pytest.mark.parametrize("pan", _VALID_PANS)
def test_pci_zero_miss_pan_masked_to_first6_last4(pan):
    out = redact(f"charge card {pan} now")
    toks = _tokens(out)
    assert len(toks) == 1, f"expected exactly one token, got {toks} for {pan!r}"
    type_, meta = toks[0]
    assert type_ == "CARD"
    digits = re.sub(r"\D", "", pan)
    assert meta == f"{digits[:6]}:{digits[-4:]}"
    # RELEASE-BLOCKING: the full contiguous PAN must be GONE (only first6/last4
    # survive, and only inside the typed token's meta). Strip the wire tokens FIRST:
    # the ⟦AEGR:{nonce}:…⟧ nonce is 16 random hex chars (so incidental decimal runs
    # can appear inside it), and the retained CARD token's meta legitimately holds
    # first6/last4 — checking raw-value substrings against the un-stripped output can
    # false-fail on a nonce coincidence rather than a real leak (same idiom as
    # test_pci_deterministic.py:142 / test_pan_never_emits_full_number_even_tokenized).
    stripped = _WIRE.sub("", out)
    assert digits not in stripped           # full contiguous PAN gone
    assert pan not in stripped              # exact raw form gone
    # No digit-run of the full PAN length survives anywhere in the token-free egress.
    assert not any(len(run) >= len(digits) for run in re.findall(r"\d+", stripped))


def test_pan_never_emits_full_number_even_tokenized():
    pan = "4012888888881881"   # Luhn-valid; middle digits distinct from first6
    out = redact(pan)
    toks = _tokens(out)
    assert len(toks) == 1 and toks[0][0] == "CARD"
    # The ONLY PAN-derived digits are the first6/last4 meta; the full PAN and its
    # middle digits never appear. (The nonce may contain incidental digits, so we
    # assert against the PAN content, not raw digit-run length.)
    assert toks[0][1] == f"{pan[:6]}:{pan[-4:]}"
    assert pan not in out
    assert pan[6:-4] not in out             # middle digits (888888) gone


def test_non_luhn_long_number_is_not_a_card():
    # An order number that happens to be 16 digits but fails Luhn must NOT become
    # a CARD (and must not lose data as if it were one).
    order = "1234567890123456"  # fails Luhn
    assert not R._luhn_ok(order)
    out = redact(f"order {order}")
    assert "CARD" not in out


# ---- PCI: over-captured PAN candidate must NOT egress the card RAW (release-
# blocking; proving test for the windowed-Luhn re-bounding). A separated leading or
# trailing digit adjacent to a valid PAN would, with a single all-or-nothing Luhn
# check, make the whole run fail Luhn and be returned RAW — the full card leaking in
# cleartext to the hosted PDP (M-3 / NFR-7 (a)). MUST FAIL if _redact_pan reverts to
# a single Luhn check on the whole captured run. -------------------------------- #
@pytest.mark.parametrize(
    "text,pan",
    [
        ("pay 5 4111111111111111", "4111111111111111"),          # Visa 16, leading digit
        ("order 9 4111 1111 1111 1111", "4111111111111111"),     # Visa 16 grouped, leading digit
        ("ref 7 378282246310005", "378282246310005"),            # Amex 15, leading digit
        ("4111111111111111 0", "4111111111111111"),              # Visa 16, trailing digit
        ("0 378282246310005", "378282246310005"),                # Amex 15, leading digit
    ],
)
def test_pan_adjacent_stray_digit_still_tokenized_never_raw(text, pan):
    out = redact(text)
    toks = _tokens(out)
    assert len(toks) == 1 and toks[0][0] == "CARD", (
        f"card not tokenized (leaked?) for {text!r}: {out!r}"
    )
    # RELEASE-BLOCKING: the full contiguous PAN must NOT survive anywhere.
    assert pan not in out, f"raw PAN {pan!r} leaked in {out!r}"
    # The meta is first6/last4 of a Luhn-valid card window. When a stray LEADING
    # digit forms a Luhn-valid window of its own (e.g. "0" + Amex-15 is a valid
    # 16-run), the chosen first6 may include that digit; the last4 (card tail) and
    # the never-emit-full-PAN invariant above are the load-bearing PCI guarantees.
    meta = toks[0][1]
    assert meta is not None and meta.endswith(f":{pan[-4:]}")
    assert re.fullmatch(r"\d{6}:\d{4}", meta), f"unexpected meta shape: {meta!r}"


def test_pan_embedded_in_longer_digit_span_no_card_digits_survive():
    # A valid PAN embedded in a longer digit-ish span (leading + trailing stray
    # digit sharing separators) must degrade to redacting the card, never leaving
    # 13-19 contiguous card digits in cleartext.
    pan = "4012888888881881"  # Luhn-valid Visa
    out = redact(f"txn 8 {pan} 3")
    assert pan not in out
    # No 13+ contiguous card-digit run survives (the nonce may hold short digit
    # runs, but never the full PAN).
    assert pan[:13] not in out and pan[-13:] not in out
    # The meta is the REAL card first6/last4 (group-anchored window), never a window
    # shifted by the stray '8'/'3' (which would give bogus BIN/last4 + a stranded
    # real card digit). See the "wrong PAN window" regression below.
    toks = _tokens(out)
    assert len(toks) == 1 and toks[0][0] == "CARD"
    assert toks[0][1] == f"{pan[:6]}:{pan[-4:]}"


# ---- PCI CRITICAL: MULTI-digit over-capture must NOT egress the card RAW ------ #
# FIX for the fail-open where a 2-digit over-capture defeated the (old) 0..1 end-trim
# budget: _best_pan_window returned None and _redact_pan returned the run RAW — the
# full card egressing in cleartext (M-3 / NFR-7 (a)). Group-window trimming now drops
# WHOLE stray leading/trailing groups, so 2+ stray digits (separated OR contiguous)
# still re-bound to the real card. MUST FAIL if the group-window scan reverts to a
# fixed 0..1 digit end-trim. --------------------------------------------------- #
@pytest.mark.parametrize(
    "text,pan",
    [
        ("99 4111 1111 1111 1111", "4111111111111111"),      # 2 stray digits, separated group, leading
        ("4111111111111111 12", "4111111111111111"),         # 2 stray digits, separated group, trailing
        ("amount 100 4111111111111111", "4111111111111111"),  # 3 stray digits (amount) leading
        ("ref 55 378282246310005", "378282246310005"),        # 2 stray digits, Amex-15, leading
        ("4111 1111 1111 1111 999", "4111111111111111"),      # 3 stray digits, trailing group
        ("77 4111 1111 1111 1111 88", "4111111111111111"),    # stray groups BOTH ends
    ],
)
def test_pan_multi_stray_digit_group_still_tokenized_never_raw(text, pan):
    out = redact(text)
    # RELEASE-BLOCKING: the full contiguous PAN must NEVER survive anywhere.
    assert pan not in out, f"raw PAN {pan!r} leaked in {out!r}"
    toks = _tokens(out)
    assert len(toks) == 1 and toks[0][0] == "CARD", (
        f"card not tokenized (leaked raw?) for {text!r}: {out!r}"
    )
    # No 13+ contiguous card-digit run survives.
    assert pan[:13] not in out and pan[-13:] not in out


# ---- PCI CRITICAL (R3-C1): a PAN that SLIDES PAST the fixed-width candidate window --
# The candidate regex used to cap at ``{12,18}\d`` (a 13-19-digit window). A run of 20+
# digits across separated groups (2+ stray leading groups + a 16-digit card) matched
# only the FIRST 19 digits — the regex ENDED MID-CARD (before the card's last group),
# handing _best_pan_window a fragment with no complete card, so the full Visa PAN
# egressed RAW (and a variant mis-tokenized the strays as PHONE while stranding raw card
# digits). The candidate now captures the WHOLE group-run and _best_pan_window slides a
# 13-19-digit window across ALL sub-runs. MUST FAIL if the candidate re-acquires a fixed
# upper digit cap (the run then never contains a full card window). ------------------ #
@pytest.mark.parametrize(
    "text,pan",
    [
        ("ref 12 34 4111 1111 1111 1111", "4111111111111111"),    # 2 stray 2-digit groups (20 digits total)
        ("ref 12 34 56 4111 1111 1111 1111", "4111111111111111"),  # 3 stray 2-digit groups (22 digits total)
        ("ref 12 34 4111 1111 1111 1111 56", "4111111111111111"),  # stray groups on BOTH sides
        ("id 98 76 5555 5555 5555 4444", "5555555555554444"),      # MC card past a 2-group prefix
    ],
)
def test_pan_multi_group_run_wider_than_window_never_egresses_raw(text, pan):
    out = redact(text)
    # RELEASE-BLOCKING: the full contiguous PAN must NEVER survive anywhere.
    assert pan not in out, f"raw PAN {pan!r} leaked in {out!r} (R3-C1 fail-open)"
    toks = _tokens(out)
    cards = [t for t, _ in toks if t == "CARD"]
    assert cards == ["CARD"], f"card not tokenized once for {text!r}: {out!r}"
    # The card was masked to its REAL first6/last4, and no partial card was mis-tokenized
    # as PHONE/SECRET (the R3-C1 variant symptom).
    card_meta = next(meta for t, meta in toks if t == "CARD")
    assert card_meta == f"{pan[:6]}:{pan[-4:]}", f"wrong CARD meta for {text!r}: {out!r}"
    assert "PHONE" not in {t for t, _ in toks}, f"partial card mis-tokenized as PHONE: {out!r}"
    # No 13+ digit run survives in cleartext once the wire tokens are stripped.
    stripped = _WIRE.sub("", out)
    assert not any(len(r) >= 13 for r in re.findall(r"\d+", stripped)), (
        f"13+ digit run survived in cleartext for {text!r}: {out!r}"
    )


# ---- PCI CRITICAL: TWO adjacent cards in ONE candidate run — both must mask -------
# The whole-group-run candidate can capture MORE THAN ONE card in a single match (two
# space-adjacent PANs = one 32-digit run). Masking only the single best window would
# tokenize the first card and egress the second RAW. _redact_all_pan_windows recurses on
# the prefix/suffix so EVERY card masks. MUST FAIL if _redact_pan reverts to a single
# window per candidate (the trailing card then leaks). ------------------------------ #
@pytest.mark.parametrize(
    "text,pans",
    [
        ("cards 4111 1111 1111 1111 5555 5555 5555 4444",
         ["4111111111111111", "5555555555554444"]),
        ("4111111111111111 5555555555554444",
         ["4111111111111111", "5555555555554444"]),
        ("ref 12 34 4111 1111 1111 1111 5555 5555 5555 4444",
         ["4111111111111111", "5555555555554444"]),
    ],
)
def test_multiple_adjacent_pans_in_one_run_all_tokenized(text, pans):
    out = redact(text)
    toks = _tokens(out)
    cards = [t for t, _ in toks if t == "CARD"]
    assert len(cards) == len(pans), (
        f"expected {len(pans)} CARD tokens, got {toks} for {text!r}: {out!r}"
    )
    for pan in pans:
        assert pan not in out, f"raw PAN {pan!r} leaked in {out!r}"
    # No card survives once tokens + separators are stripped.
    despaced = re.sub(r"[ \t\r\n\-./,_]", "", _WIRE.sub("", out))
    for pan in pans:
        assert pan not in despaced, f"separated PAN {pan!r} survived: {out!r}"


# ---- PCI HIGH: the RIGHT (real-card) window is masked; no bogus meta, no stranded
# real card digit. A stray digit adjacent to a valid PAN can form a WRONG Luhn-valid
# window (a longer/shifted run) whose first6/last4 is bogus and which strands a real
# card digit outside the token in cleartext. Group-anchored, standard-length window
# selection masks the REAL card. MUST FAIL if selection reverts to "any Luhn-valid /
# longest / fewest-trims" window. --------------------------------------------- #
@pytest.mark.parametrize(
    "text,pan",
    [
        ("amount 100 4111111111111111", "4111111111111111"),  # injected "004..." window would give BIN 004111
        ("4111 1111 1111 1111 99", "4111111111111111"),       # injected "...199" window would give last4 1199 + stranded '4'
        ("txn 8 4012888888881881 3", "4012888888881881"),     # shifted window would give last4 8813 + stranded digit
    ],
)
def test_pan_wrong_window_not_masked_real_bin_and_last4(text, pan):
    out = redact(text)
    toks = _tokens(out)
    assert len(toks) == 1 and toks[0][0] == "CARD", f"not tokenized: {out!r}"
    # Meta is the REAL card's first6/last4 — never a window shifted by an injected
    # digit (which would put an injected digit into the BIN or the last4).
    assert toks[0][1] == f"{pan[:6]}:{pan[-4:]}", (
        f"bogus/shifted PAN window meta {toks[0][1]!r} for {text!r}"
    )
    assert pan not in out
    # No real card digit is stranded outside the token in cleartext. Strip the wire
    # tokens (their meta legitimately holds first6/last4) and assert no card boundary
    # digit-run leaks: neither the card's leading nor trailing 4 digits survive as a
    # standalone run in the remaining cleartext. In the "4111...99" bug the leading
    # '4' was left as a bare token-adjacent digit; here the whole card group is inside
    # the token and only the genuinely non-card stray group ("99"/"100"/"3") remains.
    stripped = _WIRE.sub("", out)
    leftover_runs = re.findall(r"\d+", stripped)
    assert all(pan[:4] not in run and pan[-4:] not in run for run in leftover_runs), (
        f"stranded card boundary digits in cleartext: {leftover_runs!r} for {out!r}"
    )


# ---- non-ASCII digit PAN: never mistaken for a card, never partial-emitted --- #
def test_non_ascii_digit_pan_never_emits_raw_partial_pan_in_meta():
    # A PAN written in Devanagari/Arabic-Indic digits matches \d but is NOT ASCII.
    # It must never (a) coincidentally Luhn-pass on ord()-48 garbage and emit the
    # raw non-ASCII partial-PAN into the CARD meta (cleartext PII on the wire), nor
    # (b) be treated as a card at all. _best_pan_window extracts ASCII-only digits,
    # so a non-ASCII-digit run yields no CARD token and no raw partial-PAN meta.
    for base in (0x0966, 0x0660):  # Devanagari, Arabic-Indic
        pan = "".join(chr(base + int(d)) for d in "4111111111111111")
        out = redact(f"card {pan}")
        toks = _tokens(out)
        assert all(t != "CARD" for t, _ in toks), (
            f"non-ASCII-digit run wrongly tokenized as CARD: {out!r}"
        )
        # No non-ASCII digit ever appears inside a wire-token meta (partial-PAN leak).
        for _, meta in toks:
            if meta:
                assert all(ord(ch) < 0x80 for ch in meta), (
                    f"non-ASCII partial-PAN leaked into meta: {meta!r}"
                )


# ---- PCI: SAD (CVV/track/PIN) dropped entirely, NO meta (never-store) ------ #
@pytest.mark.parametrize(
    "text,label",
    [
        ("cvv: 123", "cvv"),
        ("CVV2 4567", "cvv2"),
        ("the pin is 4821", "pin"),
        ("security code: 999", "security"),
    ],
)
def test_pci_zero_miss_sad_dropped_no_meta(text, label):
    out = redact(text)
    toks = _tokens(out)
    assert ("SAD", None) in toks, f"SAD not dropped for {text!r}: {toks}"
    # The raw SAD value must be gone and NO meta retained (never first/last).
    assert not re.search(r":SAD:", out)     # SAD carries no meta segment
    # the numeric secret value itself is gone
    for tok_type, meta in toks:
        assert meta is None or ":" not in (meta or "")


def test_sad_value_fully_removed():
    out = redact("cvv 321")
    assert "321" not in out


# A Luhn-valid PAN that trails a SAD label in SEPARATED form. The SAD value capture
# ``(\d{3,6})`` bites only the leading group ("4111"); left unguarded, SAD would
# tokenize just that group and the remaining 12 digits ("1111 1111 1111") — below the
# PAN 13-digit floor — would egress as cleartext, a partially-redacted PAN (M-3 /
# NFR-7 (a) PCI fail-open; E1.4 forbids emitting a partially-redacted PAN). Contiguous
# cards after a SAD label were always safe; this pins the space- and hyphen-separated
# gap. Release-blocking (WS-E acceptance §5 — a leaked card digit fails it).
@pytest.mark.parametrize(
    "text",
    [
        "pin is 4111 1111 1111 1111",       # PIN + space-separated Visa
        "cvv 4111 1111 1111 1111",          # CVV + space-separated Visa
        "pin: 4111-1111-1111-1111",         # PIN + hyphen-separated Visa
        "security code 4111 1111 1111 1111",
        "cvv: 4012 8888 8888 1881",         # another Luhn-valid Visa, grouped
    ],
)
def test_sad_label_before_separated_pan_never_leaks_card_digits(text):
    out = redact(text)
    toks = _tokens(out)
    # The whole card must be tokenized as CARD with first6/last4 meta — NOT dropped to
    # a bare SAD token that strands the tail in cleartext.
    assert ("CARD", "411111:1111") in toks or any(
        t == "CARD" for t, _ in toks
    ), f"card not tokenized for {text!r}: {out!r}"
    # No raw run of >=4 consecutive card digits may survive OUTSIDE a wire token. Strip
    # the tokens (their meta legitimately holds first6/last4) and separators, then scan.
    outside = _WIRE.sub("", out).replace(" ", "").replace("-", "")
    assert not re.search(r"\d{4,}", outside), (
        f"raw >=4-digit card run survived for {text!r}: {out!r}"
    )


# ---- PCI HIGH (R3-H1): a SEPARATE SAD value immediately before a separated PAN ------
# When the SAD value is a DISTINCT group sitting before the card (``cvv 999 4111 1111
# 1111 1111`` — 999 is the CVV, 4111… is the card), the SAD guard used to DECLINE the
# whole match (stepping aside for _redact_pan), so the CVV egressed RAW while only the
# card masked — a SAD never-store violation. BOTH must now redact: the SAD value dropped
# to a no-meta <SAD> AND the trailing card tokenized. MUST FAIL if the guard reverts to
# declining whenever the trailing run contains a card (the CVV then leaks raw). This is
# distinct from the case where the SAD value IS the card's own leading group ("pin is
# 4111 1111 1111 1111"), which correctly declines to let PAN mask the whole card. ---- #
@pytest.mark.parametrize(
    "text,sad_value,pan",
    [
        ("cvv 999 4111 1111 1111 1111", "999", "4111111111111111"),
        ("pin is 321 4012 8888 8888 1881", "321", "4012888888881881"),
        ("security code 456 5555 5555 5555 4444", "456", "5555555555554444"),
    ],
)
def test_sad_value_before_separated_pan_redacts_both_never_leaks_cvv(text, sad_value, pan):
    out = redact(text)
    toks = _tokens(out)
    # BOTH controls fired: a no-meta SAD (the CVV dropped) AND the card tokenized.
    assert ("SAD", None) in toks, f"CVV/SAD value not dropped for {text!r}: {out!r}"
    cards = [(t, meta) for t, meta in toks if t == "CARD"]
    assert len(cards) == 1 and cards[0][1] == f"{pan[:6]}:{pan[-4:]}", (
        f"card not tokenized to real first6/last4 for {text!r}: {out!r}"
    )
    # The raw CVV value is GONE (never-store) and the full PAN never egresses.
    # Strip the wire tokens FIRST: the ⟦AEGR:{nonce}:…⟧ nonce is 16 random hex
    # chars, so a short numeric SAD value (999/321/456) is valid hex and collides
    # with the nonce as an incidental substring ~0.3% of the time — a `not in out`
    # against the un-stripped output false-fails on a nonce coincidence, not a real
    # leak. Same nonce-stripping idiom as test_pci_deterministic.py:142.
    stripped = _WIRE.sub("", out)
    assert sad_value not in stripped, f"raw CVV {sad_value!r} leaked (R3-H1) in {out!r}"
    assert pan not in stripped, f"raw PAN {pan!r} leaked in {out!r}"


def test_sad_value_IS_card_leading_group_declines_to_card_only():
    # Negative control paired with the above: when the SAD value is the card's OWN
    # leading group, there is no separate CVV — the whole card must tokenize and NO
    # spurious SAD token appears (the guard declines correctly). MUST FAIL if the guard
    # over-eagerly drops the leading group to <SAD> (re-opening the R2-C2 partial-PAN).
    out = redact("pin is 4111 1111 1111 1111")
    toks = _tokens(out)
    assert [t for t, _ in toks] == ["CARD"], f"expected card-only, got {out!r}"
    assert ("SAD", None) not in toks, f"spurious SAD on card leading group: {out!r}"


# ---- HIPAA Safe-Harbor structured identifiers ------------------------------ #
def test_ssn_email_phone_ip_url_date_tokenized():
    text = (
        "SSN 123-45-6789, mail bob@example.com, call 415-555-0132, "
        "ip 10.0.0.5, see https://acme.test/x, dob 2026-07-01"
    )
    out = redact(text)
    types = {t for t, _ in _tokens(out)}
    assert {"SSN", "EMAIL", "PHONE", "IP", "URL", "DATE"} <= types
    for raw in ("123-45-6789", "bob@example.com", "415-555-0132", "10.0.0.5",
                "acme.test", "2026-07-01"):
        assert raw not in out


# ---- IP: BOTH families (HIPAA SH #18 is generic — FIX-B, NFR-7 (a)) --------- #
# REGRESSION (fail-open PHI leak): the ``IP`` token in LLD 29 §3.1 (line 152) is
# generic — it is NOT IPv4-only. An IPv6 address that egressed RAW to the hosted PDP
# is a structured-identifier leak just like a leaked IPv4 (NFR-7 (a)). Before FIX-B
# only ``_IPV4`` was implemented, so ``2001:db8::1`` / ``fe80::…`` / ``::1`` egressed
# in cleartext. These pin BOTH families to the same ⟦…:IP⟧ token. They FAIL if the
# IPv6 arm is reverted (the raw address survives), so they are not vacuous.
_IPV6_ADDRESSES = [
    "2001:0db8:85a3:0000:0000:8a2e:0370:7334",  # full 8-group (the finding's example)
    "2001:db8::8a2e:370:7334",                  # ::-compressed
    "fe80::200:5aee:feaa:20a2",                 # link-local, compressed
    "fe80::1",                                  # short link-local
    "::1",                                      # loopback
    "2001:db8:0:0:0:0:2:1",                     # uncompressed zeros
    "::ffff:192.168.1.1",                       # IPv4-mapped IPv6
]


@pytest.mark.parametrize("ip", _IPV6_ADDRESSES)
def test_ipv6_is_tokenized_and_never_egresses_raw(ip):
    out = redact(f"server {ip} is down")
    toks = _tokens(out)
    assert ("IP", None) in toks, f"IPv6 {ip!r} not tokenized: {out!r}"
    # RELEASE-BLOCKING: the raw address must be GONE from the egress text. For the
    # IPv4-mapped form the whole ``::ffff:192.168.1.1`` collapses to one token — the
    # embedded dotted tail must not be stranded in cleartext (partial redaction).
    assert ip not in out, f"raw IPv6 {ip!r} leaked in {out!r}"
    for chunk in ip.split(":"):
        # No non-trivial hextet / embedded-IPv4 chunk of the address survives raw
        # (skip empty chunks from ``::`` and 1-char chunks that legitimately recur
        # inside the random nonce hex).
        if len(chunk) >= 2:
            assert chunk not in out, f"IPv6 chunk {chunk!r} leaked in {out!r}"


@pytest.mark.parametrize(
    "text",
    [
        "std::vector<int> nums;",       # C++ scope resolution (alpha hextets, no digit)
        "call foo::bar::baz() now",     # scope resolution chain
        "namespace Aaa::Bbb here",      # alpha-only
    ],
)
def test_scope_resolution_prose_is_not_mistaken_for_ipv6(text):
    # False-positive guard: ``::`` in code/prose whose hextets are purely-alpha
    # valid-hex words (``std``, ``foo``, ``bar``) parses as a valid IPv6 address
    # (``d:: == d:0:0:…``) but is NOT PHI. The digit-required gate keeps it as-is.
    # Over-masking here would corrupt legitimate param signal the PDP needs.
    out = redact(text)
    assert not _tokens(out), f"scope-resolution mis-masked as IP: {out!r}"
    assert out == text, f"prose altered: {out!r}"


def test_mac_address_and_time_not_mistaken_for_ipv6():
    # A MAC (6 hex pairs) and an HH:MM:SS time are colon-bearing but are NOT IPv6
    # addresses — the stdlib validator rejects them, so they must pass through.
    for text in ("nic 00:1B:44:11:3A:B7 up", "logged at 09:30:45 today"):
        out = redact(text)
        assert not _tokens(out), f"non-IP colon run mis-masked: {out!r}"


def test_ipv4_still_tokenized_after_ip_matcher_change():
    # Guard that adding the IPv6 arm did not regress IPv4 (the finding is IPv6-only).
    out = redact("db host 10.0.0.5 and gw 192.168.1.1")
    toks = _tokens(out)
    assert [t for t, _ in toks] == ["IP", "IP"], f"IPv4 regressed: {out!r}"
    assert "10.0.0.5" not in out and "192.168.1.1" not in out


def test_labelled_ids_format_anchored():
    out = redact("MRN: A1234567 and account no 998877")
    types = {t for t, _ in _tokens(out)}
    assert "MRN" in types
    assert "ACCOUNT" in types
    assert "A1234567" not in out
    assert "998877" not in out


def test_bare_number_without_label_is_not_a_labelled_id():
    # A bare number with no label + not Luhn/format-anchored must NOT be masked as
    # an ID — bounds false positives (E1.1 format-anchored, not pure shape).
    out = redact("the total was 12345 dollars")
    assert "12345" in out
    assert not _tokens(out)


@pytest.mark.parametrize(
    "text,domain",
    [
        ("license jsmith@acme.com", "acme.com"),
        ("account holder1@corp.io", "corp.io"),
        ("device admin99@bar.example", "bar.example"),
        ("acct: sales.team@vendor.co.uk", "vendor.co.uk"),
    ],
)
def test_email_adjacent_to_labelled_id_word_does_not_leak_domain(text, domain):
    # REGRESSION (partial-redaction PII leak): a LABELLED_ID label word ("license"/
    # "account"/"device"/"acct") immediately before an email must NOT let the
    # labelled-id value capture steal the email local-part and leave the raw domain
    # in cleartext. EMAIL must run before LABELLED_ID (frozen order). The whole
    # email is one EMAIL token and the domain never egresses (NFR-7 (a) / E1.4).
    out = redact(text)
    toks = _tokens(out)
    assert ("EMAIL", None) in toks, f"email not tokenized in {text!r}: {toks}"
    assert domain not in out, f"raw domain {domain!r} leaked in {out!r}"
    # No LABELLED_ID token stole the local-part.
    assert all(t not in ("LICENSE", "ACCOUNT", "DEVICE") for t, _ in toks)


def test_email_and_url_precede_labelled_id_in_frozen_order():
    # The fix is order-based: pin EMAIL (and URL) before LABELLED_ID so the fix
    # can't be silently reverted by reordering the matcher tuple.
    order = [name for name, _ in R._ORDERED_MATCHERS]
    assert order.index("EMAIL") < order.index("LABELLED_ID")
    assert order.index("URL") < order.index("LABELLED_ID")


def test_plain_labelled_id_still_redacts_after_reorder():
    # Reordering EMAIL/URL earlier must NOT stop a genuine labelled id (no email)
    # from being tokenized.
    out = redact("license no A1234567")
    types = {t for t, _ in _tokens(out)}
    assert "LICENSE" in types
    assert "A1234567" not in out


# ---- high-entropy secret (LAST, broadest) ---------------------------------- #
def test_high_entropy_secret_masked():
    secret = "sk_live_AbCd1234EfGh5678IjKl9012MnOp"
    out = redact(f"key={secret}")
    assert ("SECRET", None) in _tokens(out)
    assert secret not in out


def test_long_english_prose_not_masked_as_secret():
    # A long lowercase word must not trip the secret matcher (charset/entropy gate).
    prose = "responsibilities"  # 16 chars, low entropy, single-case
    out = redact(f"my {prose} include auditing")
    assert prose in out
    assert "SECRET" not in out


def test_known_credential_prefixes_masked_regardless_of_entropy():
    # A 20-char AWS access-key id is all upper+digit (mixed=False) with entropy
    # < 4.0, so the generic charset/entropy gate misses it. Prefix-anchoring the
    # known credential formats masks it — otherwise a credential egresses RAW
    # (NFR-7 (a)). MUST FAIL if the _SECRET_PREFIXES rule is reverted.
    for cred in (
        "AKIAIOSFODNN7EXAMPLE",      # AWS access-key id (upper+digit, entropy < 4)
        "ASIAIOSFODNN7EXAMPLE",      # AWS session key id
        "ghp_1234567890ABCDEFghij",  # GitHub PAT
    ):
        out = redact(f"key={cred}")
        assert ("SECRET", None) in _tokens(out), f"{cred!r} not masked: {out!r}"
        assert cred not in out, f"raw credential {cred!r} leaked in {out!r}"


# ---- obfuscation: NFKC normalization before matching (Appendix G (ii)) ----- #
_FW = {str(d): chr(0xFF10 + d) for d in range(10)}  # ASCII digit -> fullwidth


def _fullwidth(s: str) -> str:
    return "".join(_FW.get(ch, ch) for ch in s)


def test_fullwidth_digit_pan_is_normalized_and_tokenized():
    # RELEASE-BLOCKING (fail-open PCI leak): a card written with a fullwidth digit
    # must NFKC-normalize to ASCII and be caught as a CARD — not egress raw. MUST
    # FAIL if the NFKC normalization is reverted.
    raw_ascii = "4111 1111 1111 1111"
    obfuscated = "4111１111 1111 1111"  # one fullwidth '1' inside the run
    out = redact(f"my card is {obfuscated}")
    toks = _tokens(out)
    assert len(toks) == 1 and toks[0][0] == "CARD", f"not caught: {out!r}"
    # first6/last4 meta is ASCII (normalized), never the raw fullwidth digits.
    assert toks[0][1] == "411111:1111"
    assert "１" not in out                       # no fullwidth digit egresses
    assert re.sub(r"\D", "", raw_ascii) not in out   # full contiguous PAN gone


def test_pure_fullwidth_pan_meta_is_ascii_not_raw_partial_pan():
    # A pure-fullwidth 16-digit PAN must normalize to ASCII BEFORE Luhn/meta so the
    # CARD meta is ASCII first6/last4, never raw non-ASCII partial-PAN cleartext on
    # the wire (and Luhn is computed on real digits, not ord()-48 garbage).
    fw_pan = _fullwidth("4111111111111111")
    out = redact(fw_pan)
    toks = _tokens(out)
    assert len(toks) == 1 and toks[0][0] == "CARD"
    assert toks[0][1] == "411111:1111"               # ASCII meta
    for fw_digit in _FW.values():
        assert fw_digit not in out                   # no fullwidth digit anywhere


# ---- M-4: matcher order is a security control ------------------------------ #
def test_matcher_order_is_frozen():
    order = [name for name, _ in R._ORDERED_MATCHERS]
    # SAD first, PAN(CARD) before any bare-numeric, SECRET last (broadest).
    assert order[0] == "SAD"
    assert order.index("CARD") < order.index("SECRET")
    assert order[-1] == "SECRET"
    # PAN must precede the entropy secret matcher (a PAN is high-entropy digits).
    assert order.index("CARD") < order.index("SECRET")


def test_pan_wins_over_secret_when_both_could_match():
    # A raw PAN is also a long digit run; the frozen order must token it as CARD
    # (keeping first6/last4), never as an opaque SECRET.
    out = redact("4111111111111111")
    toks = _tokens(out)
    assert [t for t, _ in toks] == ["CARD"]


# ---- M-4: planted-token neutralization (NEGATIVE CONTROL) ------------------ #
def test_planted_token_cannot_forge_marker():
    # An attacker plants the reserved wire sentinel in raw input, trying to forge
    # a "redaction happened" marker with a chosen nonce. After redaction NO token
    # bearing the attacker's forged content may survive — the only real tokens are
    # the ones WE mint. This MUST FAIL if _neutralize_planted_tokens is removed.
    forged = "⟦AEGR:deadbeefdeadbeef:CARD:hacked⟧ and ⟦stray brackets⟧"
    out = redact(forged)
    # The attacker's sentinel brackets are stripped -> no forged marker remains.
    assert "deadbeefdeadbeef" not in out
    assert "⟦" not in out and "⟧" not in out
    assert not _tokens(out)  # nothing the attacker planted reads as a real marker


def test_planted_token_around_real_pii_still_redacts_real_pii():
    # Neutralizing planted sentinels must not stop us redacting genuine PII in the
    # same field.
    out = redact("⟦AEGR:0000000000000000:SSN⟧ real ssn 123-45-6789")
    toks = _tokens(out)
    # exactly one token, and it's a REAL redaction (fresh nonce, not 0000...).
    assert [t for t, _ in toks] == ["SSN"]
    assert "0000000000000000" not in out
    assert "123-45-6789" not in out


def test_bare_angle_bracket_token_is_not_the_wire_form():
    # A descriptive/UI <CARD> is never the wire form; it can't spoof a real marker.
    out = redact("literally <CARD> here")
    assert "<CARD>" in out          # left as harmless text
    assert not _tokens(out)         # it is NOT a wire token


def test_per_call_nonce_differs():
    a = redact_detailed("ssn 123-45-6789")
    b = redact_detailed("ssn 123-45-6789")
    na = _WIRE.search(a.text).group(1)
    nb = _WIRE.search(b.text).group(1)
    assert na != nb, "nonce must be fresh per call (M-4)"


# ---- M-4: a later matcher must NOT re-enter an earlier emitted token -------- #
# Every wire token in the output MUST be well-formed ⟦AEGR:16hex:TYPE[:meta]⟧ with
# NO nesting — i.e. no `⟦AEGR:` substring may appear inside another token. The nonce
# is 16 hex chars and can contain a Luhn-valid 13-19 digit run; before the fix,
# _redact_pan (which runs AFTER _redact_sad) found that run INSIDE an emitted SAD
# token's nonce, masked it, and nested a CARD token inside the SAD token — mangling
# the nonce so the PDP could no longer verify the marker. These are negative controls:
# both MUST FAIL if _apply_outside_tokens is reverted (a matcher runs over the whole
# accumulating text again).
def _tokens_are_well_formed(out: str) -> bool:
    spans = list(re.finditer(r"⟦[^⟧]*⟧", out))
    for m in spans:
        if not _WIRE.fullmatch(m.group(0)):
            return False
        # no reserved-namespace open-sequence may hide inside a token body
        if "⟦AEGR:" in m.group(0)[len("⟦"):]:
            return False
    return True


def test_nonce_with_luhn_run_does_not_corrupt_earlier_token():
    # DETERMINISTIC repro: this nonce contains the 14-digit Luhn-valid run
    # "86110212678670" — the exact value that nested a CARD inside a SAD token.
    nonce = "3f86110212678670"
    out = redact("pin is 4821 and akiaIOSFODNN7EXAMPLE", nonce=nonce)
    assert _tokens_are_well_formed(out), f"token corrupted by later matcher: {out!r}"
    # The SAD token's nonce survives intact (not chewed by _redact_pan).
    assert f"⟦AEGR:{nonce}:SAD⟧" in out, f"SAD token nonce mangled: {out!r}"
    # And every genuine marker still carries the single call nonce.
    assert {m.group(1) for m in _WIRE.finditer(out)} == {nonce}


def test_random_nonces_never_corrupt_emitted_tokens():
    # SWEEP: with fresh CSPRNG nonces, a payload that emits several tokens must never
    # produce a malformed/nested token, regardless of the nonce's digit content.
    payloads = [
        "pin is 4821 and akiaIOSFODNN7EXAMPLE",
        "charge 4111111111111111 now and ssn 123-45-6789",
        "cvv 4111 1111 1111 1111 date 2026-07-01",
        "sha 5f4dcc3b5aa765d61d8327deb882cf99 and card 5555555555554444",
    ]
    for _ in range(3000):
        for s in payloads:
            out = redact(s)
            assert _tokens_are_well_formed(out), f"corrupt token for {s!r}: {out!r}"


# ---- E1.4 / E1.5: fail-secure -------------------------------------------- #
def test_redact_rejects_non_string():
    with pytest.raises(RedactionError):
        redact(1234)  # type: ignore[arg-type]


def test_redact_internal_error_is_fail_secure(monkeypatch):
    # Force a matcher to blow up; redact() must raise RedactionError (fail secure),
    # NOT return the raw/partial value.
    def _boom(text, nonce):
        raise ValueError("simulated matcher crash")

    monkeypatch.setattr(R, "_ORDERED_MATCHERS", (("BOOM", _boom),))
    with pytest.raises(RedactionError):
        redact("some 123-45-6789 pii")


def test_redaction_error_message_carries_no_raw_value(monkeypatch):
    # A redactor failure must not itself leak the raw content (NFR-7 (a)).
    def _boom(text, nonce):
        raise ValueError("crash")

    monkeypatch.setattr(R, "_ORDERED_MATCHERS", (("BOOM", _boom),))
    secret_value = "123-45-6789"
    try:
        redact(f"ssn {secret_value}")
    except RedactionError as exc:
        assert secret_value not in str(exc)
    else:  # pragma: no cover
        pytest.fail("expected RedactionError")


def test_redact_params_wraps_non_redaction_error_fail_secure(monkeypatch):
    # redact_params is a PUBLIC exported API and the guard (guard._build_request)
    # only catches RedactionError. A non-RedactionError escaping _walk (e.g. a
    # RecursionError on a pathological structure) would bypass the fail-secure DENY
    # and let the raw params egress. redact_params must re-wrap ANY internal failure
    # as RedactionError. MUST FAIL if the try/except wrapper is removed.
    def _boom(_text, _nonce):
        raise RecursionError("simulated deep-structure crash")

    monkeypatch.setattr(R, "_ORDERED_MATCHERS", (("BOOM", _boom),))
    with pytest.raises(RedactionError):
        redact_params({"k": "some 123-45-6789 pii"})


def test_redact_params_wrapped_error_carries_no_raw_value(monkeypatch):
    # The re-wrapped param-redaction error must not leak the raw params (NFR-7 (a)).
    def _boom(_text, _nonce):
        raise RuntimeError("crash")

    monkeypatch.setattr(R, "_ORDERED_MATCHERS", (("BOOM", _boom),))
    secret_value = "123-45-6789"
    try:
        redact_params({"k": f"ssn {secret_value}"})
    except RedactionError as exc:
        assert secret_value not in str(exc)
    else:  # pragma: no cover
        pytest.fail("expected RedactionError")


def test_binary_content_is_refused_not_sent(monkeypatch):
    # FR-3.15 (E1.5): binary/image content is refused, never redacted-or-sent-raw.
    with pytest.raises(RedactionError):
        redact_params({"image": b"\x89PNG\r\n\x1a\n"})


# ---- E1.3: recursive param redaction --------------------------------------- #
def test_redact_params_walks_nested_structures():
    params = {
        "user": {"email": "bob@example.com", "note": "clean"},
        "cards": ["4111111111111111", "no card here"],
        "count": 3,
        "active": True,
    }
    out = redact_params(params)
    assert out["count"] == 3          # non-content leaf preserved
    assert out["active"] is True
    assert "bob@example.com" not in str(out)
    assert "4111111111111111" not in str(out)
    assert "clean" in out["user"]["note"]        # clean text untouched
    assert "no card here" in out["cards"][1]


def test_redact_params_tuple_leaf_redacts_and_coerces_to_list():
    # A tuple leaf in tool_params is walked like a list: its string elements are
    # redacted AND the container is coerced to a list. tool_params are JSON-shaped
    # (JSON has no tuple type — a tuple round-trips to an array), so the coercion is
    # the intended, harmless behavior; this pins it so (a) redaction of tuple-nested
    # content can't silently regress and (b) the list-coercion is a deliberate,
    # tested contract rather than an accidental untested type change (_walk,
    # redaction.py:1003-1004). MUST FAIL if the tuple branch stops recursing (a raw
    # value would then egress) or is changed to a different container semantics.
    params = {"pair": ("4111111111111111", "clean"), "nested": (("bob@example.com",),)}
    out = redact_params(params)
    assert isinstance(out["pair"], list), "tuple leaf must coerce to list (JSON-shaped)"
    assert isinstance(out["nested"], list) and isinstance(out["nested"][0], list)
    flat = str(out)
    assert "4111111111111111" not in flat         # PAN inside tuple redacted
    assert "bob@example.com" not in flat          # email inside nested tuple redacted
    assert "clean" in out["pair"][1]              # clean text untouched


def test_redact_params_does_not_mutate_input():
    params = {"email": "bob@example.com"}
    _ = redact_params(params)
    assert params["email"] == "bob@example.com"  # original untouched


def test_redact_params_redacts_pii_in_dict_keys():
    # REGRESSION: structured PII/PCI in a dict KEY must be redacted, not egress raw.
    # (An agent may key a params dict by an email or an account/card number.)
    params = {
        "alice@corp.com": "value",
        "4111111111111111": {"nested": "acct 998877"},
    }
    out = redact_params(params)
    flat = str(out)
    assert "alice@corp.com" not in flat        # raw email key gone
    assert "4111111111111111" not in flat       # raw PAN key gone
    # The redacted keys carry typed wire tokens (structural signal preserved).
    key_tokens = [t for k in out for t, _ in _tokens(k)]
    assert "EMAIL" in key_tokens
    assert "CARD" in key_tokens
    # Values under the (now-redacted) keys are still walked/redacted.
    assert "998877" not in flat


def test_redact_params_bytes_key_is_refused_not_sent():
    # A bytes key is binary content the text redactor cannot scrub — refuse it,
    # mirroring the bytes-leaf refusal (FR-3.15 / E1.5). Fail secure, never egress.
    with pytest.raises(RedactionError):
        redact_params({b"\x89PNG": "value"})


def test_redact_params_non_string_keys_pass_through():
    # Structural (non-str, non-bytes) keys are not content — they pass through so
    # numeric-keyed maps are not mangled.
    out = redact_params({1: "clean", 2: "also clean"})
    assert 1 in out and 2 in out
    assert out[1] == "clean" and out[2] == "also clean"


def test_clean_text_passes_through_unchanged():
    text = "please look up the weather in Seattle tomorrow"
    assert redact(text) == text


# ---- E6.1: edge image/binary tagging (never pixel-redact, never egress raw) --- #
def test_data_uri_image_is_tagged_not_pixel_redacted():
    blob = "data:image/png;base64," + ("A" * 600)
    out = redact(blob)
    toks = _tokens(out)
    assert [t for t, _ in toks] == ["IMAGE"], f"data-URI not tagged IMAGE: {out!r}"
    assert "A" * 600 not in out                 # raw blob dropped (routed, not sent)


def test_long_high_entropy_base64_blob_is_tagged_image():
    # A bare inlined base64 attachment (no data-URI header) is still tagged + routed.
    import base64
    import os

    blob = base64.b64encode(os.urandom(700)).decode("ascii")
    out = redact(blob)
    assert [t for t, _ in _tokens(out)] == ["IMAGE"], f"blob not tagged: {out[:40]!r}"
    assert blob not in out


def test_prose_and_short_tokens_are_not_mistagged_as_image():
    # Conservative detection: ordinary prose and short/low-entropy tokens must NOT
    # be tagged IMAGE (which would destroy legitimate text). MUST FAIL if the image
    # heuristic over-matches.
    prose = "The quick brown fox jumps over the lazy dog. " * 20  # long but has spaces
    assert "IMAGE" not in redact(prose)
    order = "order-1234567890"        # short, has separator
    assert "IMAGE" not in redact(order)


def test_image_blob_in_params_is_tagged_not_refused():
    # A base64 image STRING leaf is tagged (E6.1), distinct from a raw ``bytes``
    # leaf which is refused (FR-3.15). Both never egress raw.
    blob = "data:image/jpeg;base64," + ("Z" * 700)
    out = redact_params({"attachment": blob})
    assert [t for t, _ in _tokens(out["attachment"])] == ["IMAGE"]
    assert "Z" * 700 not in str(out)


# ---- E7.2: URL query-secret strip ------------------------------------------ #
@pytest.mark.parametrize(
    "secret_param,secret_val",
    [
        ("token", "abc123SECRETtokenvalue456"),
        ("api_key", "AKIAIOSFODNN7EXAMPLE"),
        ("access_token", "ya29.averylongoauthaccesstokenvalue"),
        ("sig", "9f8e7d6c5b4a3210"),
    ],
)
def test_url_query_secret_stripped(secret_param, secret_val):
    # A secret-bearing query value must not egress in cleartext (E7.2). The whole URL
    # collapses to one opaque ⟦…:URL⟧ token, so the query secret is removed WITH the
    # URL — asserted on the real redact() output (the negative control: the raw secret
    # value must be absent, and the URL must be tokenized, not passed through raw).
    url = f"https://api.example.com/x?{secret_param}={secret_val}&page=2"
    out = redact(f"call {url}")
    assert secret_val not in out                    # no raw query secret survives
    assert "https://api.example.com" not in out     # URL not emitted in cleartext
    assert ("URL", None) in _tokens(out)            # the URL was tokenized


# ---- new_nonce public helper ----------------------------------------------- #
def test_new_nonce_is_fresh_16_hex():
    a, b = R.new_nonce(), R.new_nonce()
    assert re.fullmatch(r"[0-9a-f]{16}", a)
    assert a != b


def test_explicit_nonce_is_used_for_all_tokens():
    # When a caller threads an explicit nonce (the guard's per-egress nonce), every
    # genuine marker carries THAT nonce (single-nonce binding, §3.3).
    n = "abcdef0123456789"
    out = redact("ssn 123-45-6789 and mail x@y.com", nonce=n)
    nonces = {m.group(1) for m in _WIRE.finditer(out)}
    assert nonces == {n}


# ==========================================================================
# ROUND-2 MUST-FIX regressions — real raw-value leaks found by adversarial
# verification (2026-07-01). Each test's leaking input is ALSO covered in the
# always-on PCI 0-miss corpus (pci_sad_pan.jsonl) where it is a PAN/SAD; these
# unit tests pin the non-PCI leaks (hex secret, SSN separators, path over-mask)
# and the matcher-level separator behavior. Every one MUST FAIL if its fix is
# reverted (negative control) — they exercise separators / a hex charset the
# round-1 corpus provably did not.
# ==========================================================================


# ---- R2-C1 (CRITICAL): a PAN separated by dot/slash/comma/underscore egressed
# RAW — the space/hyphen-only candidate did not match it (PCI fail-open, M-3 /
# NFR-7 (a)). MUST FAIL if _PAN_SEP / _PAN_CANDIDATE drops any of these separators.
@pytest.mark.parametrize(
    "text,pan",
    [
        ("card 4111.1111.1111.1111 on file", "4111111111111111"),   # dot
        ("pasted 4111/1111/1111/1111 today", "4111111111111111"),   # slash
        ("csv row 4111,1111,1111,1111 imported", "4111111111111111"),  # comma
        ("field 4111_1111_1111_1111 set", "4111111111111111"),      # underscore
        ("bill 5555.5555.5555.4444 monthly", "5555555555554444"),   # dot, MC
        ("amex 3782/822463/10005 approved", "378282246310005"),     # slash, Amex-15
    ],
)
def test_r2c1_separated_pan_is_carded_never_raw(text, pan):
    out = redact(text)
    toks = _tokens(out)
    cards = [(t, meta) for t, meta in toks if t == "CARD"]
    assert len(cards) == 1, f"expected one CARD for {text!r}, got {toks}: {out!r}"
    assert cards[0][1] == f"{pan[:6]}:{pan[-4:]}", (
        f"wrong CARD meta {cards[0][1]!r} for {text!r}"
    )
    # RELEASE-BLOCKING: the full contiguous PAN never survives.
    assert pan not in out, f"raw PAN leaked for {text!r}: {out!r}"
    stripped = _WIRE.sub("", out)
    assert not any(len(run) >= 13 for run in re.findall(r"\d+", stripped)), (
        f"13+ digit run survived in cleartext for {text!r}: {out!r}"
    )


# ---- R2-C1 (CRITICAL, whitespace-separator completion): _PAN_SEP omitted TAB and
# newline, and the candidate allowed only ONE separator char between groups, so a PAN
# pasted from a spreadsheet/TSV cell (TAB-delimited), a multi-line field (LF), or a
# Windows/multi-line paste (two-char CRLF) egressed RAW as a partial-digit run — the
# same PCI fail-open class R2-C1 widened punctuation separators to close, but the
# whitespace forms were left open. The design intent of _PAN_SEP is to cover
# spreadsheet/formatted-field pastes, where TAB is the canonical delimiter, so the
# omission was inconsistent. MUST FAIL if _PAN_SEP drops \t/\r/\n OR if _PAN_CANDIDATE /
# _SAD_VALUE_PAN_RUN drop the up-to-two-separator ({0,2}) run (CRLF is two chars).
@pytest.mark.parametrize(
    "text,pan",
    [
        ("card 4111\t1111\t1111\t1111 on file", "4111111111111111"),   # TAB (TSV)
        ("4111\n1111\n1111\n1111", "4111111111111111"),                # LF (multiline)
        ("4111\r\n1111\r\n1111\r\n1111", "4111111111111111"),          # CRLF (two-char)
        ("row 4111, 1111, 1111, 1111 end", "4111111111111111"),        # comma+space (TSV cell)
        ("amex 3782\t822463\t10005 ok", "378282246310005"),            # TAB, Amex-15
        ("pin is 4111\r\n1111\r\n1111\r\n1111", "4111111111111111"),    # SAD label + CRLF card
    ],
)
def test_r2c1_whitespace_separated_pan_is_carded_never_raw(text, pan):
    out = redact(text)
    toks = _tokens(out)
    # SAD must step aside for the whole card even across a CRLF (no partial-PAN, R2-C2).
    assert ("SAD", None) not in toks, f"SAD wrongly ate a card group in {out!r}"
    cards = [(t, meta) for t, meta in toks if t == "CARD"]
    assert len(cards) == 1, f"expected one CARD for {text!r}, got {toks}: {out!r}"
    assert cards[0][1] == f"{pan[:6]}:{pan[-4:]}", (
        f"wrong CARD meta {cards[0][1]!r} for {text!r}"
    )
    assert pan not in out, f"raw PAN leaked for {text!r}: {out!r}"
    # No 12+ raw card-digit run survives in cleartext (partial-PAN, E1.4).
    stripped = _WIRE.sub("", out)
    assert not any(len(run) >= 12 for run in re.findall(r"\d+", stripped)), (
        f"12+ raw card digits survived (partial-PAN) for {text!r}: {out!r}"
    )


def test_r2c1_whitespace_pan_does_not_join_distant_numbers():
    # NEGATIVE CONTROL: the up-to-two-separator run must NOT let two distant, unrelated
    # numbers merge into a bogus Luhn-valid card. Neither run is 13-19 digits nor Luhn-
    # valid, so no CARD is emitted and no over-mask occurs (bounds the {0,2} widening).
    out = redact("order 12345678 ref 87654321")
    assert "CARD" not in out, f"distant numbers wrongly joined into a card: {out!r}"


# ---- R2-C2 (CRITICAL): a SAD label before a dot/slash-separated PAN produced a
# partial-redacted PAN — SAD ate the leading group and 12 real card digits egressed
# behind a marker that FALSELY looked redacted (worse than a plain miss; E1.4 no
# partial-PAN). The SAD footgun guard must step aside for the whole card. MUST FAIL
# if _SAD_VALUE_PAN_RUN's separator set falls behind _PAN_SEP.
@pytest.mark.parametrize(
    "text,pan",
    [
        ("pin is 4111.1111.1111.1111", "4111111111111111"),          # dot
        ("cvv 4111/1111/1111/1111", "4111111111111111"),             # slash
        ("security code 5105.1051.0510.5100", "5105105105105100"),   # dot, MC
    ],
)
def test_r2c2_sad_label_before_separated_pan_no_partial_pan(text, pan):
    out = redact(text)
    toks = _tokens(out)
    # The WHOLE card is a single CARD token (SAD declined) — never a SAD token that
    # strands the trailing card digits in cleartext.
    assert ("SAD", None) not in toks, f"SAD wrongly ate a card group in {out!r}"
    cards = [(t, meta) for t, meta in toks if t == "CARD"]
    assert len(cards) == 1 and cards[0][1] == f"{pan[:6]}:{pan[-4:]}", (
        f"card not fully tokenized for {text!r}: {out!r}"
    )
    assert pan not in out, f"raw PAN leaked for {text!r}: {out!r}"
    stripped = _WIRE.sub("", out)
    assert not any(len(run) >= 12 for run in re.findall(r"\d+", stripped)), (
        f"12+ raw card digits survived (partial-PAN) for {text!r}: {out!r}"
    )


# ---- R2-H1 (HIGH): a long all-lowercase-hex credential (SHA1/SHA256 digest, hex
# session token, hex API key) egressed RAW — it cleared the ≥3.5 entropy floor but
# failed BOTH the mixed-charset gate (all-lowercase) AND the ≥4.0 fallback (16-symbol
# hex caps at 4.0). MUST FAIL if the _HEX_SECRET rule is reverted (credential leak,
# NFR-7 (a)).
@pytest.mark.parametrize(
    "hexval",
    [
        "da39a3ee5e6b4b0d3255bfef95601890afd80709",                          # SHA1 (40)
        "d41d8cd98f00b204e9800998ecf8427e",                                  # MD5 (32)
        "da39a3ee5e6b4b0d3255bfef95601890afd80709da39a3ee5e6b4b0d3255bfef",  # SHA256-len (64)
    ],
)
def test_r2h1_lowercase_hex_credential_masked(hexval):
    out = redact(f"apikey={hexval}")
    assert ("SECRET", None) in _tokens(out), f"hex secret not masked: {out!r}"
    assert hexval not in out, f"raw hex credential leaked in {out!r}"


# ---- R2-H1 (HIGH, uppercase/mixed-case completion): the hex-secret rule was
# lowercase-only (``^[0-9a-f]{32,}$``), so an UPPER-case or mixed-case hex digest/token
# (upper SHA1/SHA256/MD5, an uppercase HMAC signature, an uppercase hex session key)
# egressed RAW while its lowercase twin was masked — the leak was charset-CASE-
# dependent (an all-upper hex run has no lowercase char so ``mixed=False``, and a
# 16-symbol hex alphabet caps Shannon entropy at ~3.7 < 4.0, so the mixed-charset gate,
# the ≥4.0 fallback, AND a lowercase-only _HEX_SECRET ALL miss it). MUST FAIL if
# _HEX_SECRET reverts to lowercase-only (credential leak, NFR-7 (a)). The lowercase
# twin is asserted too, so the test pins that behaviour is case-INDEPENDENT.
@pytest.mark.parametrize(
    "hexval",
    [
        "DA39A3EE5E6B4B0D3255BFEF95601890AFD80709",                          # UPPER SHA1 (40)
        "D41D8CD98F00B204E9800998ECF8427E",                                  # UPPER MD5 (32)
        "DA39A3EE5E6B4B0D3255BFEF95601890AFD80709DA39A3EE5E6B4B0D3255BFEF",  # UPPER SHA256-len (64)
        "Da39A3ee5E6b4B0d3255BfeF95601890afD80709",                         # MIXED-case hex (40)
    ],
)
def test_r2h1_uppercase_and_mixed_hex_credential_masked(hexval):
    out = redact(f"apikey={hexval}")
    assert ("SECRET", None) in _tokens(out), (
        f"upper/mixed hex secret not masked (case-dependent leak): {out!r}"
    )
    assert hexval not in out, f"raw hex credential leaked in {out!r}"
    # Case-INDEPENDENCE: the lowercase twin of the same digest is masked identically.
    lower = hexval.lower()
    lout = redact(f"apikey={lower}")
    assert ("SECRET", None) in _tokens(lout) and lower not in lout, (
        f"lowercase twin behaves differently — masking must be case-independent: {lout!r}"
    )


# ---- R2-M1 (MEDIUM): a space- or dot-separated SSN egressed RAW — the matcher was
# dash-only. MUST FAIL if _SSN drops the space/dot separators. (A mixed/garbage
# separator run must still NOT match — the groups share ONE separator.)
@pytest.mark.parametrize(
    "text,ssn",
    [
        ("SSN: 123-45-6789", "123-45-6789"),   # dash (was already covered)
        ("SSN: 123 45 6789", "123 45 6789"),   # space (leaked)
        ("SSN: 123.45.6789", "123.45.6789"),   # dot (leaked)
    ],
)
def test_r2m1_separated_ssn_masked(text, ssn):
    out = redact(text)
    assert ("SSN", None) in _tokens(out), f"SSN not masked for {text!r}: {out!r}"
    assert ssn not in out, f"raw SSN leaked for {text!r}: {out!r}"


def test_r2m1_ssn_mixed_separator_not_matched():
    # A run with inconsistent separators is not an SSN shape — it must NOT be masked
    # as one (guards the back-reference; bounds false positives).
    out = redact("code 123-45 6789 here")
    assert "SSN" not in out


# ---- R2-M2 (MEDIUM, fail-SECURE quality not a leak): the SECRET charset includes
# '/', so a plain file_path / s3:// URI param got over-masked to <SECRET>, destroying
# the param signal the PDP needs for Cedar param-bounds / sequence checks on the
# financial-action beachhead. A path/URI (no secret-shaped segment) must pass through
# unchanged. MUST FAIL if the path/URI exclusion is reverted (regression = over-mask).
@pytest.mark.parametrize(
    "path",
    [
        "s3://my-bucket/reports/q3/financials.csv",
        "/var/log/app/output/report-2026.txt",
        "/usr/local/share/data/customer/records",
        "https://acme.test/reports/q3/financials",  # host+path, no query secret
    ],
)
def test_r2m2_path_and_uri_not_over_masked_as_secret(path):
    out = redact(path)
    assert "SECRET" not in out, f"path over-masked to SECRET: {out!r}"


def test_r2m2_path_exclusion_does_not_leak_slash_bearing_secret():
    # NEGATIVE CONTROL: the R2-M2 path exclusion must NOT let a genuine base64/slash-
    # bearing secret through — a secret has a high-entropy segment, a path does not.
    secret = "aB3dEf9kL2mN8pQ4rS6tU/vW1xY7zA0bC5dE9fG"
    out = redact(f"token={secret}")
    assert ("SECRET", None) in _tokens(out), f"slash-bearing secret leaked: {out!r}"
    assert secret not in out


# ---- residual MEDIUM: slash-DENSE secret whose chunks are individually too short --
# The old path exclusion was purely NEGATIVE ("no single '/'-segment qualifies as a
# secret"), so a slash-DENSE credential chunked into short (<20-char) pieces
# (``a1B2/c3D4/e5F6/…``) had no qualifying segment and passed through RAW as if it were
# a path — a credential fail-open (NFR-7 (a)). The passthrough is now anchored to a
# POSITIVE path/URI signal; a slash-dense run with NO path signal is tested on its
# separator-stripped core and masked. MUST FAIL if the passthrough reverts to the
# negative-only per-segment test (the chunked secret then egresses raw). ------------ #
@pytest.mark.parametrize(
    "secret",
    [
        "a1B2/c3D4/e5F6/g7H8/i9J0/k1L2/m3N4",   # mixed-charset, 4-char chunks
        "Zk3/Qp9/Lm2/Xr7/Bv4/Nt8/Wc1/Hj6/Yd0",  # mixed-charset, 3-char chunks
        "aB3d-Ef9k-L2mN-8pQ4-rS6t-Uv1x-Y7zA",   # hyphen-dense (same class)
    ],
)
def test_slash_dense_secret_with_short_chunks_is_masked(secret):
    out = redact(f"cred {secret}")
    assert ("SECRET", None) in _tokens(out), (
        f"slash/hyphen-dense secret egressed RAW (residual MEDIUM): {out!r}"
    )
    assert secret not in out, f"raw chunked secret leaked in {out!r}"


@pytest.mark.parametrize(
    "path",
    [
        "/App/v2/config/Prod1/settings.json",   # mixed-charset versioned config path
        "C:/Users/Alice/Documents/Q3-2026.xlsx",  # Windows drive path w/ extension
        "reports/q3/financials/summary",         # low-entropy relative path (no signal)
    ],
)
def test_slash_dense_fix_still_passes_real_paths(path):
    # Guard the R2-M2 side of the MEDIUM fix: a REAL path/URI (even a mixed-charset,
    # versioned one) must still pass through so the PDP keeps its param signal. The fix
    # anchors passthrough to a positive path signal / low-entropy core — it must not
    # start over-masking legitimate paths. MUST FAIL if the core-entropy test is too
    # loose and swallows a real path.
    out = redact(path)
    assert "SECRET" not in out, f"real path over-masked to SECRET: {out!r}"
    assert path in out, f"real path altered: {out!r}"
