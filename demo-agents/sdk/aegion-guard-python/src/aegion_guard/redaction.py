"""Tier-1 edge deterministic redactor (WS-E1, FR-3.13; LLD 23 §2 / WS-E §M-1).

The SDK egresses ``tool_params`` and ``user_input`` to the hosted PDP. On the
**Serverless** edition that payload leaves the customer boundary, so structured
PII / PCI must be masked **at the edge, before egress** — raw structured PII never
leaves the customer (NFR-7 clause (a): no raw retention on any edition; clause (c):
structured PII is redacted inline, only free-text PHI may transit under a BAA).

This module is the deterministic first tier. It is **stdlib-only by design**
(``re``, ``math``, ``unicodedata``, ``secrets``, ``ipaddress`` — LLD 23 §2): the SDK
vendors unchanged into a Lambda zip / Azure Function, so a runtime dependency is
forbidden (``pyproject.toml`` ``dependencies == []``). ``ipaddress`` is stdlib since
3.3, so it satisfies the no-runtime-dependency invariant. The heavy free-text
semantic NER is a separate server-side tier (WS-E2), NOT here.

Design invariants (WS-E model M-1..M-5, enforced by tests):

* **Structure-preserving typed tokens.** A value is replaced by a *typed* wire
  token so the deep detectors still get structural signal (residual #5 measures
  the recall cost). We do NOT collapse every hit to one opaque token.
* **Wire-token grammar is a security control (M-4).** The wire token is
  ``⟦AEGR:{nonce}:TYPE[:meta]⟧`` with a per-call ``secrets.token_hex(8)`` nonce.
  A bare ``<CARD>`` is descriptive/UI only and is *never* the wire form — a
  spoofable bare marker re-opens M-4 (an attacker plants ``<CARD>`` to forge a
  "redaction happened" signal). :func:`_neutralize_planted_tokens` runs FIRST so
  attacker-supplied sentinels can never masquerade as a real marker.
* **Matcher ORDER is a security control (M-4/E1.1 footgun).** The frozen
  :data:`_ORDERED_MATCHERS` runs highest-harm / most-specific first: SAD -> PAN
  (Luhn) -> whole-value EMAIL/URL -> format-anchored labelled IDs -> the
  remaining generic structured (SSN/IP/phone/date) -> high-entropy SECRET last
  (broadest, lowest precedence). PAN must precede any bare-numeric matcher or a
  card would mis-token and lose the first6/last4 obligation. EMAIL/URL must
  precede LABELLED_ID or a label word adjacent to an email ("license a@b.com")
  lets the labelled-id value capture steal the local-part and leak the domain
  in cleartext (partial-redaction leak).
* **PCI (M-3).** PAN -> first6/last4 ONLY (middle digits gone; never emit a full
  PAN even tokenized). SAD (CVV/track/PIN) -> ``SAD`` with **no meta**
  (never-store / never-log — the value is dropped entirely).
* **Fail-secure (E1.4).** This module raises :class:`RedactionError` on an
  internal failure rather than returning a partially-redacted or raw value. The
  caller (``guard._build_request``) turns that into a DENY and never egresses raw.
"""
from __future__ import annotations

import ipaddress
import math
import re
import secrets
import unicodedata
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple

from .exceptions import RedactionError

# --------------------------------------------------------------------------- #
# Wire-token grammar (M-4). The sentinel is a reserved, hard-to-type bracket
# pair that ordinary text does not contain; combined with a per-call nonce it is
# not forgeable from attacker input (see _neutralize_planted_tokens).
# --------------------------------------------------------------------------- #
_WIRE_OPEN = "⟦"   # ⟦  MATHEMATICAL LEFT WHITE SQUARE BRACKET
_WIRE_CLOSE = "⟧"  # ⟧  MATHEMATICAL RIGHT WHITE SQUARE BRACKET
_WIRE_NS = "AEGR"       # reserved namespace

_NONCE_BYTES = 8        # secrets.token_hex(8) -> 16 hex chars, per call


def _make_nonce() -> str:
    """A fresh per-call nonce. ``secrets`` (CSPRNG), never ``random`` (M-4)."""
    return secrets.token_hex(_NONCE_BYTES)


def new_nonce() -> str:
    """Public: mint ONE per-egress marker nonce (§3.3).

    The guard mints this once per ``_build_request`` and threads it through every
    redacted field so all genuine markers in the payload share the single
    ``redaction_nonce`` the PDP checks against. CSPRNG (``secrets``), never
    guessable — an attacker cannot forge a marker bearing the call's nonce (M-4).
    """
    return _make_nonce()


def _wire_token(nonce: str, type_: str, meta: str = "") -> str:
    """Build the reserved wire token ``⟦AEGR:{nonce}:TYPE[:meta]⟧`` (M-4/M-5).

    ``meta`` is included ONLY when non-empty (e.g. ``CARD`` carries ``6:4``; SAD
    carries nothing — PCI never-store).
    """
    body = f"{_WIRE_NS}:{nonce}:{type_}"
    if meta:
        body = f"{body}:{meta}"
    return f"{_WIRE_OPEN}{body}{_WIRE_CLOSE}"


# Patterns used to neutralize planted markers (M-4). First strip any FULL reserved
# token an attacker planted (brackets + the AEGR body, incl. its forged nonce/meta),
# then strip any stray reserved brackets that remain. Stripping the whole token —
# not just the brackets — ensures a forged ``AEGR:<nonce>:CARD:...`` body cannot
# survive as plaintext masquerading as a redaction marker, and that PII-shaped
# digits an attacker hides inside a planted token are removed with it.
_PLANTED_TOKEN = re.compile(
    f"{_WIRE_OPEN}\\s*{_WIRE_NS}\\s*:[^{_WIRE_OPEN}{_WIRE_CLOSE}]*{_WIRE_CLOSE}"
)
_SENTINEL_RUN = re.compile(f"[{_WIRE_OPEN}{_WIRE_CLOSE}]+")


def _neutralize_planted_tokens(value: str) -> str:
    """Strip attacker-planted reserved markers from *raw* input (M-4).

    Runs FIRST, before any matcher. An attacker who plants ``⟦AEGR:...:CARD⟧`` (or
    bare ``⟦`` / ``⟧``) in a ``tool_param`` / ``user_input`` must not be able to
    forge a redaction marker. We (1) delete any full reserved ``⟦AEGR:…⟧`` token —
    including its forged body — then (2) delete any stray reserved brackets, so the
    only occurrences left after redaction are the ones WE minted with this call's
    unforgeable nonce. Descriptive ``<CARD>``-style angle brackets are left alone:
    they are never the wire form, so they cannot spoof a real marker.
    """
    value = _PLANTED_TOKEN.sub("", value)
    return _SENTINEL_RUN.sub("", value)


def _apply_outside_tokens(
    matcher: Callable[[str, str], str], text: str, nonce: str
) -> str:
    """Run ``matcher`` only on the text OUTSIDE already-emitted wire tokens (M-4).

    Matchers run sequentially over the accumulating text, so a matcher late in the
    frozen chain would otherwise scan the ``⟦AEGR:{nonce}:TYPE[:meta]⟧`` tokens an
    EARLIER matcher emitted. That is a real defect: the per-call nonce is 16 hex
    chars, and roughly one nonce in a few hundred contains a Luhn-valid 13-19 digit
    run — so ``_redact_pan`` (which runs after ``_redact_sad``) would find that run
    INSIDE an emitted SAD token's nonce, mask it, and nest a CARD token inside the
    SAD token — corrupting the wire token so the PDP can no longer verify the
    marker's nonce (and stranding a mangled nonce on the wire). The CARD meta could
    likewise be re-chewed by SECRET/DATE. The token is a reserved, already-safe
    region: no subsequent matcher may re-enter it. We therefore splice ``text`` on
    the reserved-token spans and run ``matcher`` only on the plaintext gaps, leaving
    every emitted token byte-for-byte intact. This is order-independent — it closes
    the whole class (any later matcher biting into any earlier token), not just the
    SAD/PAN pair observed. The plaintext gaps still contain no genuine leftover
    ``⟦``/``⟧`` (``_neutralize_planted_tokens`` removed attacker-planted ones first),
    so nothing outside a real token is ever wrongly protected.
    """
    parts: List[str] = []
    last = 0
    for m in _PLANTED_TOKEN.finditer(text):
        # plaintext gap before this token: matcher may run here
        gap = text[last : m.start()]
        if gap:
            parts.append(matcher(gap, nonce))
        # the emitted token itself: preserved untouched
        parts.append(m.group(0))
        last = m.end()
    tail = text[last:]
    if tail:
        parts.append(matcher(tail, nonce))
    return "".join(parts)


