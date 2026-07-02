# LLD 29a: Tier-1 Redaction Format Spec — normalize-then-detect matchers, per-identifier rules, corpus (WS-E)

**Version**: 1.0
**Last Updated**: 2026-07-02
**Status**: Draft — drives the `aegion_guard/redaction.py` code rewrite
**Parent**: [29-redaction.md](29-redaction.md) (this is the buildable matcher/format detail for LLD 29 §3.2–§3.4, §15.4). It does **not** re-open ADR-032 or the two-tier split; it pins the *detector* implementation and the corpus.

**Scope**: the **stdlib-only Tier-1 edge redactor** — the deterministic matcher set, how each identifier is detected/validated, the separator-tolerant normalization architecture, and the corpus rows. Tier-2 semantic NER (names/prose PHI) is out of scope here (LLD 29 §4). Every format claim below carries an inline citation. Anything the verify pass could not confirm is marked **UNVERIFIED**.

> **Constraint (frozen, LLD 29 §3.1):** `re`, `math`, `unicodedata`, `secrets` only — no runtime dependency added to `pyproject.toml` (`dependencies = []`). Verhoeff, Luhn, mod-11, mod-97, mod-23 are all pure-arithmetic and implementable in ~10–20 lines each with **zero** dependencies (§5). A checksum being "hard" is never a reason to add a lib.

---

## 1. The core architectural fix — normalize-then-detect

### In plain terms
Today's bug class is *whack-a-mole on separators*. A PAN can be written `4111 1111 1111 1111`, `4111  1111...` (two spaces), `4111   1111...` (three), `4111-1111-...`, `4111\t1111...`, or pasted from a spreadsheet column with a slash or mixed whitespace. An in-place regex like `\d{4}[ -]\d{4}[ -]\d{4}[ -]\d{4}` matches the shapes you thought of and **leaks the one you didn't**. We hit exactly this: patched 1-space, a 2-space PAN leaked; patched that, a tab leaked; patched that, a slash-delimited SSN leaked. Every patch is one more `[ -]` in a character class, and the next weird separator is a new breach.

**The fix kills the whole class instead of playing the next round of the game:** within a bounded window, **strip every non-alphanumeric character, run the checksum/format check on the normalized digit/char run, and map the match back to the original span** (including the separators it spanned) for replacement. The detector never sees separators, so no separator can defeat it.

### 1.1 The three-step pipeline (per matcher)

```
raw field  ──▶ (a) WINDOW      ──▶ (b) NORMALIZE      ──▶ (c) VALIDATE       ──▶ map span back
              a bounded run of      strip all              run the checksum/       replace the ORIGINAL
              digits/word-chars     non-alphanumerics      structural rule on      span (separators
              + adjacent seps       inside the window      the clean run           included) with the token
```

- **(a) Window** — a matcher first finds a *candidate window*: a bounded run of `[A-Za-z0-9]` and interior separator characters, within the identifier's max length (e.g. a PAN window is ≤ 19 alnum + up to ~6 interior separators; an SSN window is ≤ 9 alnum + up to 2 separators). The window bound is the over-join guard (§1.2). Anchoring uses a *shape* pattern that already tolerates arbitrary interior separators, e.g. `(?:\d[ \t\-.\/]*){13,19}` for a PAN candidate, `(?:\d[ \t\-.\/]*){9}` for SSN.
- **(b) Normalize** — inside the window, `re.sub(r'[^A-Za-z0-9]', '', window)` → the bare run (`4111111111111111`). Keep an index map (offset in normalized run → offset in original) so step (c)'s accept lets us recover the original start/end including separators.
- **(c) Validate** — run the identifier's checksum + structural rule (Luhn, mod-11, Verhoeff, prefix table, …) on the bare run. **Only a validated run is redacted.** A window that fails the check is left untouched (it is not that identifier).

### 1.2 The over-join risk + its mitigation (why this is safe, not greedy)

Stripping separators risks **over-joining**: `4111 1111 1111 1111 2222` (a PAN followed by an unrelated 4-digit number) could normalize into a 20-digit run, or two adjacent SSNs could fuse. Two bounded controls make normalize-then-detect *safer* than the whack-a-mole regex, not looser:

1. **Bounded window.** The window is length-capped at the identifier's max (PAN ≤19 digits, SSN =9, Aadhaar =12, …). A run longer than the cap is *slid*, not swallowed whole — the matcher tries valid-length sub-runs (e.g. for a PAN it tries the leading 13/14/15/16/19-digit prefixes/anchored substrings) and accepts the first that passes the checksum. It never emits a token over a run that exceeds the max length.
2. **Checksum/format gate is the real filter.** Because acceptance requires the *checksum* (Luhn/mod-11/Verhoeff/mod-97) or a strict positional format (SSN area/group/serial rules), a spuriously-joined run overwhelmingly **fails the check** and is left alone. Luhn on a random 16-run passes ~10% of the time; requiring a *known IIN prefix* as well drops false-joins far lower. The over-join that would matter (two real PANs fusing into a checksum-valid 32-run) is impossible because 32 > the 19 cap.

