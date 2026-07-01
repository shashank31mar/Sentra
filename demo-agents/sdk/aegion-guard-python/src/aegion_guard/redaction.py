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
# Matchers. Each is (name, callable) where the callable takes (text, nonce) and
# returns the text with its class of values replaced by wire tokens. Order is a
# security control: _ORDERED_MATCHERS is frozen highest-harm/most-specific first.
# --------------------------------------------------------------------------- #

# --- PAN (card) : regex candidate -> windowed Luhn -> ⟦…:CARD:first6:last4⟧ --- #
# 13-19 digits, optionally separated into groups by up to TWO of {space, TAB, newline
# (CR or LF), hyphen, dot, slash, comma, underscore} chars between groups (a two-char
# ``\r\n`` CRLF from a Windows/multi-line paste, or ``,`` + space from a TSV/CSV cell). The separator set is DELIBERATELY
# wide: a PAN pasted from a spreadsheet, a TSV/CSV cell, a formatted field, or a
# multi-line form commonly carries a non-standard group separator
# (``4111.1111.1111.1111``, ``4111/1111/…``, ``4111_1111…``, ``4111,1111,…``, a
# TAB-delimited ``4111\t1111\t…`` from a spreadsheet/TSV, or a newline-wrapped
# ``4111\n1111\n…`` from a multiline field) — and with a set that omitted TAB/newline
# those whitespace-delimited forms egressed the card RAW (R2-C1, PCI fail-open, M-3 /
# NFR-7 (a)): the design intent of this class is to cover exactly the spreadsheet /
# formatted-field paste, where TAB is the canonical delimiter, so omitting it was
# inconsistent with the stated intent. :data:`_PAN_SEP` is the single canonical
# separator class shared by :data:`_PAN_CANDIDATE` and the SAD footgun run
# (:data:`_SAD_VALUE_PAN_RUN`) so the accepted separators stay in lock-step (widening
# one without the other re-opens R2-C1/R2-C2). NOTE the SSN matcher (:data:`_SSN`)
# deliberately keeps its OWN narrower ``[ .\-]`` class (dash/space/dot only — ``/``,
# ``,``, ``_`` are date/thousands/identifier shapes, not SSN forms), so it is not
# driven by ``_PAN_SEP`` and this widening does not touch it.
#
# The candidate boundary is DELIBERATELY loose: because a separator is also a valid
# inter-group separator, the candidate can over-capture one OR MORE separated
# leading/trailing digit-GROUPS that are NOT part of the card (e.g. "pay 5 4111 1111
# 1111 1111", "amount 100 4111111111111111", "99 4111 1111 1111 1111" or
# "4111111111111111 12"). If we ran Luhn once on the whole captured run it would be
# 17-19 digits, fail Luhn, and — fatally — the old all-or-nothing path returned the
# run RAW, so a real PAN egressed in cleartext (PCI fail-open, M-3 / NFR-7 (a)). The
# group-windowed Luhn scan below re-bounds the candidate to the actual card, so an
# over-captured candidate degrades to redacting the card, never to emitting it raw and
# never to emitting the WRONG window (a longer/shifted Luhn-valid run formed by an
# injected adjacent digit — which would leak a real card digit in cleartext and put an
# injected digit into the first6/last4 meta; see _best_pan_window). The digit-only
# ``(?<!\d)``/``(?!\d)`` boundary (not ``[\w-]``) is required now that ``_`` is an
# accepted separator: a ``\w`` boundary would refuse a card whose own separator is an
# underscore. The Luhn gate + group-window scan bound false positives, so the loose
# boundary never mis-masks a non-card run.
_PAN_SEP = r"[ \t\r\n\-./,_]"
# Up to TWO separator chars may sit between digit groups (``{0,2}``), not just one:
# a multi-line/Windows paste separates groups with a two-char ``\r\n`` (CRLF), and a
# TSV/CSV cell boundary can be ``,`` + space — a single-separator quantifier broke the
# digit run at the double separator so a CRLF-wrapped card still egressed RAW (R2-C1
# whitespace form). The bound is 2 (not unbounded ``*``) so the loose candidate cannot
# span a large gap and mis-associate two distant numbers; the group-windowed Luhn scan
# (:func:`_best_pan_window`, which trims WHOLE ASCII digit-groups) re-bounds any
# over-capture to the actual card regardless of how many separator chars sat between
# groups, so widening the run count never mis-masks a non-card run nor drops the
# surrounding text.
_PAN_CANDIDATE = re.compile(rf"(?<!\d)(\d{_PAN_SEP}{{0,2}}){{12,18}}\d(?!\d)")