# --------------------------------------------------------------------------- #
# Detector primitives (stdlib only).
# --------------------------------------------------------------------------- #
def _luhn_ok(digits: str) -> bool:
    """Luhn (mod-10) checksum — the PAN gate that keeps random 13-19 digit runs
    (order numbers, timestamps) from being masked as cards (E1.1)."""
    total = 0
    parity = len(digits) % 2
    for i, ch in enumerate(digits):
        d = ord(ch) - 48  # ord('0')
        if i % 2 == parity:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _shannon_entropy(s: str) -> float:
    """Shannon entropy in bits/char — the high-entropy-secret heuristic (E1.1)."""
    if not s:
        return 0.0
    counts: dict = {}
    for ch in s:
        counts[ch] = counts.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


# --------------------------------------------------------------------------- #
# IIN (Issuer Identification Number) prefix validation (29a §2.1 table).
#
# A Luhn-valid 13-19-digit run is necessary but NOT sufficient to be a real PAN:
# roughly 1-in-10 random digit runs are Luhn-valid, so Luhn alone over-masks long
# order ids / concatenated timestamps that happen to pass mod-10. The IIN prefix
# (the leading digits of the PAN) is the second, structural gate: a real card
# starts with an issuer-assigned prefix from a small, well-known set. Requiring a
# valid IIN prefix on TOP of Luhn (both must hold) sharply narrows the false-positive
# surface without dropping any real card, because every issuing network's range is
# covered below. This is the ``format+validity`` half of NORMALIZE-THEN-DETECT for
# PAN: strip separators, then gate on (Luhn AND IIN-prefix AND card length).
#
# Ranges are the standard major-industry-identifier / IIN assignments:
#   Visa            4                     (13/16/19)
#   Mastercard      51-55, 2221-2720      (16)
#   Amex            34, 37                (15)
#   Discover        6011, 644-649, 65, 622126-622925 (16/19)
#   Diners Club     300-305, 3095, 36, 38-39, 54-55  (14/16)
#   JCB             3528-3589             (16-19)
#   UnionPay        62, 81                (16-19)
#   Maestro         50, 56-69             (12-19; the broad ranges above already cover)
# Kept as prefix-length buckets so the check is pure arithmetic (stdlib-only,
# 29a §5.3) — no table lookup library. A run whose length is a card length and whose
# leading digits fall in ANY bucket is IIN-valid.
# --------------------------------------------------------------------------- #
_PAN_MIN_LEN = 12       # shortest real card (Maestro) — 29a §2.1
_PAN_MAX_LEN = 19       # longest real card (Visa/UnionPay/JCB 19)


def _iin_ok(digits: str) -> bool:
    """Does ``digits`` begin with a valid issuer IIN prefix (29a §2.1)?

    Pure arithmetic over the leading digits (stdlib-only). Necessary-together with
    :func:`_luhn_ok`: a run must pass BOTH to be treated as a card, which stops a
    Luhn-coincidental order id / timestamp from being masked as a PAN (E1.1) while
    never dropping a real card (every issuing network's range is covered).
    """
    if len(digits) < _PAN_MIN_LEN:
        return False
    d1 = int(digits[0])
    d2 = int(digits[:2])
    d3 = int(digits[:3])
    d4 = int(digits[:4])
    d6 = int(digits[:6])
    # Visa
    if d1 == 4:
        return True
    # Mastercard (51-55) + 2-series BIN (2221-2720)
    if 51 <= d2 <= 55 or 2221 <= d4 <= 2720:
        return True
    # Amex
    if d2 in (34, 37):
        return True
    # Diners Club (300-305, 3095, 36, 38, 39)
    if 300 <= d3 <= 305 or d4 == 3095 or d2 in (36, 38, 39):
        return True
    # JCB (3528-3589)
    if 3528 <= d4 <= 3589:
        return True
    # Discover (6011, 644-649, 65, 622126-622925)
    if d4 == 6011 or 644 <= d3 <= 649 or d2 == 65 or 622126 <= d6 <= 622925:
        return True
    # UnionPay (62, 81)
    if d2 in (62, 81):
        return True
    # Maestro (50, 56-69) — broad debit ranges (56-69 already partly covered above)
    if d2 == 50 or 56 <= d2 <= 69:
        return True
    return False


def _is_pan(digits: str) -> bool:
    """A pure-ASCII digit run is a PAN iff it is a card length AND passes BOTH the
    Luhn mod-10 checksum AND a valid issuer IIN prefix (29a §2.1 / §5.3).

    This is the single validity predicate used by every PAN path (the normalize-
    then-detect window scan, and the SAD footgun guard) so the accept criteria never
    diverge across call sites. Both gates are pure arithmetic — stdlib-only.
    """
    return (
        _PAN_MIN_LEN <= len(digits) <= _PAN_MAX_LEN
        and _luhn_ok(digits)
        and _iin_ok(digits)
    )


# --------------------------------------------------------------------------- #
# Matchers. Each is (name, callable) where the callable takes (text, nonce) and
# returns the text with its class of values replaced by wire tokens. Order is a
# security control: _ORDERED_MATCHERS is frozen highest-harm/most-specific first.
# --------------------------------------------------------------------------- #

# --- PAN (card) : NORMALIZE-THEN-DETECT -> ⟦…:CARD:first6:last4⟧ (M-3) -------- #
# ARCHITECTURAL MODEL (29a §2.1 / ROUND-4). The earlier design enumerated an
# ever-growing separator CLASS in the candidate regex (space, TAB, CR/LF, hyphen,
# dot, slash, comma, underscore, up to two at a time). That in-place-separator-regex
# approach is fundamentally leak-prone: every separator shape a real paste can carry
# (3+ spaces, a TAB, a slash, a mix) is a SEPARATE regex arm, and any form the class
# forgot egressed the card RAW (the R2/R3/R4 separator-leak class: R2 separated-PAN,
# R3 multi-group, R4 3-space/tab/slash PAN + tab/slash SSN). Enumerating separators
# can only ever chase the leak; it cannot close the class.
#
# NORMALIZE-THEN-DETECT closes the ENTIRE class by construction, not by enumeration:
#   1. capture a bounded WINDOW that may contain digits and ANY run of non-alphanumeric
#      separator characters (:data:`_PAN_CANDIDATE`);
#   2. STRIP every non-alphanumeric separator from the window and keep a map from each
#      surviving ASCII digit back to its ORIGINAL index (:func:`_normalize_digits`);
#   3. slide a card-length Luhn+IIN-valid window over the pure digit string
#      (:func:`_best_pan_window`) — validity is checked on NORMALIZED digits, so a card
#      split by ANY separator (even a separator no regex enumerated) is detected;
#   4. MAP the winning digit span back over the ORIGINAL text and tokenize exactly that
#      substring (:func:`_redact_all_pan_windows`), leaving genuinely non-card text as-is.
# Because step 2 removes ALL separators before validation, no separator variant can
# hide a card: the detector never sees the separators at all. Adding a new exotic
# separator to a paste can no longer re-open a leak — it is stripped, not enumerated.
#
# The candidate window is DELIBERATELY loose so it never breaks a card at a separator:
# a maximal run of ASCII digits and separator chars (with a digit at each end). Non-card
# leading/trailing digit-GROUPS an over-capture swallows ("pay 5 <card>", "amount 100
# <card>", "ref 12 34 <card> 56") are re-bounded to the real card by the digit-index
# window scan (which trims WHOLE non-card groups). The digit-anchored boundary
# ``(?<![0-9A-Za-z])`` / ``(?![0-9A-Za-z])`` keeps the window from biting into an
# adjacent word/underscore-joined identifier while still admitting ``_``-separated cards
# (``_`` is stripped as a separator inside, not a boundary). A run whose separator span
# between two digits exceeds :data:`_PAN_SEP_MAX_GAP` chars is NOT a single formatted
# card (two distant numbers) and is broken there, so the loose window cannot merge two
# unrelated numbers into a bogus Luhn+IIN card.
_PAN_SEP_MAX_GAP = 3      # max consecutive non-alnum separator chars between two card
                          # digit groups (covers ", " / " / " / "\r\n" / up to 3 spaces)