> **Rule:** a matcher with **no** checksum and only a weak shape (bare 9-digit → SSN) MUST additionally require a **label anchor** or the strict positional rule (§3, SSN row) before it strips-and-accepts, precisely because it lacks a checksum to filter over-joins. High-harm + checksummed matchers (PAN, Aadhaar, IBAN) may rely on the checksum; shape-only matchers may not.

### 1.3 Concrete: the PAN matcher, end to end

```python
# redaction.py (NEW, stdlib-only). Illustrative — not production code (LLD rules).
_SEP = r'[ \t\-. /]*'                       # space, tab, dash, dot, NBSP, slash — the seps we saw leak
_PAN_WINDOW = re.compile(r'(?<![0-9])(?:\d' + _SEP + r'){12,19}\d')  # 13..19 digits w/ interior seps

def _pan_sub(text: str, *, nonce: str) -> str:
    def repl(m: re.Match) -> str:
        window = m.group(0)
        digits = re.sub(r'\D', '', window)        # NORMALIZE: strip every separator
        for n in (16, 15, 19, 14, 13):            # try each valid PAN length, longest-common first
            if len(digits) >= n:
                cand = digits[:n]
                if _luhn_ok(cand) and _iin_brand(cand):   # VALIDATE: Luhn + assigned IIN
                    return _token(nonce, "CARD", meta=f"{cand[:6]}:{cand[-4:]}")  # map back over full span
        return window                              # failed → leave raw untouched (it isn't a PAN)
    return _PAN_WINDOW.sub(repl, text)
```

The same `window → strip → checksum → token-or-leave` shape is reused by every checksummed matcher (SSN uses positional rules instead of Luhn). **No matcher builds its own separator character-class beyond `_SEP`, and `_SEP` is defined once** — the fix is architectural, not per-identifier.

---

## 2. Payment-card PAN + SAD

### In plain terms
A card number is 8–19 digits [1] with a trailing **Luhn** check digit that *every* major brand uses [4]. The brand (Visa/MC/Amex/…) is decided by the leading digits (the IIN/BIN). A card security code (CVV/CVC/CID), the magnetic-stripe tracks, and PINs are **SAD** (Sensitive Authentication Data) — they must never be stored after authorization [PCI glossary]. So Tier-1 masks a PAN to first-6/last-4 and **drops** SAD entirely.

### 2.1 The authoritative PAN rule

- **Length:** 8–19 digits (ISO/IEC 7812-1); 16 is most common, Amex is 15, some run 13/18/19 [1][3].
- **Checksum — Luhn mod-10 (CONFIRMED [4]):** from the digit left of the check digit, moving left, double every second digit; if a doubled value > 9 subtract 9; sum all digits incl. the check digit; valid iff `total % 10 == 0`.
- **IIN prefix → brand (all CONFIRMED against [3], Stripe test PANs [2]):**

  | Brand | IIN prefix rule | Allowed lengths |
  |---|---|---|
  | Visa | first digit `4` | 13, 16, 19 |
  | Mastercard | `51`–`55` **or** `2221`–`2720` | 16 |
  | Amex | `34` or `37` | 15 |
  | Discover | `6011`, `644`–`649`, `65`, `622126`–`622925` | 16–19 |
  | Diners | `30`(incl `300`–`305`,`3095`), `36`, `38`, `39` | 14–19 |
  | JCB | `3528`–`3589` | 16–19 |
  | UnionPay | `62` | 16–19 |
  | Maestro | `5018`,`5020`,`5038`,`5893`,`6304`,`6759`,`6761`,`6762`,`6763` (BIN-table, not range-guess) | 12–19 |

  > The parenthetical broad shorthand "Maestro = 50 / 56–69" from the raw research is **UNVERIFIED as an authoritative enumeration** — the verify pass confirmed only the specific BINs above. Use the BIN table, not the loose range.

### 2.2 How the normalized PAN detector works
Per §1.3: window a 13–19-digit run tolerating `_SEP`; strip; try each valid length (16,15,19,14,13); accept the first that is **both** Luhn-valid **and** matches an assigned IIN prefix; emit `⟦AEGR:{nonce}:CARD:{first6}:{last4}⟧`. **Never emit the middle digits, even tokenized** (LLD 29 §3.3 footgun). A Luhn-valid run whose IIN is unassigned is *structurally* not a card — but for a redactor, favor masking: if it passes Luhn and is 13–19 digits, mask it as `<CARD>` even without a brand match (fail-safe toward over-masking a number that looks exactly like a card). Brand is used for the length filter, not as a hard gate to redact.

This handles the leak variants directly: `4111 1111 1111 1111`, `4111  1111 1111 1111`, `4111\t1111\t1111\t1111`, `4111-1111-1111-1111`, `4111.1111.1111.1111`, `3782 822463 10005` (Amex 4-6-5), and the bare `4111111111111111` all normalize to the same digit run and pass identically.

### 2.3 SAD handling (drop, never tokenize with a value)

