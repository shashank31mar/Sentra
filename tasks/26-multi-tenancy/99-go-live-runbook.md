# Multi-Tenancy Go-Live Runbook — WS-A data-plane enforce

**Status**: mechanism **complete and proven in tests**. The live-cutover steps below
are **human-gated** because they are outward-facing (live dev/demo) and/or
irreversible (brownfield purge). Build is done; flipping the live environment is a
decision, not a code change.

---

## What is already done (no action needed)

| Piece | State |
|---|---|
| Control plane: tenant tables, ALB-OIDC verify, operator→tenant + RBAC, `/v1/me`, credentials/tenants/members/invites APIs | implemented + tested |
| Data plane: `/v1/validate` resolves tenant from a **verified** agent JWT (shadow / enforce / `_unverified`) | implemented + tested |
| **SDK signing** (`aegion-guard[identity]`): ES256 keypair, `JwtSigner` (cache + silent refresh ≤15 min), Bearer on every validate, `provision` CLI | **implemented this change** |
| Cross-package proof: real SDK signer → controller verify → enforce routes; tampered/expired/foreign-key negatives | `src/security-controller/tests/test_sdk_identity_e2e.py` (green) |
| API Gateway forwards `Authorization` to `/v1/validate` | verified (HTTP_PROXY, no authorizer on the route) |
| Fleet ceiling on dev | `cdk/config/dev.yaml: tenant_identity_mode: shadow` |

**Effective mode = `min(env ceiling, tenant.identity_mode)`.** Dev's ceiling is
`shadow`, so no tenant enforces until the ceiling is raised — this is the safety latch.

---

## Gated cutover (run only with explicit go)

Pre-req: AWS creds (profile `sentra`, `us-east-1`; `ada cred update --once`).

1. **Deploy the tenant tables** (if not already on dev):
   `cdk deploy <StorageStack>` → creates `sentra-tenants`, `sentra-tenant-members`,
   `sentra-agent-credentials` (+ `kid-index`, `tenant-members-index`). Confirm with
   `aws dynamodb describe-table`.

2. **Create a clean tenant** (never `default`): `POST /v1/tenants {display_name}`
   (or seed the first one via the platform path). Set `identity_mode: shadow`.

3. **Provision a clean agent under that tenant**:
   - Scan/import the cloud account **under the new tenant** → canonical
     `agent_id = t_xxx-<cloud>-<slug>-<hash>`.
   - `python -m aegion_guard.provision --agent-id t_xxx-<cloud>-<slug>-<hash> --tenant-id t_xxx --register --api-base <controller-url> --header '<operator auth>'`
     → writes the private key (mode 600), captures the `kid`, emits a
     `*.identity.env` scaffold.

4. **Turn on signing for that agent**:
   - Update the agent's **vendored** `aegion_guard/` to the canonical SDK
     (`demo-agents/sdk/aegion-guard-python`) **or** `pip install 'aegion-guard[identity]'`.
   - Ship the private key; set `SENTRA_TENANT_ID`, `SENTRA_AGENT_KID`,
     `SENTRA_AGENT_PRIVATE_KEY_FILE`. No app code change — `AegionGuard()`
     auto-detects identity from env and signs.
   - Redeploy the agent.

5. **Verify in shadow**: controller logs `identity_state=verified` for that agent;
   behavior unchanged (shadow observes, never routes).

6. **Flip the tenant to enforce**: `PATCH /v1/tenants/t_xxx {identity_mode: enforce}`.
   To make it *bite*, raise the dev ceiling — `tenant_identity_mode: enforce` in
   `dev.yaml` + redeploy — **only after this tenant's credential coverage ≈ 100%**.
   Other tenants stay capped by their own row.

7. **Verify enforce**: signed calls ALLOW/route; an unsigned call from that tenant
   DENYs `IDENTITY_UNVERIFIED`, audited under `_unverified`.

## Acme demo agents — light up signing under tenant `acme` (WS-B / acme migration)

The three Acme agents already exist under tenant `acme` with **active credentials**
(verified live: `sentra-agent-credentials` has all three). The remaining step is to
make them actually *sign*. Each agent's flat id (`acme-payments-agent`, …) is a
delimited prefix of tenant `acme` (`acme-` == `tenant + "-"`), so it passes the
controller's canonical-id check with **no re-key**.

1. **Provision (rotates a fresh keypair, keeps old valid):**
   ```sh
   python demo-agents/registration/provision_acme_identity.py \
     --api-base "$SENTRA_API_BASE" --header "x-amzn-oidc-data: <operator token>"
   ```
   Writes private keys + `.identity.env` under `./.identity/` (mode 600) and prints
   the per-agent deploy env.
2. **Redeploy with the printed env** — the deploy paths are now wired to pass it
   through (inert if unset, so a non-signing deploy is unchanged):
   - AWS Lambda: `SENTRA_TENANT_ID/KID/PRIVATE_KEY` → `deploy_payments_agent.py`.
   - Azure: same trio → `azd up` (threaded through `infra/main.bicep` →
     `identitySettings` app-settings).
3. **Verify in shadow**, then flip `acme` to enforce (below) once all three show
   `identity_state=verified`.

## New WS-B flags (default-off — no behavior change until set)

| Flag (env) | Default | Effect when set |
|---|---|---|
| `S3_EXPLICIT_TENANT_PREFIX` | `false` | New policy writes use `tenants/{tid}/policies/agents/…`; reads dual-read both layouts. Run `scripts/migrate_s3_policy_prefix.py` (then `--delete-old` after confirming reads). |
| `IDENTITY_FALLBACK_WINDOW_SECONDS` | `0` (disabled → immediate DENY) | Residual uncredentialed-agent grace window during a per-tenant enforce flip; alarmed (`IdentityFallback`), expires to DENY. Set e.g. `86400` during the flip, drive to `0` as coverage → 100%. |

Both need the `sentra-identity-fallback` table deployed (`cdk deploy <StorageStack>`,
added this change). Residual list for ops: `GET /v1/identity/residual-agents`.

## Brownfield `default` discard (B9) — inventory now, purge gated

```sh
python scripts/migrate_brownfield.py inventory --out default_inventory.json   # safe, read-only
# attach default_inventory.json to the sign-off, then ONLY with explicit go:
python scripts/migrate_brownfield.py purge --confirm-no-customer-data         # IRREVERSIBLE
```
Live inventory (2026-06-24) shows **0 credentials under `default`** — consistent
with the "dev data" premise, but the purge still requires the explicit sign-off.

## Rollback

- Per-tenant: `PATCH identity_mode` back to `shadow`/`off` (propagates ≤ 30 s, the
  mode cache TTL).
- Fleet kill-switch: `tenant_identity_mode = shadow|off` (env ceiling) caps everyone.

---

## Brownfield — the existing `default-*` fleet (separate, irreversible, needs sign-off)

Every current agent is `default-<cloud>-<slug>-<hash>` and `agent_id` is immutable, so
it **cannot** hold a real-tenant credential without a re-key — the cascade migration the
LLD rejected (§B9). Decision on record: **re-import under real tenants, then purge
`default`.** The purge is irreversible and runs **only behind explicit human sign-off**
re-confirming no real customer data lives under `default`.

Until that sign-off: leave the `default` fleet on the legacy path (untouched) and prove
enforce on the **clean tenant** only. Do **not** run the purge as part of this rollout.