# A window is a digit, then any number of (up-to-gap separator run + digit) repeats.
# ``[^0-9A-Za-z]`` is EVERY non-alphanumeric char — no separator is enumerated, so no
# separator shape can be forgotten (the whole point of normalize-then-detect). The
# ``{1,GAP}`` gap bound stops the window from spanning a large prose gap between two
# unrelated numbers; a wider gap simply ends the window (the loose boundary never
# mis-merges two distant numbers into a card). The boundary is alnum (not ``\d``) so a
# card is never glued to an adjacent word, yet an ``_``-separated card still matches
# (``_`` is non-alnum → a valid interior separator, and NOT a boundary char).
_PAN_CANDIDATE = re.compile(
    rf"(?<![0-9A-Za-z])[0-9](?:[^0-9A-Za-z]{{1,{_PAN_SEP_MAX_GAP}}}?[0-9]|[0-9])*"
    r"(?![0-9A-Za-z])"
)
# A real PAN is at most 19 digits. The normalize-then-detect scan is O(digits * 19) —
# for each start position we extend at most until the window exceeds 19 digits — so it
# is LINEAR in the digit count. This cap bounds a pathological many-digit window so the
# scan cannot become a redaction-path DoS. Set very generously (a card is <=19 digits,
# so 512 digits is ~26 cards) so NO realistic payload — including a multi-card run — is
# ever dropped and left to egress raw. A window with more digits than the cap cannot be
# scanned as a card and is left for later matchers; this is a documented cost bound, not
# a correctness bound (a real card is never silently skipped below the cap). Kept as a
# DIGIT count (was a group count) — normalize-then-detect works on stripped digits, not
# separated groups, so the bound is on the total digit length of the window.
_PAN_MAX_GROUPS = 512

# ASCII digit RUNS only. A PAN written in non-ASCII \d-matching digits (Arabic-Indic,
# Devanagari, or a fullwidth digit that slipped NFKC) must NOT be treated as a card:
# the stdlib Luhn works on ``ord()-48`` so non-ASCII code points feed it garbage, and
# a mod-10 coincidence would emit the raw non-ASCII partial-PAN into the CARD meta —
# itself cleartext PII on the wire. NFKC (see redact_detailed) folds the common
# compatibility digits to ASCII first; anything still non-ASCII here is out of scope
# for the card matcher and is left untouched for the later matchers (never mistaken
# for a card, never partially emitted). See Appendix G (ii) / LLD 29 §14.4.
_ASCII_DIGIT_RUN = re.compile(r"[0-9]+")

# Standard PAN lengths, most-common first. When an over-captured window has more than
# one valid card sub-window, we prefer the one whose length is a real card length
# (Visa/MC/Discover 16, Amex 15, then the rarer 14/13, then the over-length 19/18/17,
# then Maestro 12). This anchors selection to the ACTUAL card rather than to whichever
# window an injected adjacent digit happened to also make Luhn+IIN-valid: without it a
# longer valid run (injected "004" + card, or card + injected "99") could win, emit a
# bogus first6/last4, and strand a real card digit in cleartext ("Wrong PAN window").
_PAN_STD_LENGTHS: Tuple[int, ...] = (16, 15, 14, 13, 19, 18, 17, 12)


def _normalize_digits(raw: str) -> "Tuple[str, List[int], List[int]]":
    """Strip ALL non-alphanumeric separators; return (ASCII-digit string, index map,
    group-boundary offsets).

    The heart of NORMALIZE-THEN-DETECT: a card window may be split by ANY separator
    (space/TAB/CR/LF/hyphen/dot/slash/comma/underscore/…) — we do not enumerate them,
    we simply keep only the ASCII digits and record, for the i-th kept digit, its
    ORIGINAL index in ``raw`` (``idx_map[i]``). Detection then runs on the pure digit
    string; a winning digit span ``[a:b)`` maps back to the original substring
    ``raw[idx_map[a] : idx_map[b-1] + 1]`` so ONLY the card characters (digits AND the
    interleaved separators between them) are tokenized, and surrounding text is intact.
    Non-ASCII ``\\d`` digits are EXCLUDED (never counted toward a card — see
    _ASCII_DIGIT_RUN / the non-ASCII partial-PAN leak).

    ``boundaries`` is the set of digit-string offsets that begin a NEW contiguous
    ASCII-digit group in ``raw`` (offset 0 plus each offset preceded by a separator).
    The card-window scan starts/ends ONLY at these boundaries so a stray digit can
    attach to a card only *through a separator* — a purely contiguous run is one group
    and must validate as a WHOLE (never an interior sub-window), preserving the E1.1
    false-positive gate (a 16-digit non-card order id is not sliced into a valid card).
    """
    digits: List[str] = []
    idx_map: List[int] = []
    boundaries: List[int] = []
    prev_orig = -2
    for i, ch in enumerate(raw):
        if "0" <= ch <= "9":  # ASCII digit only
            if i != prev_orig + 1:
                # a separator (or the run start) sits before this digit -> group start
                boundaries.append(len(digits))
            digits.append(ch)
            idx_map.append(i)
            prev_orig = i
    return "".join(digits), idx_map, boundaries


def _best_pan_window(raw: str) -> "Tuple[int, int, str] | None":
    """Re-bound an over-captured PAN candidate to the actual card (NORMALIZE-THEN-DETECT).

    ``raw`` is one ``_PAN_CANDIDATE`` window — digits interleaved with ANY separators,
    which may have swallowed non-card leading AND/OR trailing digit GROUPS ("pay 5 <card>",
    "ref 12 34 <card> 56"). We (1) strip ALL separators to the pure ASCII digit string
    (:func:`_normalize_digits`), keeping the contiguous-group boundaries; (2) slide a
    card-length window over the digit string, considering ONLY windows that START and END
    on a group boundary, and accept any that is a valid PAN — a card length AND Luhn mod-10
    AND a valid issuer IIN prefix (:func:`_is_pan`); (3) MAP the winning digit span back to
    the ORIGINAL coordinates in ``raw`` so the exact card substring (digits + interleaved
    separators) can be tokenized. Because validity is tested on the SEPARATOR-FREE digit
    string, a card split by any separator shape is detected by construction — closing the
    entire R2/R3/R4 separator-leak class without enumerating separators.

    Group-aligned windowing is what keeps a legitimate long *contiguous* number (order id
    / concatenated timestamp) from being sliced into a valid card: with no separator it is
    one group, so the WHOLE run must itself be a valid PAN to card (an interior 15-digit
    sub-window of a 16-digit contiguous non-card run is NOT considered — it does not start
    on a group boundary). A stray digit can only attach to a card through a separator.

    Among valid windows we select, in order: (1) a real card length
    (:data:`_PAN_STD_LENGTHS`) — an injected adjacent digit that merely extends a card
    into a longer valid run cannot win and emit a bogus first6/last4; (2) the fewest
    stray digits outside the window (closest to a clean card); (3) the leftmost start.
    Returns ``(orig_start, orig_end, digits)`` where ``raw[orig_start:orig_end]`` is the
    exact card substring to tokenize, or ``None`` if no window is a valid PAN (a genuine
    non-card run degrades to "leave as-is" — never emitted raw *as a card* nor mis-masked).
    A window with more than :data:`_PAN_MAX_GROUPS` ASCII digit-GROUPS cannot be a
    formatted card and is rejected outright so the scan stays bounded (DoS guard).
    """
    digits, idx_map, boundaries = _normalize_digits(raw)
    nd = len(digits)
    ng = len(boundaries)
    # DoS guard + floor: too many groups to be a formatted card (bounded scan), or fewer
    # digits than the shortest card. Reject outright (leave as-is / for later matchers).
    if nd < _PAN_MIN_LEN or ng > _PAN_MAX_GROUPS:
        return None
    # Group-boundary END offsets: the start of each group AFTER a boundary, plus the end
    # of the whole digit string (a card can end at the run's tail). Sorted, deduped.
    ends = sorted(set(boundaries[1:] + [nd]))
    best_key: "Tuple[int, int, int] | None" = None
    best_span: "Tuple[int, int, str] | None" = None
    for start in boundaries:
        for end in ends:
            length = end - start
            if length < _PAN_MIN_LEN:
                continue
            if length > _PAN_MAX_LEN:
                break  # ``ends`` is sorted — any further end only grows the window
            sub = digits[start:end]
            if not _is_pan(sub):  # length + Luhn + IIN prefix, all pure arithmetic
                continue
            try:
                len_priority = _PAN_STD_LENGTHS.index(length)
            except ValueError:  # pragma: no cover — 12..19 are all listed
                len_priority = len(_PAN_STD_LENGTHS)
            strays = start + (nd - end)  # non-card digits before + after the window
            key = (len_priority, strays, start)
            if best_key is None or key < best_key:
                best_key = key
                # Map the digit span back to the ORIGINAL coordinates: from the first
                # card digit's original index through the last card digit's index+1.
                best_span = (idx_map[start], idx_map[end - 1] + 1, sub)
    return best_span


