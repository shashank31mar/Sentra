# ws-e1-tier1-redactor — Tier-1 edge deterministic redactor (stdlib-only SDK)

**Scope of**: [../ws-e-redaction.md](../ws-e-redaction.md) Milestone E1 + E6.1 + E7.2 + tests E8.1/E8.2 (Tier-1 only) · **LLD**: [../../../lld/29-redaction.md](../../../lld/29-redaction.md) §3
**Domain**: backend (Python, stdlib) · **Package**: `demo-agents/sdk/aegion-guard-python/`

## Purpose

Today the SDK egresses `tool_params` + `user_input` + (post-WS-B) `content_text` **un-redacted** ([guard.py:461-489](../../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L461)). This workstream builds the deterministic Tier-1 redactor (`redaction.py`, stdlib-only) and runs it on **every** egressing phase inside WS-B's `_build_request`, before `_send`, fail-secure. It masks structured PII/PCI into typed tokens via a frozen ordered matcher set. Tier-1 correctness is deterministic (not WS-0-recall-gated) — this is the safest WS-E slice to build ahead of the spike gate.

**Contracts this workstream OWNS (join keys):** `redact(value, *, nonce) -> str` · the typed-token grammar `⟦AEGR:{nonce}:TYPE[:meta]⟧` · `redaction_nonce` (additive payload field) · `redacted=True` provenance flag (payload-level) · the frozen `_ORDERED_MATCHERS` + token type set.

---

## 🔴 ROUND-5 MUST-FIX — normalize-then-detect landed (separator class CLOSED, 0 raw leaks); 1 real correctness gap remains

> **Good news:** the Round-4 normalize-then-detect rewrite (commit `9b8d361`) **closed the entire separator-leak class** — all 8 prior leak variants (2/3-space, dot, slash, multi-stray PAN; SAD+PAN; tab/slash SSN) now mask, verified on the branch, suite green, **zero raw-PII leaks this round.** The findings below are NOT leaks; fix them and Tier-1 is done.