# ASCII digit RUNS only. A PAN written in non-ASCII \d-matching digits (Arabic-Indic,
# Devanagari, or a fullwidth digit that slipped NFKC) must NOT be treated as a card:
# the stdlib Luhn works on ``ord()-48`` so non-ASCII code points feed it garbage, and
# a mod-10 coincidence would emit the raw non-ASCII partial-PAN into the CARD meta —
# itself cleartext PII on the wire. NFKC (see redact_detailed) folds the common
# compatibility digits to ASCII first; anything still non-ASCII here is out of scope
# for the card matcher and is left untouched for the later matchers (never mistaken
# for a card, never partially emitted). See Appendix G (ii) / LLD 29 §14.4.
_ASCII_DIGIT_RUN = re.compile(r"[0-9]+")

# Standard PAN lengths, most-common first. When an over-captured candidate has more
# than one Luhn-valid group-window, we prefer the one whose length is a real card
# length (Visa/MC/Discover 16, Amex 15, then the rarer 14/13, then the over-length
# 19/18/17). This anchors selection to the ACTUAL card rather than to whichever window
# an injected adjacent digit happened to also make Luhn-valid: without it, a longer
# Luhn-valid run (e.g. injected "004" + card, or card + injected "99") could win,
# emit a bogus first6/last4, and strand a real card digit outside the token in
# cleartext (finding: "Wrong PAN window masked").
_PAN_STD_LENGTHS: Tuple[int, ...] = (16, 15, 14, 13, 19, 18, 17)


def _best_pan_window(raw: str) -> "Tuple[int, int, str] | None":
    """Re-bound an over-captured PAN candidate to the actual Luhn-valid card.

    ``raw`` is one ``_PAN_CANDIDATE`` match, which may have swallowed one or more
    separated leading/trailing digit-GROUPS that are not part of the card (loose
    boundary by design — see _PAN_CANDIDATE). A stray digit can only attach to the
    card *through a separator* (space/hyphen); a purely contiguous run is a single
    group and cannot be trimmed. So we split ``raw`` into ASCII digit-groups on its
    separators and try the sub-runs formed by dropping 0..k WHOLE leading/trailing
    groups — never an internal sub-window, and never a partial group. Trimming whole
    groups only (not arbitrary digits) is what keeps a legitimate long *contiguous*
    number (an order id / concatenated timestamp) from being mis-masked: with no
    separator it is one group, so the whole run must itself be Luhn-valid to count as
    a card — preserving the E1.1 false-positive gate the Luhn check exists for.

    Among the Luhn-valid group-windows we select, in order: (1) the one whose length
    is a real card length (:data:`_PAN_STD_LENGTHS`) — so an injected adjacent digit
    that merely *extends* a card into a longer Luhn-valid run cannot win and emit a
    bogus first6/last4 while stranding a real card digit in cleartext; (2) the fewest
    trimmed groups (closest to the capture); (3) the fewest leading trims. Returns
    ``(start, end, digits)`` where ``raw[start:end]`` is the exact card substring to
    tokenize (only genuinely non-card leading/trailing groups are preserved as
    cleartext — never a card digit), or ``None`` if no group-window is a valid PAN (a
    genuine non-card run degrades to "leave as-is" — never emitted raw *as a card* nor
    mis-masked).
    """
    # ASCII digit-groups with their (start, end) span in ``raw``; non-ASCII digits
    # are excluded so they are never counted toward a card (see _ASCII_DIGIT_RUN).
    groups = [
        (m.start(), m.end(), m.group(0)) for m in _ASCII_DIGIT_RUN.finditer(raw)
    ]
    ng = len(groups)
    if ng == 0 or sum(len(g[2]) for g in groups) < 13:
        return None
    best_key: "Tuple[int, int, int] | None" = None
    best_span: "Tuple[int, int, str] | None" = None
    for lead in range(ng):
        for trail in range(ng - lead):
            sub = groups[lead : ng - trail] if trail else groups[lead:]
            if not sub:
                continue
            digits = "".join(g[2] for g in sub)
            length = len(digits)
            if not (13 <= length <= 19) or not _luhn_ok(digits):
                continue
            try:
                len_priority = _PAN_STD_LENGTHS.index(length)
            except ValueError:  # pragma: no cover — 13..19 are all listed
                len_priority = len(_PAN_STD_LENGTHS)
            key = (len_priority, lead + trail, lead)
            if best_key is None or key < best_key:
                best_key = key
                best_span = (sub[0][0], sub[-1][1], digits)
    return best_span