def _redact_all_pan_windows(raw: str, nonce: str) -> str:
    """Tokenize EVERY valid card window inside one candidate run (M-3).

    A single ``_PAN_CANDIDATE`` window can span MORE THAN ONE card — two space-adjacent
    PANs ("4111 1111 1111 1111 5555 5555 5555 4444") capture as one run. Masking only
    the single best window would tokenize the first card and egress the second RAW (a
    PCI fail-open). So we mask the best window, then RECURSE on the ORIGINAL cleartext
    prefix and suffix around it, tokenizing every further card until none remains. Only
    the card substrings are replaced; genuinely non-card leading/trailing text (and the
    separators between cards) are preserved as cleartext.
    """
    window = _best_pan_window(raw)
    if window is None:
        return raw  # not a card — leave for later matchers / as-is
    start, end, digits = window
    # PCI: first6/last4 ONLY. Middle digits are GONE; never emit the full PAN.
    meta = f"{digits[:6]}:{digits[-4:]}"
    token = _wire_token(nonce, "CARD", meta)
    # Recurse on the prefix/suffix so a SECOND (or third) card adjacent to this one is
    # also masked — never leave a full PAN raw in the tail of a multi-card run.
    prefix = _redact_all_pan_windows(raw[:start], nonce) if raw[:start] else ""
    suffix = _redact_all_pan_windows(raw[end:], nonce) if raw[end:] else ""
    return f"{prefix}{token}{suffix}"


def _redact_pan(text: str, nonce: str) -> str:
    return _PAN_CANDIDATE.sub(
        lambda m: _redact_all_pan_windows(m.group(0), nonce), text
    )


# --- SAD (CVV/track/PIN) : format-anchored -> ⟦…:SAD⟧ (PCI never-store) ------- #
# Label-anchored only, to avoid masking every 3-4 digit number. The value is
# DROPPED entirely — no first/last meta (never-store / never-log).
# Label, then an optional short connector ("is"/"=" /":" /"#" /"of"/"was") and up
# to a couple of filler words, then the digits. Anchored to a label so we never
# mask arbitrary 3-6 digit numbers.
_SAD_ANCHORED = re.compile(
    r"(?i)\b(cvv2?|cvc2?|cid|cav2?|pin|track\s*[12]?|security\s*code)\b"
    r"(?:\s*[:=#]\s*|\s+(?:is|was|of|=)\s+|\s+)"
    r"(\d{3,6})\b"
)

# A candidate window starting at the SAD value group, used by the SAD footgun guard.
# NORMALIZE-THEN-DETECT (ROUND-4): the same loose :data:`_PAN_CANDIDATE` window shape
# (digits + ANY separators, gap-bounded) matched anchored at the SAD-captured leading
# group — so the guard sees the WHOLE trailing card regardless of its separator shape
# (space / dot / slash / TAB / CRLF / 3-space — every R2/R3/R4 form), by construction,
# not by an enumerated separator class that could fall behind the PAN matcher (the
# R2-C2 partial-PAN re-open). Because the guard normalizes-then-detects with the exact
# same :func:`_best_pan_window`, its separator handling can never diverge from the PAN
# matcher's.
_SAD_VALUE_PAN_RUN = re.compile(
    rf"[0-9](?:[^0-9A-Za-z]{{1,{_PAN_SEP_MAX_GAP}}}?[0-9]|[0-9])*"
)


def _redact_sad(text: str, nonce: str) -> str:
    def repl(m: "re.Match[str]") -> str:
        # SAD footgun (M-3 / NFR-7 (a) — PCI fail-open): the value capture ``(\d{3,6})``
        # matches only the LEADING digit-group of a separated card that trails a SAD
        # label (e.g. "pin is 4111 1111 1111 1111" captures just "4111"). SAD runs BEFORE
        # PAN, so if we tokenized "4111" to SAD here the remaining "1111 1111 1111" is 12
        # digits — below the PAN floor as a standalone group — so 12 real card digits
        # could egress in cleartext (a partially-redacted PAN, which E1.4 forbids). We
        # look at the candidate window STARTING at this value group and ask
        # :func:`_best_pan_window` (normalize-then-detect) whether it contains a valid
        # card, and — critically — WHERE that card starts within the window:
        #
        #   * card starts at the SAD value's FIRST digit (the SAD value IS the card's
        #     leading group, e.g. "pin is 4111 1111 1111 1111" / "pin is 4111.1111…"):
        #     DECLINE the SAD match so ``_redact_pan`` tokenizes the WHOLE card. There is
        #     no separate SAD value here — the digits are the card. (R2-C2 / R4.)
        #   * card starts AFTER the SAD value (a stray group precedes the card, so the
        #     SAD value is a SEPARATE value in front of the card, e.g.
        #     "cvv 999 4111 1111 1111 1111" — 999 is the CVV, 4111… the card): redact
        #     BOTH. Drop the SAD value to a no-meta ``<SAD>`` HERE and leave the trailing
        #     card (which sits AFTER this match's end) for ``_redact_pan``. Declining
        #     would leak the CVV RAW while only the card masked (R3-H1, SAD never-store).
        #
        # A genuine short SAD ("pin is 4821") has no valid trailing card (window is None),
        # so it tokenizes to SAD exactly as before. Comparison is by ORIGINAL index: the
        # card window's original start equals this SAD value's original start iff the SAD
        # value is the card's own leading group.
        value_start = m.start(2)
        run_match = _SAD_VALUE_PAN_RUN.match(text, value_start)
        if run_match is not None:
            window = _best_pan_window(run_match.group(0))
            if window is not None and run_match.start() + window[0] == value_start:
                # The SAD value is the card's own leading group — decline; PAN masks the
                # whole card. Do NOT partially redact a card.
                return m.group(0)
        # Either no trailing card, or the card starts AFTER this SAD value (a separate
        # CVV/PIN before a card). Keep the label, drop THIS value into a no-meta SAD
        # token; any trailing separated card is redacted by _redact_pan next.
        return f"{m.group(1)}: {_wire_token(nonce, 'SAD')}"

    return _SAD_ANCHORED.sub(repl, text)


# --- SSN (US) : NORMALIZE-THEN-DETECT + validity rules -> ⟦…:SSN⟧ (HIPAA SH) -- #
# ARCHITECTURAL MODEL (29a §2.1 / ROUND-4). The earlier ``(\d{3})([ .\-])(\d{2})\2
# (\d{4})`` matched a 3-2-4 grouping with a CONSISTENT enumerated separator (dash /
# space / dot only). That in-place-separator-regex left the TAB and slash forms
# ("123\t45\t6789", "123/45/6789") leaking RAW (R4 separator class). Like the PAN
# matcher, we NORMALIZE-THEN-DETECT: capture a bounded window of digits + ANY
# separators, strip separators, and validate the pure 9-digit string against the SSN
# format + issuance validity rules — so no separator shape can hide an SSN.
#
# US SSN has NO checksum (unlike a PAN's Luhn) — it is a pure format + issuance-range
# check (29a §5.3, pure arithmetic). A 9-digit ``AAA-GG-SSSS`` is a valid SSN number
# iff: area (AAA) is 001-899 EXCEPT 666; group (GG) is 01-99; serial (SSSS) is
# 0001-9999. (900-999 areas are ITINs / never issued; 000 area, 00 group, 0000 serial
# are never issued.) Because a bare 9-digit run passing only these loose rules would
# over-mask ordinary 9-digit numbers (order ids, zip+4 runs), the SSN matcher stays
# LABEL-ANCHORED: it fires only when an ``ssn`` / ``social security`` label precedes
# the value (the format+validity check then bounds false positives among labelled
# numbers). This mirrors the SAD design (label-anchored) and the LLD 29 §3.4 false-
# positive discipline. ``/`` , ``,`` , ``_`` etc. are all handled as separators now
# (stripped), because normalize-then-detect does not enumerate a separator class.
_SSN_ANCHORED = re.compile(
    r"(?i)\b(ssn|social\s+security(?:\s+(?:no|number|#))?)\b"
    r"(?:\s*[:=#]\s*|\s+(?:is|was|of|=)\s+|\s+)"
    r"([0-9](?:[^0-9A-Za-z]{1,3}?[0-9]|[0-9])*)"
)