- **Card security code (CVV2/CVC2/CID/CAV2/CVN2)** — 3 digits (Visa/MC/Disc/JCB/UnionPay) or 4 (Amex); **no checksum** [PCI glossary][Wikipedia card-security-code] (CONFIRMED). Detect **only label-anchored** (`cvv`, `cvc`, `cid`, `security code`, `cvn` adjacent) — a bare `123` has no structure and must NOT be blanket-scrubbed. Emit `<SAD>` with **no meta**, value dropped.
- **Track 1 (Format B)** — `%B<PAN>^<NAME>^<YYMM><svc><disc>?<LRC>`, ≤79 chars; start `%`, sep `^`, end `?` [ISO/IEC 7813] (CONFIRMED [Track-1 verify]). Anchor on `%B` + two `^` + a 4-digit expiry. Drop the whole track → `<SAD>`.
- **Track 2** — `;<PAN>=<YYMM><svc><disc>?<LRC>`, ≤40 chars; start `;`, sep `=`, end `?` (CONFIRMED [ISO/IEC 7813]). The `=` separator is the Track-2 tell. Drop the whole track → `<SAD>`. **UNVERIFIED-corrected nuance:** the raw-research "valid Track 2 example" omitted the trailing LRC char — for *detection* this is immaterial (we anchor on `;`…`=`…`?`, LRC optional), but do NOT assert a well-formed track requires only up to `?`.
- **PIN / PIN block** — clear PIN 4–12 digits; PIN block 16 hex (8 bytes), first nibble is the ISO 9564 format id ∈ `{0,1,2,3,4}` [ISO 9564]. **Corrected by verify pass:** the raw-research valid PIN-block example `A1B2C3D4E5F60789` is **INVALID** (first nibble `A` is not a legal ISO-9564 format id) — do not use it as a positive fixture. Detect PIN only label-anchored (`pin`, `pin block`); PIN block only as a 16-hex run whose first nibble ∈ `{0..4}` AND label-anchored. Emit `<SAD>`, value dropped. **No offline checksum exists** for either (CONFIRMED [ISO 9564 / PCI glossary]).

> **PCI is the hard 0-miss deterministic gate** (LLD 29 §15.4, §7.2). PAN + SAD get their own release-blocking test on `corpus/pci_sad_pan.jsonl`, never averaged into the fuzzy Tier-2 recall number.

---

## 3. Per-identifier table

Legend: **CS** = checksum status. All checksum verdicts are from the verify pass; where verify **refuted** the raw research it is flagged inline. `[n]` citations map to §6 Sources.