### R5-M1 (MEDIUM, real — verified) — PII-keyed dict collapses, silently dropping params
- **File:** `redaction.py` `redact_params`/`_walk`/`_walk_key` (~:1088–1155).
- **Repro (verified):** `redact_params({"alice@corp.com":"x","bob@corp.com":"y","carol@corp.com":"z"}, nonce=n)` → **1 entry out of 3** — the 3 email keys all redact to the identical meta-less `⟦…:EMAIL⟧` token, so the dict comprehension `{_walk_key(k): _walk(v)}` collapses N colliding keys to one. N-1 params are **silently lost** → the PDP evaluates an incomplete param set and can **wrong-ALLOW** an action whose risky value sat under a dropped key.
- **Fix:** detect key collisions after redacting keys and disambiguate so **no dict entry is ever dropped** (e.g. suffix an ordinal/index into the colliding key's token meta, or key by original-index). **Invariant: `len(redact_params(d)) == len(d)` always.** Add a test with ≥2 distinct email keys AND two distinct valid PANs sharing first6:last4, asserting no entry is lost.

### R5-L1 (LOW) — `content_text` redacted twice on egressing phases
- **File:** `guard.py:529` — `content_text = _redaction.redact(resolved_input, nonce=nonce)` re-runs the full matcher chain on the same input already computed as `redacted_input` (`:488`, same input+nonce → byte-identical). Reuse `payload["content_text"] = redacted_input` (saves a full matcher pass on the hot path). Add a test pinning `content_text == user_input` for a content-phase payload.

### R5-L2 (LOW, not a leak — documented seam) — `content_text` sourced from session `user_input`, not the decorated fn's argument
- **File:** `guard.py:524-529`. For content/output/memory phases, `content_text` comes from the session `user_input`, not the actual function argument the phase governs. The function's args still egress via redacted `tool_params`, so **NOT a raw-PII leak** — but `content_text` may carry the wrong/empty content vs. what the phase intends. This is a WS-B/WS-L ownership seam (comment at :524-528). **Action: confirm with a test that a `@guard.content` fn whose content is a distinct ARGUMENT still gets that argument redacted+carried, OR document the seam as WS-L's to close** (don't silently leave it unverified).

---

## 🟢 ROUND-4 — ARCHITECTURAL REWRITE: normalize-then-detect (drives out the whole separator-leak class)

> **Root cause of R2/R3/R4 leaks:** the matchers detect structured PII *in place*, with separators baked into the regex (`_PAN_SEP{0,2}`, dash-only SSN). Every separator/count not enumerated = a raw leak (we hit 2-space→3-space→tab→slash — whack-a-mole). **This round replaces the whack-a-mole with the normalize-then-detect architecture** specified — with cited, adversarially-verified formats+checksums — in **[../../../lld/29a-redaction-format-spec.md](../../../lld/29a-redaction-format-spec.md)** (LLD 29a, the buildable companion to LLD 29 §3).
>
> **Build to LLD 29a. Non-negotiable specifics from it:**
> - **§1 normalize-then-detect:** within a **bounded window**, strip ALL non-alphanumeric separators → run the checksum/format check on the clean run → map the span back over the ORIGINAL text (separators included). One normalization pass handles any separator (spaces/tabs/slashes/dots/dashes/mixed) — do NOT enumerate separators in the regex anymore. Over-join risk is mitigated by the length-capped window + the checksum being the real filter; shape-only matchers (SSN, no checksum) additionally require a **label anchor**.
> - **§2 PAN:** 8–19 digits, **Luhn** + a valid **IIN prefix** (per-brand table, all CONFIRMED in §2.1), mask to `<CARD:6:4>` (first6/last4, middle NEVER emitted). Closes R3-C1 (multi-group) and R2/R4 (3-space/tab/slash) by construction.
> - **§2.3 SAD:** CVV label-anchored, Track 1/2 sentinel-anchored, PIN-block ISO-9564 nibble check → `<SAD>` dropped, no value. Closes R3-H1 (redact BOTH the SAD value AND an adjacent card).
> - **§3 checksums (stdlib-only, ~15 lines each — NO dependency):** US SSN validity rules (area≠000/666/900-999, group≠00, serial≠0000; no checksum → label-anchored). **⚠️ If Aadhaar (P1) is built, use the CORRECTED Verhoeff table `p[6]=2793806415` (§5.3) — the raw-research value was wrong; the verify pass caught it.**
> - **§3.1 NAME COLLISION:** India tax "PAN" (`AAAAA9999A`) is NOT a payment card — separate matcher, separate token, **never run Luhn on it**.
> - **§4 corpus:** add the leaked variants as HARD 0-miss rows — **3-space PAN, tab PAN, slash PAN, tab SSN, slash SSN** — plus over-join negative controls. A fix without its corpus row is not done.
> - **§5 scope:** P0 = payment PAN + SAD + US SSN + the existing stdlib HIPAA structured matchers (email/phone/IP/URL/date/MRN/secret). Intl IDs = P1 behind a region flag.
>
> The R2/R3 sections below are the leak history this rewrite subsumes — keep every one as a regression corpus row (all must still pass). **R4-C1 (3+ separator PAN) and R4-M1 (tab/slash SSN), both reproduced on the branch, are closed by the §1 normalization — not separate patches.**

---

## 🔴 ROUND-3 MUST-FIX — multi-group PAN/SAD leaks found by integration-sentinel (2026-07-01), reproduced on the branch

> The rebuild is green + reconciled to WS-B, but integration-sentinel read the code and found **2 more PCI fail-open classes the corpus does not cover** — both reproduced by running `redact()` on branch `codeloop/ws-e1-tier1-redactor`. Same rule: **each fix MUST add its leaking input as a row to `pci_sad_pan.jsonl`** (the zero-miss gate) so it's covered forever. These live in the reused redactor's PAN/SAD windowing logic — NOT in the WS-B reconciliation (that's clean).

### R3-C1 (CRITICAL) — multi-stray-digit-group PAN slides past the 19-digit window and egresses RAW
- **File:** `redaction.py` — `_PAN_CANDIDATE` (~:242) caps the captured digit-run at 19 digits; `_best_pan_window` only trims WHOLE groups from the candidate it was handed, so it can't recover a card that never fully fit the window.
- **Repro (verified):** `redact("ref 12 34 4111 1111 1111 1111")` → **unchanged** — the two 2-digit strays + 16-digit card = 20 digits; the window slid to include the strays and excluded the card's trailing group. Full Visa PAN `4111111111111111` egresses raw. Variant `redact("cvv 123 456 4111 1111 1111 1111")` → `123 456 4111` mis-tokenized as `<PHONE>`, stranding 12 raw card digits behind a marker that falsely looks redacted (E1.4 no-partial-PAN violated) AND the CVV survives raw.
- **Fix:** the PAN scan must find a Luhn-valid 13–19-digit card window **anywhere inside a longer digit-group run**, not just within a ≤19-digit capture. Widen the candidate to capture the full multi-group run, then have `_best_pan_window` slide a 13–19-digit window across ALL sub-runs (not just whole-group trims of a fixed candidate). Add corpus rows: `ref 12 34 <PAN>`, `cvv 123 456 <PAN>`, and a 3-stray-group case.

### R3-H1 (HIGH) — SAD value immediately before a separated PAN: the CVV/PIN egresses RAW
- **File:** `redaction.py` — `_redact_sad` (~:367) DECLINES (steps aside for `_redact_pan`) whenever the run starting at the SAD value contains a Luhn-valid PAN. So `redact("cvv 999 4111 1111 1111 1111")` → the card masks to `<CARD:6:4>` but the CVV `999` is dropped as "over-captured non-card text" and **egresses raw** — SAD never-store violated.
- **Fix:** when a SAD value is adjacent to a trailing separated PAN in one run, redact **BOTH** — drop the SAD value to a no-meta `<SAD>` AND tokenize the trailing card. The SAD guard must not trade a real SAD redaction for the card redaction. Add a corpus row: `cvv 999 <PAN>` asserting both `<SAD>` (no `999`) and `<CARD:6:4>`.

**Note:** R2 leaks (separated-PAN, SAD+dot-PAN, hex-secret, IPv6) were already fixed in the reused branch — these R3 findings are a distinct multi-group-windowing class the earlier rounds didn't reach. Also 2 non-blocking residuals from review: a MEDIUM slash-dense secret passthrough (`redaction.py:579`) and a LOW dead `_strip_url_query_secrets` helper (`redaction.py:371`) — fix or delete alongside.

---

## 🔴 ROUND-2 MUST-FIX — real leaks found by adversarial verification (2026-07-01), reproduced on the branch

> The round-1 build is green (225 passed) but an independent PCI adversary lens found **3 raw-value leaks the zero-miss corpus does not cover** — all reproduced by running `redact()` on the branch. These are the exact NFR-7(a) fail-open class E1 exists to close. **Each fix MUST add the leaking input as a row to the `pci_sad_pan.jsonl` zero-miss gate (or the matcher UT), so the gate covers it going forward** — a fix without a corpus/test row is not done.

### R2-C1 (CRITICAL) — dot/slash/comma/underscore-separated PAN egresses RAW
- **File:** `redaction.py` — `_PAN_CANDIDATE` (~:169) `(\d[ -]?){12,18}\d` accepts only space/hyphen.
- **Repro (verified):** `redact("4111.1111.1111.1111")` → unchanged (raw). Same for `/`, `,`, `_`. Space and hyphen mask correctly.
- **Fix:** widen the inter-group separator set to include `. / , _`; update `_best_pan_window` group-split + `_SAD_VALUE_PAN_RUN` to match. Add a `pci_sad_pan.jsonl` row per separator.

### R2-C2 (CRITICAL) — SAD label + dot-separated PAN → partial-redacted PAN (12 raw digits, looks redacted)
- **File:** `redaction.py` — the SAD footgun guard `_SAD_VALUE_PAN_RUN` (~:281) spans only digits/space/hyphen.
- **Repro (verified):** `redact("pin is 4111.1111.1111.1111")` → `pin: ⟦AEGR:…:SAD⟧.1111.1111.1111` — SAD eats the leading group `4111`, the trailing 12 card digits egress raw, and the output falsely looks redacted (worse than a plain miss; violates E1.4 no-partial-PAN).
- **Fix:** extend `_SAD_VALUE_PAN_RUN` to the same separators as `_PAN_CANDIDATE` so the SAD guard declines when its value is a card's leading group. Add a corpus/test row for label+dot-PAN.

### R2-H1 (HIGH) — lowercase-hex credential egresses RAW (entropy dead-zone)
- **File:** `redaction.py` — `_redact_secret` / `SecretMatcher` (~:472).
- **Repro (verified):** `redact("apikey=da39a3ee5e6b4b0d3255bfef95601890afd80709")` → unchanged. 40-char, entropy 3.737 — clears the ≥3.5 floor but fails BOTH the mixed-charset gate (needs upper+lower+digit) AND the ≥4.0 fallback. Generalizes to SHA1/SHA256 hex session tokens, HMAC sigs, hex API keys. (A 64-char hex token DOES mask — only the mid-length dead-zone leaks.)
- **Fix:** treat a long (16+) all-lowercase-hex run (`^[0-9a-f]+$`) as a secret regardless of the mixed/entropy gate (OR lower the non-mixed fallback to ~3.7 for hex-charset candidates). Add a test asserting a 40- and 64-char hex token → `<SECRET>`.

### R2-M1 (MEDIUM) — space/dot-separated SSN egresses raw
- `redact("SSN: 123 45 6789")` and `"SSN: 123.45.6789"` → unchanged; `_SSN` is dash-only. Dash form masks correctly. Fix alongside R2-C1's separator widening; add UT rows.

### R2-M2 (MEDIUM, quality not leak — fail-SECURE) — SECRET over-redacts file paths / s3:// URIs
- The SECRET charset includes `/`, so a plain `file_path`/`s3_uri` param gets masked to `<SECRET>` — destroys the param signal the PDP needs for Cedar param-bounds/sequence checks on the **financial-action beachhead** params. Over-masking (never a leak). Fix: exclude path/URI-shaped low-entropy runs from SECRET; add a test asserting a plain path/s3-uri passes through.

**Non-vacuity note:** the round-1 zero-miss corpus provably exercises only contiguous/space/hyphen PAN separators and no lowercase-hex secret — so "a green test already covers it" does NOT apply to C1/C2/H1. Every R2 fix ships with its covering row.

---

## Real touch-points (verified 2026-07-01)

- **NEW** `demo-agents/sdk/aegion-guard-python/src/aegion_guard/redaction.py` — the redactor module (stdlib-only).
- [guard.py:412-491](../../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L412) — `_build_request` (**WS-B rebuilt this**; takes `phase: str = "request"` param). `payload` dict built at [:461-479](../../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L461); `safe_params` at [:460](../../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L460). **WS-B already emits `phase` + `content_text` at [:484-489](../../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L484) for non-`request` phases** — the comment there explicitly says *"WS-E (lld/29 §3.5) redacts this field before _send"*. **Redaction hooks in after `safe_params`/after WS-B places `content_text`, before `return payload`.**
- [guard.py:493+](../../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L493) — `_send` + the existing fail-secure `Decision(decision="DENY", reason="validation_unavailable")` pattern to mirror for `redaction_failed`.
- **DO NOT touch `RequestContext` for phase.** WS-B flows `phase` through `_build_request` as a **parameter** (set by the `@guard.tool/content/output/memory` decorators via `_phase_decorator` at [guard.py:270](../../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L270)), **NOT** via `RequestContext` (the WS-B comment at [:279](../../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L279) is explicit). Read `phase` from the `_build_request` parameter — my old plan to add `RequestContext.phase` was the reverted divergence.
- [config.py](../../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/config.py) — `fail_secure` default lives here; align the redaction fail-secure path with it.
- [pyproject.toml:26](../../../demo-agents/sdk/aegion-guard-python/pyproject.toml#L26) — `dependencies = []` (runtime). **Must stay `[]`.**
- **NEW** `demo-agents/sdk/aegion-guard-python/tests/test_redaction.py` — the Tier-1 unit suite (E8.1).
- **NEW** `demo-agents/sdk/aegion-guard-python/tests/corpus/pci_sad_pan.jsonl` + `tests/test_pci_deterministic.py` — the release-blocking hard PCI 0-miss test (E8.2). *(Placed in the SDK tests, not `src/security-controller/tests/`, because the redactor under test is SDK-local at this stage.)*

---

## Milestone E1 — the Tier-1 redactor + wiring

### E1.1 — the deterministic matcher set + the frozen ORDER
- **File (new):** `src/aegion_guard/redaction.py` — **stdlib-only** (`re`, `math`, `unicodedata`, `secrets`). No runtime dep added to `pyproject.toml`.
- **Change:** implement each matcher `(detector → typed-token)` per LLD §3.2 and freeze the order in a module constant:
  ```python
  # redaction.py (NEW, stdlib-only) — order is a security control (§3.2).
  _ORDERED_MATCHERS = (
      SADMatcher(),        # most-specific/highest-harm: DROP entirely (PCI never-store) → <SAD>, no meta
      PANMatcher(),        # regex candidate → Luhn mod-10 → <CARD:6:4> (first6/last4 only) — MUST precede any bare-numeric matcher
      SSNMatcher(), MRNMatcher(), AccountMatcher(), LicenseMatcher(), DeviceMatcher(),  # format-anchored (label-adjacent+shape)
      EmailMatcher(), PhoneMatcher(), IPMatcher(), URLMatcher(), DateMatcher(),
      SecretMatcher(),     # Shannon-entropy fallback LAST — broadest, lowest precedence → <SECRET>
  )
  ```
  Token types (LLD §17 canonical set): `CARD:6:4`, `SAD`, `SSN`, `EMAIL`, `PHONE`, `IP`, `URL`, `MRN`, `ACCT`, `LICENSE`, `DEVICE`, `DATE`, `SECRET`.
- **Implements:** LLD §3.2.
- **FOOTGUN:** `<CARD:6:4>` carries first6/last4 **only** (never the middle digits); `<SAD>` carries **NO** meta. Never emit a full PAN even tokenized. Format-anchored IDs (SSN/MRN/account/license/device) are label-adjacent + shape, not pure shape — don't over-scrub bare numbers.

### E1.2 — Shannon-entropy floor for `<SECRET>`
- **File:** `redaction.py` (`SecretMatcher`).
- **Change:** Shannon entropy over the candidate token's charset; a tuned floor (~≥3.5 bits/char over a 32+ char base62/hex string) + min-length that catches API keys/tokens while **NOT** scrubbing a legitimate low-entropy UUID or order number. The floor is a module constant; set conservatively — favor a false-negative on a benign ID over destroying a legitimate value.
- **Implements:** LLD §3.4.

### E1.3 — typed-token grammar: reserved sentinel + per-call nonce + neutralize planted tokens (M-4)
- **File:** `redaction.py`.
- **Change:** implement the wire grammar `⟦AEGR:{nonce}:TYPE[:meta]⟧` and `_neutralize_planted_tokens`; the shared contract is `redact(value, *, nonce) -> str`:
  ```python
  def redact(value: str, *, nonce: str) -> str:
      escaped = _neutralize_planted_tokens(value)        # M-4: attacker can't forge a marker
      for matcher in _ORDERED_MATCHERS:                  # §3.2, highest-harm first
          escaped = matcher.sub_token(escaped, nonce=nonce)  # value → ⟦AEGR:{nonce}:TYPE[:meta]⟧
      return escaped
  ```
  The `{nonce}` is a per-call `secrets.token_hex(8)` bound to this single egress; downstream, only `⟦AEGR:{nonce}:…⟧` (with the call's nonce) is a genuine marker.
- **Implements:** LLD §3.3, M-4.
- **FOOTGUN:** do NOT use a bare `<CARD>`. The HLD's `<CARD>` illustration is descriptive UI rendering, not the wire grammar. A bare token any input can spoof re-opens M-4. `_neutralize_planted_tokens` must handle BOTH a planted `⟦AEGR:…⟧` (any nonce, including a guessed/replayed one) AND a bare `<CARD>`-style string — neither may survive as a readable marker.

### E1.4 — run on EVERY egressing phase (the live bug), in `_build_request` — RECONCILED to WS-B
- **File:** [guard.py:412-491](../../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L412) (`_build_request`, WS-B version) — after `safe_params` ([:460](../../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L460)) and after WS-B's `phase`/`content_text` block ([:484-489](../../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L484)), before `return payload`.
- **Change:** WS-B already threads `phase` (a `_build_request` **parameter**, default `"request"`) and, for non-`request` phases, places `payload["content_text"] = resolved_input` at [:489](../../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L489). Redact each content-bearing field WS-B produced, **consuming WS-B's `KNOWN_PHASES`/`_CONTENT_FIELD` from `models.py` mirrored SDK-side** (do NOT invent a second spelling):
  ```python
  nonce = secrets.token_hex(8)                          # per-call; binds genuine markers (§3.3)
  # `phase` is the _build_request PARAMETER (set by @guard.tool/content/output/memory), NOT RequestContext.
  payload["tool_params"] = redact_fields(safe_params, nonce=nonce)  # redact each string value in the dict
  payload["user_input"]  = redact(resolved_input, nonce=nonce)
  # WS-B placed the egressing content in the SINGLE `content_text` field (disambiguated by phase,
  # per WS-B's _CONTENT_FIELD = {content|output|memory -> "content_text"}). Redact it if present:
  if payload.get("content_text") is not None:           # i.e. phase in content/output/memory
      payload["content_text"] = redact(payload["content_text"], nonce=nonce)
  payload["redaction_nonce"] = nonce                    # PDP uses it to recognize genuine markers
  payload["redacted"] = True                            # provenance flag (WS-B left a redaction-boundary tripwire in models.py)
  ```
  Provide `redact_fields(mapping, *, nonce)` (redact each string value, recursing into nested dicts/lists) in `redaction.py`. **Consume WS-B's canonical `content_text` field name — there is ONE content field, disambiguated by `phase`; do NOT add per-phase `content`/`output`/`memory` fields (that was the reverted divergence).**
- **Implements:** LLD §3.5 (consuming WS-B's LLD 30 §2.3 `_CONTENT_FIELD` contract).
- **FOOTGUN 1:** do NOT redact only the `request` branch. `content` (retrieved docs, tool output, web text — carried in `content_text`) is often the **richest** PII surface — leaving it raw is the live NOT-DONE bug. The §15.1 test drives a `content`-phase call and asserts the typed token in `content_text`, not the raw value.
- **FOOTGUN 2 (the reverted divergence — do not repeat):** phase comes from the `_build_request` **parameter** WS-B added, NOT a new `RequestContext.phase`. Use `KNOWN_PHASES`/`content_text` (WS-B's canonical names), never `_VALID_PHASES`/per-phase fields.

### E1.5 — fail-secure on redactor error
- **File:** the redaction call site in `_build_request` (or the caller `_avalidate_or_raise`/`_send` path); mirror the existing DENY pattern in `_send`'s `TransportError` branch ([guard.py:493+](../../../demo-agents/sdk/aegion-guard-python/src/aegion_guard/guard.py#L493), WS-B version) and the `config.fail_secure` default.
- **Change:** if `redact()` / `redact_fields()` raises on any field, short-circuit to a **DENY** `Decision` (reason `redaction_failed`) — **never** `_send` the raw payload. Because `_build_request` is called from `avalidate`/`_avalidate_or_raise` before `_send`, the cleanest shape is: catch the redaction error at the boundary that owns the `Decision` return and produce the DENY there (do NOT let a raw payload reach `_send`). Fire the existing decision hook, consistent with the `validation_unavailable` path.
- **Implements:** LLD §3.8, invariant #2 (clause-a).
- **FOOTGUN:** a redactor exception falling through to `_send` with raw is the clause-(a) breach. Fail to DENY, never to "send unredacted."

### E6.1 — edge tags binary/image fields, never redacts pixels
- **File:** `redaction.py` + `_build_request`.
- **Change:** a field detected as binary/image at the edge (non-text bytes, or a base64 blob over a size+entropy threshold) is **tagged** (e.g. replaced with a `⟦AEGR:{nonce}:IMAGE⟧` marker + a side flag so the server routes it to Tier-2) — the edge **never** attempts pixel redaction and **never** sends the raw blob when policy would `block`. The server-side mode router (`evaluate|redact|block`) is a later stage; here the edge only *detects + tags + refuses-raw-on-block-intent*, it does not resolve the mode.
- **Implements:** LLD §3.6, E2. *(Server-side E6.2/E6.3 are OUT of this stage.)*

### E7.2 — Tier-1 URL query-secret strip (supplement)
- **File:** `redaction.py` (a URL-query matcher, coordinating with `SecretMatcher`).
- **Change:** scrub `?token=…` / `?api_key=…` / `?access_token=…`-style secrets in a URL's query component before egress, emitting `<URL>` (as the typed token grammar) with the secret-bearing query masked. Supplement to the (later, server-side) FR-2.9 destination allow-list — not a replacement, and NOT a parallel URL-validation subsystem.
- **Implements:** LLD §3.7 (2).

---

## Milestone E8 (Tier-1 subset) — tests

### E8.1 — Tier-1 unit tests
- **File (new):** `tests/test_redaction.py` (`asyncio_mode=auto`, `testpaths=tests`).
- **Change (LLD §15.1) — cover ALL of:**
  - **per-matcher:** PAN Luhn-valid → `<CARD:6:4>` with middle digits gone; a Luhn-**fail** 16-digit string is **NOT** carded; SAD (CVV/track/PIN, label-anchored) → `<SAD>` with no value; each of SSN / email / phone / IP / URL / MRN / account / license / device / date → its typed token; a high-entropy 32+ char key → `<SECRET>`; a low-entropy UUID / order-number is **NOT** scrubbed.
  - **ordering:** a PAN resolves to `<CARD:6:4>`, not a bare `<NUMBER>`/`<SECRET>` (proves SAD→PAN precede the generic matchers).
  - **grammar / namespacing (M-4):** plant a `⟦AEGR:<guessed-nonce>:CARD:6:4⟧` and a bare `<CARD>` in the input → after `redact()`, neither reads as a genuine marker (both neutralized); a genuine token uses the call's real nonce.
  - **per-phase:** PII in a `content`/`output`/`memory`-phase call → typed token in the built payload's `content_text` field, not the raw value (drive through `@guard.content`/`_build_request(phase="content")` — WS-B's decorator surface — asserting `content_text` is redacted; and a `request`-phase call redacts `tool_params`/`user_input`).
  - **fail-secure:** force `redact()` to raise (monkeypatch a matcher) → the guard returns DENY `redaction_failed`; assert `_send`/the transport is **never** called with a raw payload.
  - **image mode (edge):** an image/binary field is tagged + routed (never pixel-redacted); on block-intent the raw blob is not sent.
  - **stdlib-only guard:** `import aegion_guard.redaction` succeeds with no third-party import; assert the packaged runtime `dependencies == []` (read `pyproject.toml`) — a runtime dep added here fails the test.
- **Implements:** LLD §15.1.

### E8.2 — the HARD PCI SAD/PAN 0-miss deterministic test (release-blocking, SEPARATE)
- **File (new):** `tests/corpus/pci_sad_pan.jsonl` + `tests/test_pci_deterministic.py`.
- **Change (LLD §15.4):** the corpus covers Luhn-valid PANs (canonical, spaced `4111 1111 1111 1111`, dashed `4111-1111-1111-1111`, embedded in prose) + label-anchored SAD (CVV/track/PIN). Target = **hard 0-miss**: every Luhn-valid PAN emits `<CARD:6:4>` (middle gone, no full PAN anywhere in output); every SAD is dropped to `<SAD>` (no value leaks). A **single** miss fails the test. Held apart from any fuzzy recall corpus.
- **Implements:** LLD §15.4, §15.5 (separate PCI gate), invariant #5.
- **FOOTGUN:** never average this into a WS-0-gated fuzzy number — it is an independent, always-on, deterministic 0-miss gate.

---

## Acceptance checklist (this scoped stage)

- [ ] `redaction.py` exists in the SDK, **stdlib-only**; `pyproject.toml` runtime `dependencies == []` unchanged (asserted by a test).
- [ ] The frozen `_ORDERED_MATCHERS` masks PAN(first6/last4) / SAD(drop) / SSN / email / phone / IP / URL / MRN-account-license-device / dates / high-entropy-secrets into typed tokens, highest-harm first.
- [ ] `redact(value, *, nonce) -> str` + `redact_fields(mapping, *, nonce)` implement the `⟦AEGR:{nonce}:TYPE[:meta]⟧` grammar; `_neutralize_planted_tokens` defeats a planted `⟦AEGR:…⟧` and a bare `<CARD>` (M-4).
- [ ] `<CARD:6:4>` carries first6/last4 only (middle gone); `<SAD>` carries no value; no full PAN ever emitted.
- [ ] Redaction runs on **every egressing phase** in `_build_request` before `_send`; `redaction_nonce` + `redacted=True` on the payload; a `content`-phase test asserts the typed token in `content_text`, not raw.
- [ ] Redactor fails **secure** — an exception → DENY (`redaction_failed`); `_send` is never called with a raw payload.
- [ ] Edge tags image/binary fields (never pixel-redacts, never sends raw on block-intent); URL query-secret strip works.
- [ ] Consumes WS-B's landed `phase` contract (`KNOWN_PHASES`, `content_text`, `_CONTENT_FIELD`, the `_build_request(phase=...)` parameter, the `@guard.tool/content/output/memory` decorators) — **NO** new `RequestContext.phase`, **NO** `_VALID_PHASES`, **NO** per-phase content fields (the reverted divergence).
- [ ] **E8.1** Tier-1 unit suite passes (matchers + grammar + per-phase + fail-secure + image-mode + stdlib guard); the M-4 and fail-secure tests FAIL if the control is reverted (non-vacuous).
- [ ] **E8.2** the HARD PCI SAD/PAN 0-miss test passes (release-blocking, separate).

## OUT of this stage
**E1.0 server-side `phase` — DONE by WS-B** (KNOWN_PHASES/content_text/422-routing/decorators are on main; this stage CONSUMES them, does not build them). E2 (`phi-ner` container/CDK), E3/E4/E5 (server barrier / no-raw audit / feedback store), E6.2/E6.3 (server mode router + Cedar `image_mode`), E7.1 (FR-2.9 egress policy), E8.3–E8.7 (server no-raw test, feedback tests, fuzzy recall harness [WS-0-gated], LIVE e2e [needs prod infra], metrics), and all release-gate items. See [00-index.md](00-index.md).