def _is_ssn(digits: str) -> bool:
    """Is ``digits`` a validly-issuable US SSN number (29a §5.3)? Pure arithmetic.

    9 digits ``AAA-GG-SSSS`` where area 001-899 (not 666), group 01-99, serial
    0001-9999. No checksum exists for an SSN — this is the full validity gate.
    """
    if len(digits) != 9:
        return False
    area = int(digits[:3])
    group = int(digits[3:5])
    serial = int(digits[5:])
    if area == 0 or area == 666 or area >= 900:
        return False
    if group == 0:
        return False
    if serial == 0:
        return False
    return True


def _redact_ssn(text: str, nonce: str) -> str:
    def repl(m: "re.Match[str]") -> str:
        # Normalize the label-anchored value window, then validate. If the FIRST 9
        # normalized digits are a valid SSN, tokenize the exact original span of those
        # 9 digits (keeping the label and any trailing text intact). A window that is
        # not a valid SSN is left as-is (bounds false positives among labelled numbers).
        label = m.group(1)
        value = m.group(2)
        value_start = m.start(2)
        digits, idx_map, _boundaries = _normalize_digits(value)
        if len(digits) >= 9 and _is_ssn(digits[:9]):
            # Original span of the first 9 SSN digits within the whole text.
            span_start = value_start + idx_map[0]
            span_end = value_start + idx_map[8] + 1
            tail = text[span_end : m.end()]
            return f"{label}: {_wire_token(nonce, 'SSN')}{tail}"
        return m.group(0)

    return _SSN_ANCHORED.sub(repl, text)


# --- email -> ⟦…:EMAIL⟧ (HIPAA SH) ------------------------------------------- #
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def _redact_email(text: str, nonce: str) -> str:
    return _EMAIL.sub(lambda m: _wire_token(nonce, "EMAIL"), text)


# --- URL -> ⟦…:URL⟧ (HIPAA SH) — before phone so an in-URL number isn't a phone #
_URL = re.compile(r"\bhttps?://[^\s<>⟦⟧\"']+")


def _redact_url(text: str, nonce: str) -> str:
    def repl(m: "re.Match[str]") -> str:
        # E7.2 — Tier-1 URL query-secret strip. The whole URL — scheme, host, path,
        # query, AND any bearer-secret query value (``?token=…`` / ``?api_key=…`` /
        # ``?access_token=…`` / ``?sig=…``) — collapses into ONE opaque ⟦…:URL⟧ token, so
        # the secret query value is removed WITH the URL, in cleartext-nothing-survives
        # fashion. There is no partial-URL emitted, so there is no residual query secret
        # to strip separately — a dedicated ``_strip_url_query_secrets`` helper (removed:
        # it was dead code never on this path, a false second layer flagged in review)
        # would only be needed if a future change emitted part of a URL in cleartext.
        # This is a SUPPLEMENT to the (later, server-side) FR-2.9 destination allow-list,
        # not a replacement and not a parallel URL subsystem (E7.2). The behavioural
        # guarantee (a query secret never egresses in cleartext) is pinned by
        # ``test_url_query_secret_stripped`` against the real ``redact()`` output.
        return _wire_token(nonce, "URL")

    return _URL.sub(repl, text)


# --- IP (v4 AND v6) -> ⟦…:IP⟧ (HIPAA SH) ------------------------------------- #
# HIPAA Safe-Harbor identifier #18 ("IP address") is generic — it is NOT limited to
# IPv4. LLD 29 §3.1 (the token table, line 152) names one generic ``IP`` token and
# Appendix F lists it under the HIPAA-SH scope. An IPv6-only edition would leave a
# real IPv6 address (``2001:db8::1``, ``fe80::…``, ``::1``) in cleartext to the hosted
# PDP — a fail-open PHI leak (NFR-7 (a): no raw structured identifier egresses on any
# edition). So the ``IP`` matcher masks BOTH families to the same ⟦…:IP⟧ token.
_IPV4 = re.compile(
    r"(?<!\d)(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?!\d)"
)

# IPv6 is a LOOSE colon-bearing hex-group candidate, then re-validated by the stdlib
# ``ipaddress.IPv6Address`` parser — the same "loose candidate + strict validator"
# shape the PAN matcher uses (regex candidate -> Luhn), so the regex need not encode
# the full RFC-4291 grammar (compression rules, group-count arithmetic, embedded IPv4
# tail) — the parser is authoritative and rejects anything malformed. The digit-only
# ``(?<![0-9A-Fa-f:.])`` / ``(?![0-9A-Fa-f:.])`` boundary keeps the candidate from
# biting into an adjacent hex run or a dotted IPv4. The three arms cover: any
# ``::``-compressed form, the full 8-group form, and the 6-group + embedded-IPv4 tail.
_IPV6_HEXTET = r"[0-9A-Fa-f]{1,4}"
_IPV4_INNER = r"(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)"
_IPV6_CANDIDATE = re.compile(
    r"(?<![0-9A-Fa-f:.])(?:"
    rf"(?:{_IPV6_HEXTET})?(?::{_IPV6_HEXTET})*::(?:{_IPV6_HEXTET})?"
    rf"(?::{_IPV6_HEXTET}|:{_IPV4_INNER})*"     # any ::-compressed form
    rf"|(?:{_IPV6_HEXTET}:){{7}}{_IPV6_HEXTET}"  # full 8-group
    rf"|(?:{_IPV6_HEXTET}:){{5}}{_IPV6_HEXTET}:{_IPV4_INNER}"  # 6-group + IPv4 tail
    r")(?![0-9A-Fa-f:.])"
)
# A real IPv6 address contains at least one decimal digit (``fe80::``, ``::1``,
# ``2001:db8::``). Requiring a digit is what separates a genuine address from
# prose scope-resolution (``std::vector``, ``foo::bar``) whose hextets are
# purely-alpha valid-hex ("d", "foo", "bar") — those parse as valid IPv6
# (``d:: == d:0:0:…``) but are far more likely code/prose than PHI. This is a
# measured, conservative bound (the bare ``::`` unspecified address is likewise
# out of scope) — matching the deliberately-conservative posture of the PHONE
# matcher (Appendix G: an obfuscated/edge form is a measured miss, never a silent
# claim of total coverage), and it can only UNDER-mask, never leak an over-match.
_IPV6_HAS_DIGIT = re.compile(r"[0-9]")


def _is_ipv6(candidate: str) -> bool:
    """Is ``candidate`` a genuine IPv6 address (not prose scope-resolution)?

    Validates with the stdlib parser (authoritative on the RFC-4291 grammar) AND
    requires at least one decimal digit so a purely-alpha ``std::vector`` /
    ``foo::bar`` (whose hextets are valid hex words) is not mis-masked as an
    address. A real IPv6 address always carries digits.
    """
    if not _IPV6_HAS_DIGIT.search(candidate):
        return False
    try:
        ipaddress.IPv6Address(candidate)
        return True
    except ValueError:
        return False


def _redact_ip(text: str, nonce: str) -> str:
    # IPv6 candidate FIRST so an IPv4-mapped address (``::ffff:192.168.1.1``) is
    # tokenized whole — if IPv4 ran first it would mask only the embedded dotted
    # tail and strand the ``::ffff:`` prefix in cleartext (a partial redaction).
    # The stdlib parser re-validates each candidate (loose-candidate + strict-
    # validator, like PAN's Luhn gate); a bare-dotted IPv4 is then masked by _IPV4.
    def repl_v6(m: "re.Match[str]") -> str:
        cand = m.group(0)
        return _wire_token(nonce, "IP") if _is_ipv6(cand) else cand

    text = _IPV6_CANDIDATE.sub(repl_v6, text)
    return _IPV4.sub(lambda m: _wire_token(nonce, "IP"), text)


# --- phone / fax -> ⟦…:PHONE⟧ (HIPAA SH) ------------------------------------- #
# North-American-ish shapes; deliberately conservative (Appendix G: obfuscated /
# non-US forms are a measured leak, not a silent claim of full coverage).
_PHONE = re.compile(
    r"(?<![\w])(?:\+?1[ .\-]?)?(?:\(\d{3}\)|\d{3})[ .\-]\d{3}[ .\-]\d{4}(?![\w])"
)