| # | Name | Region | Structure | Length | CS (verified) | Validity rules (redactor accept condition) | Valid example | Invalid example |
|---|---|---|---|---|---|---|---|---|
| 1 | **Payment-card PAN** | global | MII+IIN+account+Luhn digit; brand by IIN [1][3] | 8–19 | **Luhn mod-10 — CONFIRMED** [4] | 13–19 digits, `total%10==0`, IIN assigned (§2.1) | `4111 1111 1111 1111` [2] | `4111 1111 1111 1112` (Luhn fail) |
| 2 | **Visa** | global | first digit `4` [3] | 13/16/19 | **Luhn — CONFIRMED** [3] | `^4`, len∈{13,16,19}, Luhn | `4242 4242 4242 4242` [2] | `4242 4242 4242 4243` |
| 3 | **Mastercard** | global | `51`–`55` or `2221`–`2720` [3] | 16 | **Luhn — CONFIRMED** [3] | prefix rule, len 16, Luhn | `5555 5555 5555 4444` [2] | `5555 5555 5555 4445` |
| 4 | **Amex** | global | `34`/`37`, 4-6-5 spacing, 4-digit CID [3] | 15 | **Luhn — CONFIRMED** [3] | `^3[47]`, len 15, Luhn | `378282246310005` [2] | `378282246310006` |
| 5 | **Discover** | global (US) | `6011`,`644`–`649`,`65`,`622126`–`622925` [3] | 16–19 | **Luhn — CONFIRMED** [3] | prefix rule, len 16–19, Luhn | `6011 1111 1111 1117` [2] | `6011 1111 1111 1118` |
| 6 | **Diners Club** | global | `30`/`36`/`38`/`39` [2] | 14–19 | **Luhn — CONFIRMED** [2] | prefix rule, len 14–19, Luhn | `36227206271667` (14) [2] | `3056930009020005` |
| 7 | **JCB** | global (JP) | `3528`–`3589` [3] | 16–19 | **Luhn — CONFIRMED** [3] | prefix, len 16–19, Luhn | `3566 0020 2036 0505` [2] | `3566 0020 2036 0506` |
| 8 | **UnionPay** | global (CN) | `62` [2] | 16–19 | **Luhn — CONFIRMED** [2] (intl-routed; some legacy domestic ranges are non-Luhn — **UNVERIFIED, treat all `62` as Luhn**) | `^62`, len 16–19, Luhn | `6200 0000 0000 0005` [2] | `6200 0000 0000 0006` |
| 9 | **Maestro** | global (ex-US) | BIN-table (`5018/5020/5038/5893/6304/6759/6761/6762/6763`) [3] | 12–19 | **Luhn — CONFIRMED** [3] | BIN in table, len 12–19, Luhn | `6759 6498 2643 8453` [3] | `6759 6498 2643 8454` |
| 10 | **Card security code (SAD)** | global | 3 or 4 numeric, not on stripe [PCI] | 3 / 4 | **none — CONFIRMED** [2] | **label-anchored only** (`cvv/cvc/cid/cvn/security code`); 3 digits (4 Amex) | `CVV 123` / `CID 1234` | `12` (too short) / `12A` |
| 11 | **Track 1 (SAD)** | global | `%B PAN ^ NAME ^ YYMM svc disc ? LRC` [ISO 7813] | ≤79 | LRC — **CONFIRMED** (LRC optional for detection) | starts `%B`, two `^`, 4-digit expiry, `?` | `%B4111111111111111^DOE/JOHN^2612101000000000000?` | `%B4111111111111111^DOE/JOHN^^?` |
| 12 | **Track 2 (SAD)** | global | `; PAN = YYMM svc disc ? LRC` [ISO 7813] | ≤40 | LRC — **CONFIRMED**; raw-research valid example **omitted trailing LRC (verify: append LRC `;`)** — immaterial for detection | starts `;`, one `=`, expiry, `?` | `;4111111111111111=2612101000000000?;` | `;4111111111111111?` |
| 13 | **PIN / PIN block (SAD)** | global | clear PIN 4–12; block 16 hex, nibble0 ∈ `{0..4}` [ISO 9564] | 4–12 / 16 hex | **none — CONFIRMED**; block is *encrypted* not checksummed | label-anchored; block = 16 hex, first nibble ∈`{0..4}`. Raw-research valid example `A1B2C3D4E5F60789` is **REFUTED (nibble0=A illegal)** — use `041261FFFFFFFFFF` | `PIN 1234` / block `041261FFFFFFFFFF` | `PIN 12` / block `A1B2C3` |
| 14 | **US SSN** | US | `AAA-GG-SSSS`, 9 digits, no check digit [SSA] | 9 | **none — CONFIRMED** [SSA] | positional: area ∉ `{000,666,900–999}`, group ≠ `00`, serial ≠ `0000`; **shape-only → require label anchor or the positional rule (§1.2)** | `123-45-6789` | `666-45-6789` |
| 15 | **ITIN** | US | SSN shape, first digit `9`, mid ∈ ranges [IRS IRM] | 9 | **none — CONFIRMED** [IRS] | `^9`, mid pair ∈ `{50–65,70–88,90–92,94–99}`, mid ∉ `{89,93}`. ("serial≠0000" = **UNVERIFIED inference**, not in IRM) | `912-70-1234` | `912-89-1234` |
| 16 | **EIN** | US | `XX-XXXXXXX`, dash at 2-7 [IRS] | 9 | **none — CONFIRMED** [IRS] | 2-digit prefix ∈ IRS-assigned set; dash position (2-7) disambiguates from SSN (3-2-4) | `12-3456789` | `07-1234567` |
| 17 | **Medicare MBI** | US | 11-char positional, no S/L/O/I/B/Z in letter positions [CMS/Purview] | 11 | **none — CONFIRMED** | pos1 ∈ `1–9`; letter/AN positions exclude `S,L,O,I,B,Z`; uppercase | `1EG4-TE5-MK73` | `1SG4TE5MK73` |
| 18 | **Hospital MRN** | US | institution-specific, no national scheme | variable (~6–10) | **none universal — CONFIRMED** | **no cross-institution rule** → label-anchored only (`MRN`, `record no.`); do NOT assume any checksum | `MRN 00849321` (per-facility) | `84A9321` (letter in a numeric facility) |
| 19 | **US Driver's License** | US | state-specific, no national format | ~1–14 | **none — CONFIRMED** [Purview] | **no cross-state rule** → label-anchored (`DL`,`DLN`,`LIC`); NY `\d{3} \d{3} \d{3}`, CA `[A-Z]\d{7}` as examples only | NY `123 456 789` / CA `I1234567` | NY-scheme `A1234567` (valid CA, invalid NY) |
| 20 | **US Phone (NANP)** | US | `NPA-NXX-XXXX` [NANP] | 10 (11 w/ +1) | **none — CONFIRMED** | `[2-9]XX-[2-9]XX-XXXX`; NPA/NXX first digit 2–9; N11 reserved | `(212) 555-0198` | `(123) 456-7890` |
| 21 | **Canada SIN** | CA | 9 digits, leading = province/type, Luhn digit last | 9 | **Luhn — CONFIRMED** [python-stdnum] | 9 digits, Luhn `%10==0` | `046 454 286` | `046 454 287` |
| 22 | **India Aadhaar** | IN | 12 digits, first 2–9, Verhoeff check last | 12 | **Verhoeff — CONFIRMED with a table FIX (see §5.1)** | 12 digits, first ∈ `2–9`, Verhoeff==0 | worked pair `2363` valid (`236`→check `3`) | `0175 9834 6012` (starts 0) |
| 23 | **India PAN (tax)** ⚠️ | IN | `AAAAA9999A`; char4=entity type, char5=name letter, char10=check letter [Wikipedia] | 10 | **alphabetic check — algorithm NOT public → NO local checksum; CONFIRMED** | regex `^[A-Z]{5}[0-9]{4}[A-Z]$`; optionally char4 ∈ `{A,B,C,F,G,H,J,L,P,T}`; **verify via ITD/Protean API, no mod-N** | `AAAPZ1234C` | `AAA1Z1234C` (digit in letter prefix) |
| 24 | **UK NINO** | UK | 2 letters + 6 digits + suffix A–D [Wikipedia/HMRC] | 9 | **none — CONFIRMED** | prefix letters ∉`{D,F,I,Q,U,V}`; 2nd ∉`{O}`; pair ∉`{BG,GB,KN,NK,NT,TN,ZZ}`; suffix ∈`{A,B,C,D}` | `AB 12 34 56 C` | `QQ 12 34 56 C` |
| 25 | **UK NHS Number** | UK | 10 digits, 3-3-4, mod-11 check [NHS] | 10 | **mod-11 — CONFIRMED** [nhs-number-validator] | weights 10..2 on first 9; `check = 11-(sum%11)`; `11→0`, `10→invalid`; must match digit 10 | `943 476 5919` | `943 476 5918` |
| 26 | **IBAN** (banking, not national ID) | EU/global | country(2)+check(2)+BBAN; fixed len per country [ISO 13616] | ≤34 (per-country) | **ISO 7064 mod-97-10 — CONFIRMED** [IBAN] | move first 4 to end, letters→digits (A=10..Z=35), `int % 97 == 1`; country len must match | `GB82 WEST 1234 5698 7654 32` | `…7654 33` |
| 27 | **Australia TFN** | AU | 9 digits (legacy 8) | 9 | **mod-11 weighted — CONFIRMED** [Wikipedia] | weights `1,4,3,7,5,8,6,9,10`; `sum % 11 == 0`. **Legacy 8-digit uses a DIFFERENT weight vector — UNVERIFIED, 9-digit only** | `123 456 782` | `123 456 789` |
| 28 | **Brazil CPF** | BR | 11 digits `NNN.NNN.NNN-DD` | 11 | **double mod-11 — CONFIRMED** [Business::BR::CPF] | D1: w `10..2` on first 9; D2: w `11..2` on first 10; `rem<2→0 else 11-rem`; **reject repunits** (`111...`, `000...`) even if math passes | `111.444.777-35` | `111.444.777-30` |
| 29 | **Italy Codice Fiscale** | IT | 16 alnum positional (individuals) | 16 | **mod-26 check letter — CONFIRMED** [Wikipedia] | odd/even position tables → sum → `%26` → `0=A..25=Z` must match char16 | `MRTMTT91D08F205J` | `MRTMTT91D08F205A` |
| 30 | **Spain DNI/NIF/NIE** | ES | 8 digits+letter (NIE: X/Y/Z→0/1/2 + 7 digits+letter) | 9 | **mod-23 letter — CONFIRMED** [Wikipedia] | `num % 23` → index into `TRWAGMYFPDXBNJZSQVHLCKE`; letter must match; no I/O/U/Ñ | `12345678Z` | `12345678A` |
| 31 | **Netherlands BSN** | NL | 9 digits (8 w/ leading 0) | 9 | **11-test — CONFIRMED (raw-research invalid-example arithmetic REFUTED)** | weights `9,8,7,6,5,4,3,2` then `-1` on last; `sum % 11 == 0`, `int>0`. Raw research said `111222334`→sum 67; **verify: sum is 65** (still fails → still invalid) | `111222333` | `111222334` |
| 32 | **South Africa ID** | ZA | 13 digits `YYMMDD SSSS C A Z`, Luhn last | 13 | **Luhn — CONFIRMED** [django localflavor] | 13 digits, valid `YYMMDD`, citizenship 0/1, Luhn `%10==0` | `9807055009087` | `9807055009086` |

