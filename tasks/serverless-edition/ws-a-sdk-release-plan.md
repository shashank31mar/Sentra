# WS-A (ship-now) / lld/36 — Approved plan (Gate-3, 2026-07-03)

> Founder-approved outline + locked decisions for `lld/36-sdk-release-and-local-floor-seam.md`.
> This is the input the design-loop BUILD phase writes from. Canonical order: HLD -> LLD -> tasks.
>
> **WHY THIS DOC EXISTS (founder split 2026-07-03):** WS-A was one monolith (SDK local floor +
> signed-bundle caching). We split it so the SDK ships NOW and unblocks dependents, while the heavy
> caching (interpreter + signed bundle) becomes a SEPARATE deferred LLD (lld/37).
> - **lld/36 (THIS doc) = SHIP-NOW:** release the SDK with all recently-merged changes (WS-B phase
>   decorators, WS-E Tier-1 redactor, WS-D trail fields), version-bump, re-vendor into the connectors,
>   AND add a **no-op `local_floor_enabled` SEAM** (off = route every call to hosted = TODAY'S behavior).
>   **No interpreter, no bundle, no caching, NO CRYPTO.** Buildable immediately.
> - **lld/37 (deferred) = CACHING:** the closed-subset interpreter + signed-bundle client + staleness/
>   epoch/anti-rollback + crypto `[local-floor]` extra + durable meter journal. FILLS the seam later.
>   Plan lives in `tasks/serverless-edition/ws-a-local-floor-caching-plan.md`.

## Ownership boundary (one line)
lld/36 owns the **released, re-vendored SDK surface + the no-op local-floor seam**. lld/37 owns the
**interpreter + bundle client + caching + crypto + meter journal** that fills the seam. lld/23 (the
historical SDK LLD, frozen 2026-06-08) gets a supersede-banner pointing here.

## The core insight that makes ship-now safe
The seam's `local_floor_enabled=off` semantics = **route every call to hosted `/v1/validate`** —
which is EXACTLY what the SDK does today (every `@guard.tool` is a blocking WAN POST, guard.py `_send`).
So ship-now changes **no runtime behavior**: it consolidates merged work into a real release, re-vendors
it into the connectors, and creates a typed plug-point. Crypto is not needed because there is no bundle
to verify yet. Metering "period" is honored trivially: 100% of calls hit hosted -> 100% metered server-side
today (the durable edge journal only becomes necessary in lld/37 when the floor starts skipping the server).

## CROSS-WORKSTREAM UNBLOCK (why ship-now matters)
- **Connectors** (`src/connectors/azure_foundry/.../aegion_guard/`, payments Lambda) vendor a BYTE-COPY of
  the SDK, not pip. A released SDK + re-vendor makes WS-B phase + WS-E redactor deploy as ONE coherent release.
- **WS-J** (canary/e2e harness) can scaffold against a frozen, released SDK surface + the seam's verdict enum.
- **WS-H** (metering) needs the SDK's bundle-fetch/heartbeat path for governed-agent existence — lld/36 can
  stub the heartbeat endpoint hook (P2) or explicitly defer it to lld/37; state which.
- **WS-B + WS-E** are merged-but-NOT-deployed (00-index: "not deployed, deferred to land once with WS-E").
  lld/36 is the release vehicle that ships them.

## LOCKED DECISIONS (founder-ratified — state as decided, do not re-open)

### S1 — Crypto is P1 (deferred to lld/37), NOT in ship-now
- Founder call 2026-07-03: "do we need crypto floor with sdk where we just need all the decorators? Can it be done as P1?" -> YES, P1.
- Crypto (`[local-floor]` extra, `ecdsa` ES256 verify) exists ONLY to verify a signed bundle. Ship-now has NO bundle. So ship-now needs ZERO crypto. Base SDK stays `dependencies = []` (stdlib-only), unchanged.
- lld/36 MUST NOT declare or stub the `[local-floor]` extra. That is 100% lld/37's.

### S2 — The seam is a typed NO-OP that routes to hosted (off = today)
- Add `SENTRA_LOCAL_FLOOR_ENABLED` / `local_floor_enabled` to config.py (default **False**).
- Add the verdict enum `{LOCAL_ALLOW, LOCAL_DENY, ESCALATE, DENY_BY_DEFAULT}` as a typed contract in the SDK (so lld/37 + WS-J code against a frozen surface), and a single hook point in guard.py between `_build_request` (redactor already ran) and `_send`.
- **Ship-now behavior when flag is False (the only path that exists):** hook is a no-op; every call falls through to `_send` (hosted). When flag is True but no interpreter is installed (lld/37 not built): **fail SECURE = route to hosted** (never skip, never local-allow). This is the `local_floor_enabled` semantics fixed by lld/28:394 (OFF = network-REQUIRED, NOT skip-validation, NOT deny-all).
- **No interpreter, no bundle client, no caching, no poll, no staleness, no meter journal** in lld/36 — all lld/37.

### S3 — Consolidate all recently-merged SDK changes into a real release
- WS-B additive phase surface: `@guard.tool`(=request), `@guard.content`, `@guard.output`, `@guard.memory` (already in guard.py:219-275); `_phase_decorator`; `TransportError.status_code` (guard.py:572); `content_text` field; unknown-phase->422 / known-but-unbuilt->fail-secure-DENY handled server-side (lld/30 — SDK just carries the phase).
- WS-E Tier-1 edge redactor: `redaction.py` (`redact`, `redact_detailed`, `redact_params`), normalize-then-detect PAN/SSN/SAD, hooked onto the WS-B `content_text` seam, runs BEFORE egress (ADR-032 ordering). Already merged (11 commits b6112fd..0c813aa).
- WS-D trail-relevant fields the SDK carries (winning_source passthrough in Decision parse; confirm what the SDK surfaces).
- Version bump: `__version__` 0.1.0 -> a real release version (propose 0.2.0 — additive phase+redactor surface, no breaking change); `pyproject.toml` version match; keep `__contract__` pinned to `/v1`.

### S4 — Re-vendor discipline (the connectors carry byte-copies)
- Connectors vendor a byte-identical subset (`src/connectors/azure_foundry/azure_function/tool_interceptor/aegion_guard/` vendors `redaction.py` + shim; payments Lambda vendors the SDK). lld/36 owns the RE-VENDOR + checksum re-verify step so the deployed edge matches the released SDK. (The Azure shim keeps import-free/stdlib-only — do not drag identity/crypto into the vendored subset.)
- Vendor-unchanged constraint holds: stdlib-only (`urllib`, no `requests`), vendors into a Lambda zip / Azure Function unchanged (lld/23 §2, §11 rule 4).

### S5 — lld/23 gets a supersede-banner, not an in-place rewrite
- lld/23 (SDK LLD, frozen 2026-06-08 v1.2) predates phase/redactor/trail. Add a banner at its top: "SDK release surface as of <version> is specified in lld/36; §-level details here may be stale — lld/36 wins." (Matches this repo's supersede-banner convention, e.g. lld/19,20.) Do NOT rewrite lld/23 wholesale.

## SECTION OUTLINE (ship-now — leaner than the caching LLD)
1. **Context** — what this LLD is (the SDK RELEASE + no-op local-floor seam); the WS-A split (lld/36 ship-now vs lld/37 caching); why it unblocks WS-B/E deploy, connectors, WS-J, WS-H; NOT a re-plan of merged work. One paragraph.
2. **Scope & non-goals** — IN: release the merged phase+redactor+trail surface, version bump, re-vendor connectors, the typed no-op seam (flag + verdict enum + guard.py hook), lld/23 supersede-banner. OUT (lld/37): interpreter, bundle client, caching, poll, staleness/epoch/anti-rollback, crypto `[local-floor]` extra, durable meter journal. OUT (other WS): emitter (WS-I), differential runner (WS-J), hosted meter ledger (WS-H).
3. **Carried-forward status table** — SDK version 0.1.0 (RE-VERIFY); phase decorators PRESENT (guard.py:219-275); redactor PRESENT (redaction.py); `local_floor_enabled` ABSENT; connectors vendor byte-copies (cite the vendored paths); lld/23 frozen 2026-06-08. Each with file:line evidence RE-VERIFIED at author time.
4. **Architecture** — plain-terms lead: "ship the SDK we already built, add an off-switch-shaped plug for the future local floor." The guard.py hot path today (decorator -> `_build_request` -> redactor -> [SEAM] -> `_send` -> parse -> Decision); the seam is a no-op that falls through. Mermaid: the call flow with the seam marked.
4.1 **The released SDK surface** — the phase decorators (WS-B), the Tier-1 redactor + content_text seam (WS-E, ADR-032 ordering), the Decision/trail fields (WS-D), `TransportError.status_code`; what's public API vs internal; the `__version__`/`__contract__` story.
4.2 **The no-op local-floor seam** — config flag `local_floor_enabled` (default False); the verdict enum as a frozen typed contract; the guard.py hook signature + insertion point (after redactor, before `_send`); the three states (flag off -> hosted; flag on + no interpreter -> fail-secure to hosted; flag on + interpreter present -> lld/37's job). Explicitly: NO Signal.decision minting, ESCALATE falls through to `_send`, DenyOverrides untouched.
4.3 **Versioning & release** — semver bump rationale (additive -> minor); pyproject + `__version__` sync; `__contract__` pinned `/v1`; CI/tag/PyPI story (from lld/23 §9) — what actually happens on release.
4.4 **Re-vendor into connectors** — the byte-copy discipline; which modules each connector vendors; the checksum re-verify step; the stdlib-only/import-free constraint on the vendored subset; a table of connector -> vendored modules -> re-verify command.
5. **Security** — the seam is fail-secure by construction (off=hosted, on-without-interpreter=hosted, never local-allow); the redactor-before-seam ordering (ADR-032) preserved so no raw value could reach a future local floor before redaction; no new crypto/secret surface (S1); vendored-subset stays import-free (no identity/crypto dragged to the edge). Confirm no-raw-retention (NFR-7) unaffected.
6. **Compatibility & migration** — additive, no breaking change; existing `@guard.tool` callers byte-identical; a customer on 0.1.0 upgrading gets phase+redactor with no code change; the flag defaults off so no behavior change on upgrade.
7. **Scaling & latency** — NO latency change (every call still hosted, ~today's 0.6-1.2s typical / ~3s p99 non-co-located WAN per WS-0); the seam adds a single branch (~ns). State plainly: the latency WIN is lld/37's (caching); ship-now is a release + plug, not a perf change.
8. **Resiliency & recovery** — unchanged from today (fail-secure transport DENY on transport error, default-DENY on unparseable response — cite guard.py); the seam adds no new failure mode; `local_floor_enabled` off is the safe default.
9. **Test plan** — named tests: phase decorators carry the right phase (WS-B regression, keep green); redactor runs before the seam + before egress (WS-E regression); Decision parse + fail-secure defaults (regression); seam-off -> call reaches `_send` (no-op proof); seam-on-without-interpreter -> routes to hosted (fail-secure, NOT skip, NOT local-allow); version/contract pin asserted; **re-vendor checksum equality** test (vendored connector copy == released SDK module, byte-for-byte). Each unit + the connector integration tie-in. Existing SDK suite (74 tests) must stay green.
10. **Cross-references block (join keys)** — Implements: FR-1.7 (seam only; caching = lld/37), FR-3.4 (phase, lld/30), FR-3.13 (redactor, lld/29), NFR-4 (fail-secure). Decisions: ADR-029 (seam anticipates the local floor), ADR-032 (redactor ordering), ADR-031 (combine untouched). Shared contracts: `local_floor_enabled` (lld/28:394 semantics), the verdict enum (frozen here, consumed by lld/37 + WS-J), phase surface (lld/30), Decision/winning_source (lld/33). Upstream: HLD §6.2(a). Siblings: lld/23 (superseded-banner), lld/29, 30, 33 + lld/37 (fills the seam) + WS-I/WS-J/WS-H. **Forward link: lld/37 fills this seam (interpreter/bundle/crypto/meter-journal).**

## BUILD STAGING
- **This whole LLD is P1 / buildable now** — it commits no fail-open risk (off=today's all-WAN) and unblocks the dependent workstreams. There is no P2 in lld/36; the deferred work is lld/37 in its entirety.

## TENETS (carried from HLD §4 — verbatim intent)
1. Enforcement is local; the control plane is never on the action path. (The seam is where local enforcement WILL live; today it's a no-op plug.)
2. Fail secure, never fail open. (Every seam state routes to hosted or DENYs; never local-allow without an interpreter.)
6. The data boundary is the customer's to set. (Redactor-before-seam preserved; vendored edge stays stdlib-only.)
8. Honest staging. (lld/36 states plainly: this is a RELEASE + a PLUG, not the latency win — that's lld/37.)
- Tie-breaker A — Shape the contract once, additively. (The verdict enum + seam are frozen here so lld/37 fills them without touching the public API again.)