def _redact_phone(text: str, nonce: str) -> str:
    return _PHONE.sub(lambda m: _wire_token(nonce, "PHONE"), text)


# --- explicit dates -> ⟦…:DATE⟧ (HIPAA SH) ----------------------------------- #
_DATE = re.compile(
    r"(?<![\w-])(?:"
    r"\d{4}-\d{2}-\d{2}"                 # ISO 2026-07-01
    r"|\d{1,2}/\d{1,2}/\d{2,4}"          # 07/01/2026
    r")(?![\w-])"
)


def _redact_date(text: str, nonce: str) -> str:
    return _DATE.sub(lambda m: _wire_token(nonce, "DATE"), text)


# --- MRN / account / license / device no. : label-adjacent + shape ----------- #
# Format-anchored (label + shape), NOT pure shape — bounds false positives (E1.1).
_LABELLED_ID = re.compile(
    r"(?i)\b(mrn|medical\s+record(?:\s+(?:no|number|#))?|account(?:\s+(?:no|number|#))?"
    r"|acct(?:\s*#)?|license(?:\s+(?:no|number|#))?|device(?:\s+(?:id|no|number|#))?)"
    r"\b\s*[:=#]?\s*([A-Za-z0-9\-]{4,})"
)

_ID_TYPE_TOKEN = {
    "mrn": "MRN",
    "medical": "MRN",
    "account": "ACCOUNT",
    "acct": "ACCOUNT",
    "license": "LICENSE",
    "device": "DEVICE",
}


def _redact_labelled_id(text: str, nonce: str) -> str:
    def repl(m: "re.Match[str]") -> str:
        label = m.group(1).lower()
        key = label.split()[0]
        type_ = _ID_TYPE_TOKEN.get(key, "ID")
        return f"{m.group(1)}: {_wire_token(nonce, type_)}"

    return _LABELLED_ID.sub(repl, text)


# --- high-entropy secret / API key : Shannon entropy + charset (LAST) -------- #
# Broadest, lowest precedence — runs after every structured matcher so it never
# steals a card/SSN/etc. Threshold + length bounds avoid scrubbing legitimate
# short IDs; the token-charset requirement avoids masking prose words.
_SECRET_ENTROPY_MIN = 3.5          # bits/char floor for a "random-looking" token
_SECRET_MIN_LEN = 20
# Boundary excludes only the token's own charset (so we grab the whole token), NOT
# a leading/trailing '=' — `key=<secret>` is the common shape and must still match.
_SECRET_CANDIDATE = re.compile(r"(?<![\w/+\-])[A-Za-z0-9/+_\-]{20,}(?![\w/+\-])")

# Known credential-token prefixes (case-sensitive) that mark a candidate as a
# secret regardless of the entropy/charset heuristic. A 20-char access-key id like
# ``AKIAIOSFODNN7EXAMPLE`` is all upper+digit (mixed=False) with entropy < 4.0, so
# the generic heuristic misses it and it egresses RAW (credential leak, NFR-7 (a)).
# These prefixes are unambiguous credential formats (AWS access/session key ids,
# GCP API keys, GitHub PATs, Slack bot tokens), so prefix-anchoring adds recall
# with negligible false-positive risk. The generic heuristic still runs for
# everything else. Kept short + specific so ordinary tokens aren't over-matched.
_SECRET_PREFIXES = ("AKIA", "ASIA", "AIza", "ghp_", "gho_", "xoxb", "xoxp")

# Long pure-hex run (EITHER case) — a SHA1/SHA256/HMAC digest, hex session token,
# or hex API key. Such a token clears the ≥3.5 entropy floor but fails BOTH the
# mixed-charset gate (a same-case hex run has no upper+lower mix) AND the ≥4.0
# non-mixed fallback (a 16-symbol hex alphabet caps entropy at 4.0 and a 40-char
# digest sits near 3.7), so the generic heuristic missed it and it egressed RAW
# (R2-H1, credential leak, NFR-7 (a)). The match is CASE-INSENSITIVE (``[0-9a-fA-F]``)
# because the leak is charset-CASE-independent: an all-UPPER-case digest/token (upper
# SHA1/SHA256/MD5, an uppercase HMAC signature, an uppercase hex session key) has no
# lowercase char (``mixed=False``) and the same ~3.7 (<4.0) entropy cap, so the mixed
# gate, the ≥4.0 fallback, AND a lowercase-only ``^[0-9a-f]{32,}$`` ALL miss it — the
# raw uppercase credential egressed while its lowercase twin was masked (R2-H1 was
# only half-closed; behaviour must not be case-dependent). A 32+ char pure-hex run is
# not a benign identifier (a UUID carries dashes; an order number is far shorter and
# not full-hex), so treating it as a secret outright adds recall with negligible
# false-positive risk. 32 = the shortest common digest (MD5); SHA1 (40)/SHA256 (64)
# exceed it.
_HEX_SECRET = re.compile(r"^[0-9a-fA-F]{32,}$")

# A POSITIVE filesystem/URI path signal — a scheme (``s3://``, ``file://``, ``http``),
# a leading ``/`` (POSIX absolute path), a drive letter (``C:/``), or a filename
# extension (``.log`` / ``.json`` / ``.xlsx``) in any segment. Used to keep the R2-M2
# path passthrough EXPLICIT: a candidate only passes through as a path when it carries
# one of these real path markers. The earlier passthrough was purely negative ("no
# segment independently qualifies as a secret"), which let a slash-DENSE secret whose
# chunks are individually too short to qualify (``a1B2/c3D4/e5F6/…``) slip through as if
# it were a path — a credential fail-open (residual MEDIUM, NFR-7 (a)). Anchoring the
# passthrough to a positive path signal, and testing the separator-stripped core when
# NO path signal is present, closes that class while still preserving the param signal
# the PDP needs for Cedar param-bounds / sequence checks on the financial-action
# beachhead (a real ``s3://…`` / ``/var/log/…`` / ``C:/…`` / ``…/settings.json`` path
# still passes through).
_PATH_SIGNAL = re.compile(
    r"^[a-z][a-z0-9+.\-]*://"        # scheme:// (s3://, file://, https://)
    r"|^/"                            # POSIX absolute path
    r"|^[A-Za-z]:/"                   # Windows drive path (C:/)
    r"|(?:^|/)[^/]+\.[A-Za-z0-9]{1,6}(?:/|$)"  # a segment with a filename extension
)
# Separators that chunk a secret into path-shaped pieces; stripped before the
# whole-core entropy test so a slash/underscore/hyphen-DENSE secret is still detected.
_SECRET_CHUNK_SEP = re.compile(r"[/_\-]")


def _redact_secret(text: str, nonce: str) -> str:
    def repl(m: "re.Match[str]") -> str:
        cand = m.group(0)
        if len(cand) < _SECRET_MIN_LEN:
            return cand
        # Known credential-format prefix wins outright — these are unambiguous
        # credential material even when the generic entropy/charset gate would miss
        # them (e.g. an AWS access-key id: all-uppercase+digit, entropy < 4.0).
        if cand.startswith(_SECRET_PREFIXES):
            return _wire_token(nonce, "SECRET")
        # Long all-lowercase-hex digest/token wins outright — the mixed-charset gate
        # and the ≥4.0 fallback both miss it (R2-H1). A hex-charset token is
        # credential material, not prose, so this adds recall with negligible FP risk.
        if _HEX_SECRET.match(cand):
            return _wire_token(nonce, "SECRET")
        # Slash-bearing candidate: a filesystem/URI path or a separator-chunked secret?
        # Over-masking a real path to ⟦…:SECRET⟧ destroys the param signal the PDP needs
        # for Cedar param-bounds / sequence checks on the financial-action beachhead
        # (R2-M2), but passing a chunked secret through leaks a credential (residual
        # MEDIUM, NFR-7 (a)). Precedence (security-first, path-preserving):
        #   1. any single ``/``-segment is itself secret-shaped -> SECRET (a base64
        #      secret with a slash always has a long qualifying chunk).
        #   2. otherwise a POSITIVE path/URI signal (:data:`_PATH_SIGNAL`) with no
        #      secret segment -> pass through as a path (R2-M2).
        #   3. otherwise (slash-DENSE, no path signal, no long chunk) test the
        #      separator-STRIPPED core: a slash/underscore/hyphen-chunked secret
        #      (``a1B2/c3D4/e5F6/…``) whose chunks are individually too short to qualify
        #      is caught here -> SECRET; a genuine low-entropy relative path
        #      (``reports/q3/summary``) fails the core test and passes through.
        if "/" in cand:
            if any(_segment_is_secretish(seg) for seg in cand.split("/") if seg):
                return _wire_token(nonce, "SECRET")
            if _PATH_SIGNAL.search(cand):
                return cand  # a real path/URI — preserve the param signal (R2-M2)
            core = _SECRET_CHUNK_SEP.sub("", cand)
            if _segment_is_secretish(core, high_entropy_floor=4.5):
                return _wire_token(nonce, "SECRET")
            return cand
        # Require mixed charset (upper+lower+digit) OR very high entropy so a long
        # lowercase English word isn't masked as a secret.
        if not _segment_is_secretish(cand):
            return cand
        return _wire_token(nonce, "SECRET")

    return _SECRET_CANDIDATE.sub(repl, text)