### ⚠️ 3.1 THE NAME COLLISION — India PAN (tax) vs payment-card PAN
**"PAN" means two completely different things in this codebase's problem domain, and conflating them is a real bug.** Payment-card **PAN** = Primary Account Number (a 8–19-**digit** card number, Luhn-checked → `<CARD>`). India **PAN** = Permanent Account Number (a 10-char **alphanumeric** `AAAAA9999A` tax ID → would map to a distinct `<TAXID_IN>` / `<PAN_IN>` token, no Luhn, no local checksum). They share **nothing** but the three letters:

| | Payment-card PAN | India tax PAN |
|---|---|---|
| Shape | 8–19 digits | `[A-Z]{5}[0-9]{4}[A-Z]` (10 chars) |
| Checksum | **Luhn mod-10** | **none reproducible** (private ITD algorithm) |
| Token | `⟦…:CARD:6:4⟧` | `⟦…:TAXID_IN⟧` (if ever built — P2, §4/§5) |
| Matcher | `PANMatcher` (card) | would be `IndiaPANMatcher` — **NOT** the card matcher |

**In code:** name the card matcher `PANMatcher`/`CardMatcher` unambiguously; if the India tax PAN is ever added it MUST be a separate matcher with a separate token — never overload `PANMatcher`, and never run a Luhn check on the India PAN (it will spuriously pass/fail on the 4 embedded digits and produce garbage).

---

