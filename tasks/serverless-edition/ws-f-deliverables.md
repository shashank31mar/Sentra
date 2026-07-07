# WS-F deliverables — dialect-lock note (F2.5), F5 loop design, F8 gap list + incident

Companion to [ws-f-prompt-signatures.md](ws-f-prompt-signatures.md). Holds the
NON-CODE, hand-off deliverables the task doc names: the LOCKED dialect spec for WS-A
(F2.5), the FR-3.14 continuous-improvement loop DESIGN (F5, design-only), and the
Cedar/abuse relocation gap list + coverage-gap incident (F8). The code + tests for
F1/F2/F3/F4/F6/F7 live in `src/security-controller/` (see the task doc's milestone map).

---

## F2.5 — LOCKED prompt-signature dialect spec (WS-A input)

Frozen as of this milestone (lld/35 Appendix A). This is WS-A's input; the
differential-conformance test is WS-A's and is **spike-gated — conformance is
UNPROVEN today** (no SDK `bundle.py` exists). WS-F delivers only the spec + reject
set; it does NOT build the second evaluator.

**Matchers (closed set):** `{contains, re, all}`
- `|contains` — value is a LITERAL; `re.compile(re.escape(v), re.IGNORECASE)`; matched via `.search()`.
- `|re` — value is UNTRUSTED external regex; `re.compile(v, re.IGNORECASE)`; matched via `.search()`; validated per the reject set below.
- `|all` — `require_all=True`; the selection is true only if EVERY value hits; each value escaped like `|contains`.
- Any other `|modifier` (`|lt`, `|gte`, `parameters.*`, `session.*`, `tool_name`, equality) is NOT a dialect matcher → produces ZERO matchers (inert; this is why the 4 param-rules never fire).

**Condition grammar (closed set):** `{<selection-name>, 1 of them, all of them, and, or, not, ( … )}`
- Precedence: `not` > `and` > `or`; parenthesizable.
- Parsed to a pure boolean AST (`And/Or/Not/Ref/OneOfThem/AllOfThem`); evaluation is a fold over the per-selection bool map. **Never `eval()`.**
- Missing/empty condition defaults to `1 of them` (the old any-hit semantics).
- A condition referencing a selection NOT declared in `detection` FAILS the rule load (a param-only selection that dropped to zero matchers is still *declared* → legal ref, always-False).

**Case-folding:** matchers are compiled `IGNORECASE`; match on the raw text (no separate lower()).

**Reject set (§6d — fail-secure, applied at LOAD):**
- `|re` uncompilable → skip that matcher + log; the rule's other matchers still load.
- `|re` tripping the catastrophic-backtracking structural heuristic (`(a+)+`, `(a*)*`, alternation-in-repetition) → skip + log.
- `|re` source > 512 chars → skip + log.
- matcher-count > 200 per rule → HARD reject the rule; > 5,000 per ruleset → HARD reject the reload (keep last-known-good).
- condition with any char outside the closed grammar (quotes, `+`, `,`, `[` …) → parse error → skip the rule (code-smuggle guard).

Canonical impl: [src/security-controller/app/validators/sigma_dialect.py](../../src/security-controller/app/validators/sigma_dialect.py).

**Byte-identity to Appendix A is NOT independently verified here** — the WS-A interpreter that would prove it does not exist yet. Do not claim conformance until WS-A's differential test ships.

---

## F5 — FR-3.14 corpus continuous-improvement loop (DESIGN-ONLY; no runtime code)

The runtime re-score/retrain job IS FR-3.14 (P2) and is a later F5 workstream. WS-F
delivers only the design + the F4 gate-interlock (already executable + tested in F4).

**Loop (§14.1):** redacted feedback store (LLD 29) → offline re-score job (the current
engine + the heavy classifier used ONLY as a labeling instrument, NOT a training
target) → FP/FN metrics → candidate signature edits → **MUST pass the F4 gate**
([sigma_eval_gate.run_gate](../../src/security-controller/app/validators/sigma_eval_gate.py)) → push to store / signed bundle. F5 grows **RULES (`|contains` only)**, never ML weights.

**Two constructs escalate to a human PR, never auto-ship:**
1. a new/changed `|re` (the only untrusted-regex surface);
2. any candidate that mutates a rule's `llm.<x>` tag set (a tag flip corrupts the
   derived `threat_type` while leaving FP/recall unchanged — invisible to the gate).