def _segment_is_secretish(cand: str, *, high_entropy_floor: float = 4.0) -> bool:
    """Does ``cand`` look like secret material on its own (charset + entropy)?

    The shared gate for :func:`_redact_secret`: a candidate (or a single ``/``-
    delimited segment of one, or a separator-stripped core) is secret-shaped when it is
    long enough AND either has a mixed upper+lower+digit charset over the entropy floor,
    or is very high entropy, or is a long pure-hex run. Used to decide a whole candidate,
    to keep a filesystem/URI path (no secret-shaped segment) from being over-masked
    (R2-M2), and to catch a separator-chunked secret by its stripped core.

    ``high_entropy_floor`` is the "very high entropy alone (charset not tri-mixed)"
    bar. It defaults to 4.0 for a contiguous candidate; the separator-stripped core of a
    slash-DENSE run is tested at a stricter 4.5 so a mildly-mixed real path core does not
    trip the non-mixed entropy arm (only a genuinely random chunked secret does).
    """
    if len(cand) < _SECRET_MIN_LEN:
        return False
    if _HEX_SECRET.match(cand):
        return True
    has_upper = any(c.isupper() for c in cand)
    has_lower = any(c.islower() for c in cand)
    has_digit = any(c.isdigit() for c in cand)
    mixed = has_upper and has_lower and has_digit
    entropy = _shannon_entropy(cand)
    if entropy < _SECRET_ENTROPY_MIN:
        return False
    return mixed or entropy >= high_entropy_floor


# --------------------------------------------------------------------------- #
# The frozen matcher order (SECURITY CONTROL — do not reorder casually; the
# order is asserted by a test). Highest-harm / most-specific first; SAD before
# any numeric; PAN(+Luhn) before any bare-numeric; SECRET-entropy last.
# --------------------------------------------------------------------------- #
_Matcher = Tuple[str, Callable[[str, str], str]]

_ORDERED_MATCHERS: Tuple[_Matcher, ...] = (
    ("SAD", _redact_sad),               # never-store, most-specific, first
    ("CARD", _redact_pan),              # Luhn-gated, before any bare-numeric
    # EMAIL/URL run BEFORE LABELLED_ID: a label word adjacent to an email/URL
    # (e.g. "license jsmith@acme.com") would otherwise let LABELLED_ID's value
    # capture grab the local-part ("jsmith") and tokenize it as a LICENSE id,
    # leaving the raw domain ("@acme.com") in cleartext — a partial-redaction
    # PII leak that egresses to the hosted PDP (NFR-7 (a); E1.4 never egress a
    # partially-redacted value). Running the whole-email/URL matchers first
    # tokenizes the entire value; the residual "⟦…⟧" bracket then breaks the
    # LABELLED_ID value capture, so no double-tokenization occurs.
    ("EMAIL", _redact_email),
    ("URL", _redact_url),               # before LABELLED_ID and IP/PHONE
    ("LABELLED_ID", _redact_labelled_id),  # format-anchored MRN/account/license/device
    ("SSN", _redact_ssn),
    ("IP", _redact_ip),
    ("PHONE", _redact_phone),
    ("DATE", _redact_date),
    ("SECRET", _redact_secret),         # broadest, lowest precedence, LAST
)


@dataclass(frozen=True)
class RedactionResult:
    """Outcome of redacting one value: the safe wire text + which types fired.

    ``types`` is metadata for the caller/telemetry (never the raw value); the
    redacted ``text`` is what egresses.
    """

    text: str
    types: Tuple[str, ...]


# --------------------------------------------------------------------------- #
# NOTE (WS-B ownership): the phase -> egress-field mapping is OWNED by WS-B (the
# multiphase contract, LLD 30). Egressing content for the content/output/memory
# phases lives in the SINGLE `content_text` field on the wire, disambiguated by
# the top-level `phase` (WS-B's `_CONTENT_FIELD` map + `KNOWN_PHASES` frozenset);
# an unknown phase is a 422 server-side. WS-E CONSUMES that seam — the guard hands
# `content_text` to :func:`redact` with the per-egress nonce like any other field.
# WS-E does NOT re-declare per-phase content fields here (that divergence was the
# reverted mistake); this module only redacts whatever content it is given.
# --------------------------------------------------------------------------- #
# Edge image/binary detection + tagging (E6.1 / FR-3.15). The edge NEVER attempts
# pixel redaction and NEVER egresses a raw image/binary blob. A string leaf that
# is (a) a data-URI image, or (b) a long, high-entropy base64 blob is TAGGED to an
# ⟦…:IMAGE⟧ marker and routed to the server-side Tier-2 (the mode router that
# resolves evaluate|redact|block is a LATER server-side stage — here the edge only
# detects + tags + refuses-raw). Kept conservative (a long, valid-base64,
# high-entropy run) so ordinary prose / short tokens are never mis-tagged.
# --------------------------------------------------------------------------- #
_DATA_URI_IMAGE = re.compile(r"^\s*data:image/[A-Za-z0-9.+\-]+;base64,", re.IGNORECASE)
_BASE64_BLOB = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")
_IMAGE_MIN_LEN = 512          # a real inlined image blob is large; prose is not
_IMAGE_ENTROPY_MIN = 4.5      # base64 of compressed/image bytes is high-entropy


def _maybe_image_tag(value: str, nonce: Optional[str]) -> Optional[str]:
    """Return an ⟦…:IMAGE⟧ marker if ``value`` looks like an image/binary blob,
    else ``None`` (the caller then treats it as text) — E6.1.

    Two shapes are detected: an explicit ``data:image/...;base64,`` URI, and a bare
    long high-entropy base64 run (an inlined attachment). Detection is deliberately
    conservative — a real image blob is large and near-max-entropy, whereas prose,
    IDs, and even a long secret token are shorter and/or lower entropy — so this
    never mis-tags text (which must still flow through the deterministic matchers).
    The raw blob is dropped entirely: the edge routes it to Tier-2, it is never
    pixel-redacted and never egressed raw.
    """
    stripped = value.strip()
    n = nonce if nonce is not None else _make_nonce()
    if _DATA_URI_IMAGE.match(stripped):
        return _wire_token(n, "IMAGE")
    if (
        len(stripped) >= _IMAGE_MIN_LEN
        and _BASE64_BLOB.match(stripped)
        and _shannon_entropy(stripped) >= _IMAGE_ENTROPY_MIN
    ):
        return _wire_token(n, "IMAGE")
    return None


def redact(value: str, *, nonce: Optional[str] = None) -> str:
    """Redact one string value into egress-safe wire text (E1.2 entrypoint).

    Neutralizes planted sentinels first (M-4), then runs the frozen matcher chain.
    Returns the redacted string. Raises :class:`RedactionError` on any internal
    failure so the caller fails secure (never egresses a raw or partially-redacted
    value — E1.4).

    ``nonce`` is the per-egress marker nonce (§3.3). When the caller
    (``guard._build_request``) mints ONE ``secrets.token_hex(8)`` per egress and
    threads it through every field (``tool_params`` / ``user_input`` / the
    phase-specific content field / ``context``), all genuine markers in that
    payload share the single ``redaction_nonce`` the PDP checks against. When
    omitted (standalone / test use) a fresh CSPRNG nonce is minted per call — the
    per-call-freshness M-4 property still holds either way.
    """
    return redact_detailed(value, nonce=nonce).text