def _redact_pan(text: str, nonce: str) -> str:
    def repl(m: "re.Match[str]") -> str:
        raw = m.group(0)
        window = _best_pan_window(raw)
        if window is None:
            return raw  # not a card — leave for later matchers / as-is
        start, end, digits = window
        # PCI: first6/last4 ONLY. Middle digits are GONE; never emit the full PAN.
        meta = f"{digits[:6]}:{digits[-4:]}"
        token = _wire_token(nonce, "CARD", meta)
        # Preserve any non-card characters the loose candidate over-captured (a
        # separated leading/trailing digit or its separator) so ONLY the card
        # substring is replaced and the surrounding text is never dropped.
        return f"{raw[:start]}{token}{raw[end:]}"

    return _PAN_CANDIDATE.sub(repl, text)


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

# A separator-joined digit run starting at the SAD value group, used by the footgun
# guard in ``_redact_sad``. Uses the SAME separator set as ``_PAN_CANDIDATE``
# (:data:`_PAN_SEP`) so the SAD guard sees the whole trailing card regardless of its
# separator — matched anchored at the SAD-captured leading group. A space/hyphen-only
# run here (while _PAN_CANDIDATE accepts dots/slashes/etc.) re-opened R2-C2: for
# "pin is 4111.1111.1111.1111" the guard saw only the leading "4111", declined to
# step aside, and tokenized it to SAD — stranding the trailing 12 card digits in
# cleartext behind a marker that falsely looked redacted (worse than a plain miss).
# Allows up to TWO separator chars between digits in lock-step with ``_PAN_CANDIDATE``
# (``{0,2}``) so a SAD label before a CRLF/multi-line-separated card
# ("pin is 4111\r\n1111\r\n1111\r\n1111") still lets the guard see the whole trailing
# Luhn-valid card and step aside for ``_redact_pan`` — a single-separator run here
# (while _PAN_CANDIDATE accepts a two-char CRLF) would re-open the R2-C2 partial-PAN.
_SAD_VALUE_PAN_RUN = re.compile(rf"\d(?:{_PAN_SEP}{{0,2}}\d)*")


def _redact_sad(text: str, nonce: str) -> str:
    def repl(m: "re.Match[str]") -> str:
        # SAD footgun (M-3 / NFR-7 (a) — PCI fail-open): the value capture ``(\d{3,6})``
        # matches only the LEADING digit-group of a space/hyphen-separated card that
        # trails a SAD label (e.g. "pin is 4111 1111 1111 1111" captures just "4111").
        # SAD runs BEFORE PAN, so if we tokenized "4111" to SAD here the remaining
        # "1111 1111 1111" is 12 digits — below _PAN_CANDIDATE's 13-digit floor — so
        # the PAN matcher would never fire and 12 real card digits would egress in
        # cleartext (a partially-redacted PAN, which E1.4 forbids). Guard: if the run
        # STARTING at this value group (separator-joined) contains a Luhn-valid 13-19
        # digit PAN, DECLINE the SAD match (return the matched text unchanged) so the
        # later ``_redact_pan`` tokenizes the WHOLE card (its loose candidate treats the
        # label prefix as over-captured non-card text). The frozen SAD-first order is
        # preserved — SAD just steps aside for the more-specific PAN when its value is a
        # card's leading group. A genuine short SAD ("pin is 4821") has no Luhn-valid
        # trailing run, so it still tokenizes to SAD exactly as before.
        value_start = m.start(2)
        run_match = _SAD_VALUE_PAN_RUN.match(text, value_start)
        if run_match is not None and _best_pan_window(run_match.group(0)) is not None:
            return m.group(0)  # leave for _redact_pan — do NOT partially redact a card
        # Keep the label, drop the value into a no-meta SAD token.
        return f"{m.group(1)}: {_wire_token(nonce, 'SAD')}"

    return _SAD_ANCHORED.sub(repl, text)


# --- SSN (US) : format-anchored -> ⟦…:SSN⟧ (HIPAA SH) ------------------------ #
# 3-2-4 grouping with a CONSISTENT separator that is a dash, single space, or dot.
# Dash-only egressed the space/dot forms ("123 45 6789", "123.45.6789") RAW (R2-M1).
# The three groups must share one separator (a back-reference) so a mixed/garbage run
# ("123-45 6789") is not mis-matched; ``/`` , ``,`` and ``_`` are intentionally NOT
# SSN separators (they are date/thousands/identifier shapes, not SSN forms). The
# digit boundary keeps it from biting into a longer number.
_SSN = re.compile(r"(?<!\d)(\d{3})([ .\-])(\d{2})\2(\d{4})(?!\d)")