**Why runtime is deferred (§14.2 — VERIFIED):**
- (a) the feedback table + phi-ner service are wired into NO deployed stack (constructs exist on main but not in `cdk/app.py`);
- (b) the Tier-2 PHI redactor still defaults to the stdlib stub ([phi_ner.py:16-21](../../src/security-controller/app/redaction/phi_ner.py));
- (c) no offline re-score/retrain job exists — and that job IS the deferred P2 work.

**Recall-delta caveat (§14.3 / M6):** signatures match raw `user_input`; the feedback
store retains **redacted** `content_text`. A re-score therefore measures a recall-delta
between raw-authored rules and redacted-re-scored traffic. F5 candidate rules must be
authored against the redacted token forms where the target is a redacted class, or the
delta is reported and accepted (moat-tension residual #5). **State it, do not hide it.**

---

## F8 — Cedar/abuse relocation gap list (→ WS-I) + coverage-gap incident

The 4 param/session rules match `parameters.*` / `session.*` / `tool_name` — OUTSIDE
the signature dialect (`req.user_input` only). They are **inert in signatures today**
(zero `|contains` → zero matchers → never fire). A relocation is "closed" ONLY when a
tested covering Cedar/abuse policy exists (WS-I owns the authoring half; WS-F owns the
sequencing discipline + this gap list). **No zero-coverage window** — the inert YAML
STAYS until the covering policy is green.

### Per-rule gap list (dated coverage contract for WS-I)

| Rule (id) | Inert predicate(s) | Relocate to | Severity / required-by | Covering policy exists? |
|---|---|---|---|---|
| `suspicious_parameter_manipulation` (sigma-llm-011, *experimental* — not even loaded) | `parameters.amount|lt: 0`, `parameters.limit|gte: 1000` | Cedar param-bounds | P0 money (`amount>=0`), **before any YAML removal** | ❌ — WS-I TODO |
| `excessive_refund_attempts` (sigma-llm-006) | `process_refund` + `parameters.amount|gte: 5000`, `session.refund_count|gte: 3` | Cedar amount-cap + sequence | **P0** money, before removal | ❌ — WS-I TODO |
| `data_exfiltration` (sigma-llm-003) — SPLIT | keep `prompt|contains` (DATA_THEFT); relocate `parameters.limit|gte: 500` (selection stays INERT in YAML until Cedar limit-cap is green — no zero-coverage window) | Cedar limit-cap | P1 | ❌ — WS-I TODO (prompt half stays live in signatures) |
| `rate_limit_abuse` (sigma-llm-009) | `session.query_count|gte: 50`, `session.calls_per_minute|gte: 20` | **abuse-detector surface** (`abuse_detector.check_rate_limit`, [registry.py:139](../../src/security-controller/app/services/scheduler/registry.py#L139)) — NOT Cedar (WS-I has zero rate_limit scope) | P1 | ❌ — **NO clear A-L owner** (founder to assign) |

**Deny-on-missing (WS-I correctness half):** the relocated money-movement Cedar rule
must `has`-guard both `context.amount` and `principal.max_refund_amount` AND carry an
explicit deny-on-missing forbid, so a request OMITTING `amount` DENYs (not ALLOWs via a
dropped has-less forbid). Acceptance: a `process_refund` with `amount < 0` DENYs AND one
with a MISSING `amount` DENYs — both green before the P0 YAML is removed
(`cedar-policy-patterns` invariants 2+3).

### Coverage-gap incident (internal note — F8.5)

These 4 controls (negative-amount block, refund cap, per-minute rate ceiling, query-limit
cap) have been **INERT in production and never fired**. Per the ✅ founder resolution
(2026-07-05): **no live customer / demo / questionnaire / compliance package ever
presented them as active** → there is **no external representation to remediate**. WS-F's
obligation was to surface the facts; it does so here. WS-F relocates the rules (F8) to the
correct engine; **no external disclosure action** is owed. The representation decision is a
founder/GTM call WS-F cannot self-close — recorded as closed by the founder.

---

## Cross-references
- Parent: [ws-f-prompt-signatures.md](ws-f-prompt-signatures.md), [lld/35-prompt-signatures.md](../../lld/35-prompt-signatures.md)
- Consumers: [ws-a-local-floor-bundle.md](ws-a-local-floor-bundle.md) (F2.5 dialect spec), [ws-i-cedar-engine.md](ws-i-cedar-engine.md) (F8 gap list), [ws-m-authz.md](ws-m-authz.md) (F6.5 gate, M-M3)
- Code: `app/validators/{sigma_engine,sigma_dialect,threat_type_remap,sigma_eval_gate}.py`, `app/api/sigma_authz_ci.py`, `scripts/gen_prompt_signature_corpus.py`, `tests/fixtures/prompt_signatures/{attacks,benign}.jsonl`