## 4. What to add to `corpus/pci_sad_pan.jsonl` and `corpus/redaction_recall.jsonl`

Both corpora are **NEW** (neither exists yet — confirmed by grep). Row schema follows LLD 29 §15.4: each case is `{"text": ..., "expect": [{"class": ..., "token": ..., "span": [start,end]}]}` (span optional for the recall harness; the PCI harness asserts the emitted token). Below are **concrete rows**, weighted toward the separator variants that leaked. `<CARD:6:4>` below is the human-readable render of `⟦AEGR:{nonce}:CARD:6:4⟧`.

### 4.1 `corpus/pci_sad_pan.jsonl` — HARD 0-miss (release-blocking)

```jsonl
{"text": "4111 1111 1111 1111", "expect": [{"class":"PAN","token":"<CARD:411111:1111>"}]}
{"text": "4111  1111  1111  1111", "expect": [{"class":"PAN","token":"<CARD:411111:1111>"}], "note":"2-space — LEAKED before"}
{"text": "4111   1111   1111   1111", "expect": [{"class":"PAN","token":"<CARD:411111:1111>"}], "note":"3-space — LEAKED before"}
{"text": "4111\t1111\t1111\t1111", "expect": [{"class":"PAN","token":"<CARD:411111:1111>"}], "note":"tab-delimited (spreadsheet paste) — LEAKED before"}
{"text": "4111-1111-1111-1111", "expect": [{"class":"PAN","token":"<CARD:411111:1111>"}]}
{"text": "4111.1111.1111.1111", "expect": [{"class":"PAN","token":"<CARD:411111:1111>"}], "note":"dot-separated"}
{"text": "4111111111111111", "expect": [{"class":"PAN","token":"<CARD:411111:1111>"}], "note":"no separator"}
{"text": "card on file: 4111/1111/1111/1111 exp 12/26", "expect": [{"class":"PAN","token":"<CARD:411111:1111>"}], "note":"slash-delimited PAN embedded in prose"}
{"text": "3782 822463 10005", "expect": [{"class":"PAN","token":"<CARD:378282:0005>"}], "note":"Amex 4-6-5 grouping"}
{"text": "the customer paid with 5555555555554444 yesterday", "expect": [{"class":"PAN","token":"<CARD:555555:4444>"}], "note":"PAN embedded in prose"}
{"text": "6759 6498 2643 8453", "expect": [{"class":"PAN","token":"<CARD:675964:8453>"}], "note":"Maestro BIN"}
{"text": "4111 1111 1111 1112", "expect": [], "note":"NEGATIVE: Luhn fails → must NOT be tokened as a card"}
{"text": "order 4111 1111 1111 1111 2222 shipped", "expect": [{"class":"PAN","token":"<CARD:411111:1111>"}], "note":"over-join guard: 20-run must still catch the 16 PAN, not fuse into a 20-digit non-card"}
{"text": "CVV 123", "expect": [{"class":"SAD","token":"<SAD>"}], "note":"label-anchored 3-digit CVV — value DROPPED"}
{"text": "security code: 1234 (Amex)", "expect": [{"class":"SAD","token":"<SAD>"}], "note":"4-digit Amex CID"}
{"text": "my favorite number is 123", "expect": [], "note":"NEGATIVE: bare 3-digit, no CVV label → must NOT scrub"}
{"text": "%B4111111111111111^DOE/JOHN^2612101000000000000?", "expect": [{"class":"SAD","token":"<SAD>"}], "note":"Track 1 — whole track dropped"}
{"text": ";4111111111111111=2612101000000000?;", "expect": [{"class":"SAD","token":"<SAD>"}], "note":"Track 2 (with LRC) — whole track dropped"}
{"text": "PIN block 041261FFFFFFFFFF", "expect": [{"class":"SAD","token":"<SAD>"}], "note":"valid ISO-9564 fmt-0 block (nibble0=0); NOT the refuted A1B2... example"}
{"text": "reset PIN 1234 now", "expect": [{"class":"SAD","token":"<SAD>"}], "note":"label-anchored clear PIN"}
```

### 4.2 `corpus/redaction_recall.jsonl` — fuzzy per-class recall (WS-0-gated threshold)

Includes the leaked separator variants for SSN plus obfuscated / non-US / narrative cases (Appendix G (ii); a canonical-only corpus passes vacuously, E12).