def redact_detailed(value: str, *, nonce: Optional[str] = None) -> RedactionResult:
    """As :func:`redact`, but also reports which typed tokens fired.

    A non-string is a caller error, surfaced as :class:`RedactionError` (the guard
    turns it into a DENY) — we never silently pass a non-string through to egress.
    """
    if not isinstance(value, str):
        raise RedactionError(
            f"redact() expects str, got {type(value).__name__}"
        )
    try:
        nonce = nonce if nonce is not None else _make_nonce()
        # E6.1: a content field (or user_input) may itself be an inlined image/
        # binary blob. Tag + route it (never pixel-redact, never egress raw) before
        # running the text matchers on what would otherwise be a huge base64 run.
        image_tag = _maybe_image_tag(value, nonce)
        if image_tag is not None:
            return RedactionResult(text=image_tag, types=("IMAGE",))
        # Unicode NFKC-normalize FIRST (before neutralization/matching). This folds
        # compatibility-obfuscated PII — fullwidth digits (`４111`), homoglyphs and
        # other compatibility variants — back to their ASCII canonical form so the
        # matchers see the real value (Appendix G (ii) obfuscated/encoded corpus;
        # LLD 29 §14.4). Without it a fullwidth-digit PAN/SSN/phone egresses RAW
        # (fail-open PCI/PHI leak, NFR-7 (a)); worse, a pure-fullwidth 16-digit run
        # is still counted by ``\d`` so it reaches ``_luhn_ok``/first6-last4 as
        # garbage ``ord()-48`` values, and a mod-10 coincidence emits raw non-ASCII
        # partial-PAN cleartext into the CARD meta. NFKC fixes both: digits become
        # ASCII, Luhn is computed on real digits, and the meta is normalized. This
        # is why LLD 29 §3.1 lists ``unicodedata`` as a required stdlib import.
        text = unicodedata.normalize("NFKC", value)
        text = _neutralize_planted_tokens(text)
        fired: List[str] = []
        for name, matcher in _ORDERED_MATCHERS:
            before = text
            # Run each matcher ONLY on text outside the tokens earlier matchers
            # already emitted (M-4): the per-call nonce is hex and can contain a
            # Luhn-valid digit run / secret-shaped span, so an unguarded later
            # matcher would corrupt an earlier token's nonce/meta and nest a bogus
            # token inside it. _apply_outside_tokens keeps emitted tokens inviolable.
            text = _apply_outside_tokens(matcher, text, nonce)
            if text != before:
                fired.append(name)
        return RedactionResult(text=text, types=tuple(fired))
    except RedactionError:
        raise
    except Exception as exc:  # noqa: BLE001 — fail secure: never leak the raw value
        # Deliberately do NOT include ``value`` in the message: a redactor error
        # must not itself leak the raw content (NFR-7 clause (a)).
        raise RedactionError(f"redaction failed: {type(exc).__name__}") from exc


def redact_params(params: dict, *, nonce: Optional[str] = None) -> dict:
    """Redact every string leaf of a ``tool_params`` dict, recursively (E1.3).

    Walks lists/dicts and redacts string leaves in place (a copy — the caller's
    dict is not mutated). Dict **keys** are redacted too (a key can carry PII/PCI —
    ``{"alice@corp.com": ...}``). Non-string leaves (int/float/bool/None) are
    structural, not content, and pass through. A ``bytes`` leaf/key is binary/image
    content the text redactor cannot scrub (FR-3.15) — refused via
    :class:`RedactionError` (the guard fails secure; it does NOT send the raw
    bytes) — see E1.5. A **base64 image/binary blob carried as a string** (the
    common edge shape — an inlined data-URI / attachment) is *tagged* to an
    ``IMAGE`` marker + routed to Tier-2, never pixel-redacted and never sent raw
    (E6.1); see :func:`_maybe_image_tag`.

    ``nonce`` threads the per-egress marker nonce (§3.3) so image tags + text
    tokens across the whole payload share one ``redaction_nonce``; when omitted a
    fresh CSPRNG nonce is minted per string leaf (standalone / test use).

    Fail-secure (E1.4): the whole traversal is wrapped so ANY internal failure —
    a :class:`RedactionError` from a leaf, or an unexpected error such as a
    ``RecursionError`` on a pathologically deep/cyclic structure — surfaces as a
    :class:`RedactionError`. This is a public exported API: the guard only catches
    ``RedactionError`` (``guard._build_request``), so a bare ``RecursionError``
    escaping here would bypass the fail-secure DENY and let the raw params egress.
    As in :func:`redact_detailed`, the re-wrapped message carries only the error
    *type*, never the raw ``params`` (NFR-7 clause (a)).
    """
    try:
        return _walk(params, nonce)
    except RedactionError:
        raise
    except Exception as exc:  # noqa: BLE001 — fail secure: never leak the raw params
        raise RedactionError(
            f"param redaction failed: {type(exc).__name__}"
        ) from exc


def _walk(obj, nonce: Optional[str]):
    if isinstance(obj, str):
        # A string leaf may itself be a base64-encoded image/binary blob (an
        # inlined attachment / data-URI). ``redact`` tags it to an IMAGE marker +
        # routes to Tier-2 (E6.1) — the edge NEVER pixel-redacts and NEVER egresses
        # the raw blob; only genuine text reaches the deterministic matcher chain.
        return redact(obj, nonce=nonce)
    if isinstance(obj, (bytes, bytearray)):
        # FR-3.15 / E6.1: raw binary/image content is out of scope for the text
        # redactor. Refuse rather than attempt-redact-or-send-raw (E1.5 / error
        # model). Raw bytes rarely survive JSON-serialization to reach here, but if
        # they do we fail toward refusal, never toward egressing the blob.
        raise RedactionError(
            "binary/image content cannot be edge-redacted (FR-3.15); "
            "refuse egress or route to in-VPC"
        )
    if isinstance(obj, dict):
        # Redact KEYS as well as values: a caller can put structured PII/PCI in a
        # dict key (e.g. {"alice@corp.com": ...} or {"4111111111111111": ...}) and
        # an un-redacted key egresses raw to the hosted PDP (NFR-7 (a)). String
        # keys go through redact(); a bytes key is binary content the text redactor
        # cannot scrub, refused just like a bytes leaf (FR-3.15 / E1.5). Non-string,
        # non-bytes keys (int/float/bool/None/tuple) are structural — pass through.
        #
        # Entry-count preservation (R5-M1): typed tokens are lossy by design, so two
        # DISTINCT PII keys can redact to the SAME wire token —
        # {"alice@corp.com": ..., "bob@corp.com": ...} both -> ⟦AEGR:{nonce}:EMAIL⟧.
        # A dict comprehension would silently collapse them (last-write-wins),
        # dropping entries so the payload arrives at the PDP with FEWER keys than the
        # agent sent — a security-relevant loss of arity that can flip a decision to
        # a wrong-ALLOW (the PDP never sees the params it would have denied on). We
        # therefore disambiguate collisions with a stable ordinal suffix appended
        # OUTSIDE the wire token (``⟦…⟧#2``) so ``len(out) == len(obj)`` ALWAYS. The
        # suffix carries only a counter — never any raw key bytes (NFR-7 (a)) — and a
        # bare ``#n`` cannot masquerade as a marker (only the reserved bracket + nonce
        # grammar is a genuine token, M-4). First occurrence keeps the plain token;
        # duplicates take ``#2``, ``#3``, … in the dict's (insertion) order.
        out: dict = {}
        seen: dict = {}
        for k, v in obj.items():
            rk = _walk_key(k, nonce)
            walked_v = _walk(v, nonce)
            if rk in out:
                n = seen.get(rk, 1) + 1
                seen[rk] = n
                disambiguated = f"{rk}#{n}"
                # Guard the (astronomically unlikely) case where the suffixed form
                # itself collides with a caller-supplied key — keep bumping so no
                # entry is ever dropped.
                while disambiguated in out:
                    n += 1
                    seen[rk] = n
                    disambiguated = f"{rk}#{n}"
                out[disambiguated] = walked_v
            else:
                out[rk] = walked_v
        return out
    if isinstance(obj, (list, tuple)):
        return [_walk(v, nonce) for v in obj]
    # int / float / bool / None — structural, not content; pass through.
    return obj


def _walk_key(key, nonce: Optional[str]):
    """Redact a dict key. Keys must stay hashable, so a str key is redacted to its
    wire form (still a str) and a ``bytes`` key is refused (FR-3.15 / E1.5); other
    hashable key types are structural and pass through unchanged."""
    if isinstance(key, str):
        return redact(key, nonce=nonce)
    if isinstance(key, (bytes, bytearray)):
        raise RedactionError(
            "binary/image content cannot be edge-redacted (FR-3.15); "
            "refuse egress or route to in-VPC"
        )
    return key