def _redact_ssn(text: str, nonce: str) -> str:
    return _SSN.sub(lambda m: _wire_token(nonce, "SSN"), text)


# --- email -> ⟦…:EMAIL⟧ (HIPAA SH) ------------------------------------------- #
_EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")


def _redact_email(text: str, nonce: str) -> str:
    return _EMAIL.sub(lambda m: _wire_token(nonce, "EMAIL"), text)


# --- URL -> ⟦…:URL⟧ (HIPAA SH) — before phone so an in-URL number isn't a phone #
_URL = re.compile(r"\bhttps?://[^\s<>⟦⟧\"']+")

# E7.2 — Tier-1 URL query-secret strip. A URL whose query carries a bearer secret
# (``?token=…`` / ``?api_key=…`` / ``?access_token=…`` / ``?sig=…`` and friends)
# must not egress that secret in cleartext even though the whole URL is already
# tokenized to ⟦…:URL⟧ below. This is a SUPPLEMENT to the (later, server-side)
# FR-2.9 destination allow-list, not a replacement and not a parallel URL subsystem
# (E7.2). Because the whole URL becomes a single opaque ⟦…:URL⟧ token, the secret
# value is removed with it — but we assert the strip explicitly so a future change
# that emits any part of the URL cleartext still drops the secret. The param-name
# list is the common bearer-secret set; matched case-insensitively.
_URL_SECRET_QUERY = re.compile(
    r"(?i)([?&](?:access_token|api_key|apikey|token|auth|key|secret|sig|"
    r"signature|password|pwd|session)=)[^&\s#]+"
)


def _strip_url_query_secrets(url: str, nonce: str) -> str:
    """Replace a secret-bearing query value inside a URL with a SECRET token (E7.2).

    Runs on the raw URL substring BEFORE the whole thing is tokenized to URL, so a
    ``?token=<secret>`` value never survives even if a later change were to emit
    part of the URL in cleartext. The param name is kept (structural signal); the
    value becomes a ⟦…:SECRET⟧ marker.
    """
    return _URL_SECRET_QUERY.sub(
        lambda m: f"{m.group(1)}{_wire_token(nonce, 'SECRET')}", url
    )


def _redact_url(text: str, nonce: str) -> str:
    def repl(m: "re.Match[str]") -> str:
        # The whole URL — path, query, and any ``?token=<secret>`` value — collapses
        # into ONE opaque ⟦…:URL⟧ token, so the bearer-secret query value is dropped
        # here by construction; there is no partial-URL cleartext to strip (E7.2).
        # The dedicated :func:`_strip_url_query_secrets` helper is the guard for a
        # FUTURE change that would emit part of a URL in cleartext; it is exercised
        # directly by ``test_url_query_secret_stripped`` (calling it here and
        # discarding the result would be a wasted regex pass on every URL).
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
        # A path/URI-shaped candidate ("s3://bucket/reports/q3/financials",
        # "/var/log/app/output") contains '/' but is NOT a secret — over-masking it to
        # ⟦…:SECRET⟧ destroys the param signal the PDP needs for Cedar param-bounds /
        # sequence checks on the financial-action beachhead (R2-M2, over-mask not a
        # leak, but it degrades enforcement). A path is distinguished from a
        # slash-bearing base64 secret structurally: split on '/', and if NO single
        # segment independently qualifies as a secret (mixed high-entropy or long
        # hex), it is a path → pass through. A real base64 secret with a slash still
        # has a qualifying segment, so this never lets a genuine secret leak.
        if "/" in cand and not any(
            _segment_is_secretish(seg) for seg in cand.split("/") if seg
        ):
            return cand
        # Require mixed charset (upper+lower+digit) OR very high entropy so a long
        # lowercase English word isn't masked as a secret.
        if not _segment_is_secretish(cand):
            return cand
        return _wire_token(nonce, "SECRET")

    return _SECRET_CANDIDATE.sub(repl, text)


def _segment_is_secretish(cand: str) -> bool:
    """Does ``cand`` look like secret material on its own (charset + entropy)?

    The shared gate for :func:`_redact_secret`: a candidate (or a single ``/``-
    delimited segment of one) is secret-shaped when it is long enough AND either has
    a mixed upper+lower+digit charset over the entropy floor, or is very high entropy,
    or is a long pure-hex run. Used both to decide a whole candidate and to keep a
    filesystem/URI path (no secret-shaped segment) from being over-masked (R2-M2).
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
    return mixed or entropy >= 4.0


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
        return {_walk_key(k, nonce): _walk(v, nonce) for k, v in obj.items()}
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