```jsonl
{"text": "SSN 123-45-6789", "expect": [{"class":"SSN","token":"<SSN>"}]}
{"text": "ssn: 123 45 6789", "expect": [{"class":"SSN","token":"<SSN>"}], "note":"space-separated"}
{"text": "ssn 123/45/6789", "expect": [{"class":"SSN","token":"<SSN>"}], "note":"slash-delimited SSN — LEAKED before"}
{"text": "ssn\t123\t45\t6789", "expect": [{"class":"SSN","token":"<SSN>"}], "note":"tab-delimited SSN — LEAKED before"}
{"text": "SSN 123456789", "expect": [{"class":"SSN","token":"<SSN>"}], "note":"unformatted 9-digit"}
{"text": "his social is 666-45-6789", "expect": [], "note":"NEGATIVE: area 666 never assigned → not a valid SSN"}
{"text": "email jane.doe+test@sub.example.co.uk here", "expect": [{"class":"EMAIL","token":"<EMAIL>"}]}
{"text": "call me at (212) 555-0198", "expect": [{"class":"PHONE","token":"<PHONE>"}]}
{"text": "server 169.254.169.254 and 10.0.0.5", "expect": [{"class":"IP","token":"<IP>"},{"class":"IP","token":"<IP>"}]}
{"text": "token in url https://x.com/cb?api_key=sk_live_9f3kD2xQ...", "expect": [{"class":"URL","token":"<URL>"},{"class":"SECRET","token":"<SECRET>"}], "note":"URL-query secret strip (§3.7)"}
{"text": "MRN 00849321 admitted", "expect": [{"class":"MRN","token":"<MRN>"}], "note":"label-anchored"}
{"text": "aws key AKIAIOSFODNN7EXAMPLE rotated", "expect": [{"class":"SECRET","token":"<SECRET>"}], "note":"high-entropy"}
{"text": "order id 550e8400-e29b-41d4-a716-446655440000 shipped", "expect": [], "note":"NEGATIVE: low-entropy UUID must NOT be scrubbed (§3.4)"}
{"text": "NHS 943 476 5919 on file", "expect": [{"class":"NHS","token":"<NHS>"}], "note":"non-US, mod-11"}
{"text": "Aadhaar 2363 (worked example prefix aside) — full 12-digit run in prose", "expect": [], "note":"placeholder; real Aadhaar rows use full Verhoeff-valid 12-digit values"}
{"text": "IBAN GB82 WEST 1234 5698 7654 32 for the wire", "expect": [{"class":"IBAN","token":"<IBAN>"}], "note":"mod-97"}
{"text": "please refund the c-a-r-d 4 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1", "expect": [{"class":"PAN","token":"<CARD:411111:1111>"}], "note":"OBFUSCATED: single-space-between-every-digit — the normalize-then-detect stress case"}
```

> The last row is the **whole point of §1**: an attacker/user who space-separates *every* digit defeats any per-group regex but not normalize-then-detect. It belongs in both corpora (PCI copy is release-blocking).

---

## 5. Scope call for THIS MVP

The beachhead is **financial-action agents** (MEMORY: gtm-beachhead). That fixes the P0 set: the identifiers that appear on a financial/payment/US-healthcare action path.

### 5.1 P0 — ship in WS-E (must pass, release-blocking)
- **Payment-card PAN** (Visa/MC/Amex/Discover/Diners/JCB/UnionPay/Maestro) — Luhn + IIN table → `<CARD:6:4>`. **Hard 0-miss.**
- **SAD** — CVV/CVC/CID (label-anchored), Track 1/2 (sentinel-anchored), PIN/PIN-block (label-anchored + ISO-9564 nibble check) → `<SAD>`, dropped. **Hard 0-miss.**
- **US SSN** — positional rules + label/shape → `<SSN>`.
- **Supporting HIPAA-Safe-Harbor structured matchers already in LLD 29 §3.2** (email, phone, IP/URL, dates, label-anchored MRN/account/license/device, high-entropy `<SECRET>`) — these are stdlib-trivial (regex/entropy, no checksum) and ship with P0.

All P0 checksums are **CONFIRMED** by the verify pass and stdlib-only (Luhn = 6 lines).

### 5.2 Nice-to-have — behind a per-tenant/region flag (P1)
International national IDs, off by default, enabled per tenant residency:
- **Canada SIN** (Luhn), **UK NHS** (mod-11), **UK NINO** (structural), **IBAN** (mod-97), **Australia TFN** (mod-11), **Brazil CPF** (double mod-11 + repunit reject), **Italy CF** (mod-26), **Spain DNI/NIE** (mod-23), **Netherlands BSN** (11-test), **South Africa ID** (Luhn), **US EIN/ITIN** (structural), **Medicare MBI** (positional).

Every one of these has a **CONFIRMED, stdlib-implementable checksum or a pure structural rule** — no library needed. They are P1 only because the beachhead doesn't need them day 1, not because they're hard. Gate them behind a region flag so a US-fintech tenant isn't paying false-positive risk on a Codice Fiscale matcher.

### 5.3 Needs a checksum lib we CANNOT add — none (the stdlib-only constraint holds)
**There is no identifier in this set that forces a dependency.** The two "scary" checksums are pure arithmetic:
- **Verhoeff (Aadhaar)** — three constant lookup tables (`d`, `inv`, `p`) + a right-to-left loop. **~15 lines, stdlib-only.** ⚠️ **Ship the CORRECTED table:** the verify pass caught a transcription error in the raw research — permutation row **`p[6]` must be `2793806415`, NOT `2793860415`** (columns 5–6 transposed). Using the wrong row flips ~4% of validity verdicts. Unit-test against the published worked pair (`gen_check(236)==3`, `validate(2363)==0`).
- **mod-11 / mod-97 / mod-23 / mod-26** (NHS, IBAN, Spain, Italy, TFN, BSN, CPF) — plain integer arithmetic + a constant string/weight vector. Each is <20 lines.

**India tax PAN** is the one identifier with **no reproducible checksum** (the ITD algorithm is private — CONFIRMED). If ever added (P2), it is **format-regex-only** (`^[A-Z]{5}[0-9]{4}[A-Z]$` + entity-letter check), authoritative validation deferred to the ITD/Protean API — and it MUST be its own matcher/token, never overloaded onto the card `PANMatcher` (§3.1).

**Bottom line:** the stdlib-only constraint (LLD 29 §3.1) is **not** a limiter on which identifiers we can support — it only means we implement the checksum arithmetic ourselves (which is trivial and testable) rather than importing `python-stdnum`. Every P0 and P1 identifier ships pure-stdlib.

---

## 6. Sources

Format/checksum claims above cite these (all CONFIRMED by the verify pass except where a row is marked UNVERIFIED or REFUTED):

1. ISO/IEC 7812 — https://www.iso.org/standard/70484.html · https://en.wikipedia.org/wiki/ISO/IEC_7812
2. Stripe test cards — https://docs.stripe.com/testing
3. Payment card number (brands/IIN) — https://en.wikipedia.org/wiki/Payment_card_number
4. Luhn — https://en.wikipedia.org/wiki/Luhn_algorithm
- PCI glossary / SAD — https://www.pcisecuritystandards.org/glossary/
- Card security code — https://en.wikipedia.org/wiki/Card_security_code
- ISO/IEC 7813 (tracks) — https://en.wikipedia.org/wiki/ISO/IEC_7813
- ISO 9564 (PIN) — https://en.wikipedia.org/wiki/ISO_9564 · https://www.eftlab.com/knowledge-base/complete-list-of-pin-blocks
- SSN — SSA POMS RM 10201.035 https://secure.ssa.gov/poms.nsf/lnx/0110201035 · https://en.wikipedia.org/wiki/Social_Security_number
- ITIN — https://www.irs.gov/irm/part3/irm_03-021-263r
- EIN — https://www.irs.gov/businesses/small-businesses-self-employed/how-eins-are-assigned-and-valid-ein-prefixes
- MBI — https://www.cms.gov/medicare/new-medicare-card/understanding-the-mbi-with-format.pdf
- US DL — https://learn.microsoft.com/en-us/purview/sit-defn-us-drivers-license-number
- NANP — https://en.wikipedia.org/wiki/North_American_Numbering_Plan
- Canada SIN — https://github.com/arthurdejong/python-stdnum/blob/master/stdnum/ca/sin.py
- Aadhaar / Verhoeff — https://en.wikipedia.org/wiki/Verhoeff_algorithm · https://en.wikipedia.org/wiki/Aadhaar
- India PAN (tax) — https://en.wikipedia.org/wiki/Permanent_account_number
- UK NINO — https://en.wikipedia.org/wiki/National_Insurance_number · https://www.gov.uk/hmrc-internal-manuals/national-insurance-manual/nim39110
- UK NHS — https://github.com/spikeheap/nhs-number-validator/blob/master/index.js
- IBAN — https://en.wikipedia.org/wiki/International_Bank_Account_Number · ISO 7064
- Australia TFN — https://en.wikipedia.org/wiki/Tax_file_number
- Brazil CPF — https://metacpan.org/pod/Business::BR::CPF
- Italy CF — https://en.wikipedia.org/wiki/Italian_fiscal_code
- Spain DNI/NIE — https://en.wikipedia.org/wiki/Documento_Nacional_de_Identidad_(Spain)
- Netherlands BSN — https://github.com/arthurdejong/python-stdnum/blob/master/stdnum/nl/bsn.py
- South Africa ID — django localflavor za/forms.py

## 7. Cross-references
- **Parent:** [29-redaction.md](29-redaction.md) §3.1 (stdlib-only), §3.2 (`_ORDERED_MATCHERS`), §3.3 (`⟦AEGR:{nonce}:TYPE[:meta]⟧` grammar), §3.4 (entropy floor), §15.4 (the two corpora).
- **Shared contracts (join keys, unchanged from LLD 29):** `redact(value, *, nonce) -> str` · token grammar `⟦AEGR:{nonce}:TYPE[:meta]⟧` (tokens incl. `CARD:6:4`, `SAD`, `SSN`, `EMAIL`, `PHONE`, `IP`, `URL`, `MRN`, `ACCT`, `LICENSE`, `DEVICE`, `DATE`, `SECRET`; **new here only as a P2 note:** `TAXID_IN` if India tax PAN is ever built) · corpora `corpus/pci_sad_pan.jsonl` (hard 0-miss) + `corpus/redaction_recall.jsonl` (WS-0-gated fuzzy).
- **Code anchors (new/edited by the rewrite this spec drives):** `demo-agents/sdk/aegion-guard-python/src/aegion_guard/redaction.py` (NEW — the matchers + normalize-then-detect); `src/security-controller/tests/corpus/pci_sad_pan.jsonl` + `test_pci_deterministic.py` (NEW); `src/security-controller/tests/corpus/redaction_recall.jsonl` + `test_redaction_recall.py` (NEW).
- **Workstream:** [tasks/serverless-edition/ws-e-redaction.md](../tasks/serverless-edition/ws-e-redaction.md).