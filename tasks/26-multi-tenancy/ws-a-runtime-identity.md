# WS-A: Runtime Tenant Identity (asymmetric JWT)

**Parent LLD**: [lld/26-multi-tenancy.md](../../lld/26-multi-tenancy.md) §3
**Status**: ✅ Complete (2026-06-24) — controller verify path + credential APIs (8a34abd), agent SDK ES256 signing + provisioning + cross-package e2e (5f90c03)
**Owner**: TBD

> This is the largest new build and the one that converts the system from "default-tenant" to genuinely multi-tenant on the data path. It ships in **shadow** first.

## Dependencies

- **Depends on**: **WS-D** (`resolve_operator_tenant` + `require_role` — the credential APIs are operator-authed and must verify the operator's tenant owns the `agent_id`). Canonical-id scheme from `features/multicloud-agent-import`. SDK keypair from LLD-23.
- **Blocks**: the WS-B per-tenant **enforce** flip (credentials must exist before flip — LLD §7.1.2). WS-C console (`tenantOf()` becomes real once A3 lands). WS-E metric `tenant_id` dimension.
- **Shared**: [tenancy.py](../../src/security-controller/app/utils/tenancy.py).

---

## Trust model (read before coding)

- **Asymmetric** keys: each agent holds a **private** signing key; Sentra stores only the **public** key → Sentra can verify but **never mint** an agent token. A compromised controller DB cannot forge agent identity.
- **Two-phase**: canonical `agent_id` baked into the SDK scaffold **at import** (during scan/discovery); keypair generated + public key registered **at deploy time**.
- The controller derives `(tenant_id, agent_id)` from the **verified** token, then cross-checks the body's self-asserted `agent_id`.

## Tasks

### A1 — `sentra-agent-credentials` table (new)

PK `tenant_id` (S), SK `key_id` (S) = `{agent_id}#{kid}` (multiple active keys per agent for rotation).

| Attribute | Type | Notes |
|---|---|---|
| `tenant_id` (PK) | S | Owning customer |
| `key_id` (SK) | S | `{agent_id}#{kid}` |
| `kid` | S | Globally-unique UUID — **its own attribute** (it is the GSI PK) |
| `agent_id` | S | Canonical, tenant-scoped |
| `public_key` | S | PEM/JWK, ES256 (P-256) |
| `alg` | S | `ES256` (fixed; reject others) |
| `status` | S | `active` \| `rotating` \| `revoked` |
| `not_before` / `not_after` | N | Validity window (epoch ms) |
| `created_at` / `created_by` | N / S | Audit |

- **GSI `kid-index`**: PK `kid` → O(1) lookup at verify (token header carries only `kid`). Intentionally **not** tenant-partitioned — it is the one pre-tenant lookup that *establishes* the tenant. `kid` is a UUID so no hot partition by tenant.
- Add to CDK storage stack, LLD-06, and the WS-D deletion purge list.
- **IAM grant + env wiring (do not skip — "deploys clean, 500s at runtime"):** [storage_stack.py](../../cdk/stacks/storage_stack.py) defines tables; [compute_stack.py](../../cdk/stacks/compute_stack.py) wires table names into the task-role env and grants access. Grant the controller task role **read/write on `sentra-agent-credentials` and query on `kid-index`**, and inject the table name as an env var, the same way the existing tables are wired. Verify must read the GSI; issuance writes the base table.

### A2 — Issuance & rotation APIs (operator-authed via WS-D)

| Method & path | Purpose | Auth |
|---|---|---|
| `POST /v1/agents/{agent_id}/credentials` | Register a public key. Body `{public_key, alg, not_after?}` → returns `{kid}`. | Operator session; tenant must own `agent_id` |
| `GET /v1/agents/{agent_id}/credentials` | List keys (status/kid/validity) — no private material. | Operator session |
| `POST /v1/agents/{agent_id}/credentials/{kid}/rotate` | Mark `rotating`; caller registers new key; old stays valid until `not_after`. | Operator session |
| `DELETE /v1/agents/{agent_id}/credentials/{kid}` | Revoke immediately (`status=revoked`). | Operator session |

- **Ownership check**: every endpoint asserts the operator's `current_tenant()` (from WS-D dependency) **owns** `agent_id`. **Do NOT use a bare `agent_id.startswith(tenant)`** — it is delimiter-unsafe (`t_01` falsely matches `t_01hxyz-aws-…`). Use `agent_id.startswith(tenant + "-")`, or better, **look up the registry row and compare its `tenant_id` field** (authoritative). Mismatch → `403`.
  - ⚠️ **Brownfield interaction (blocking, see index / WS-B migration task):** every *existing* agent has `agent_id` beginning with `default-` (imports ran under `current_tenant()="default"`). An operator in a real tenant `t_real` cannot pass this check for a `default-…` agent. The pre-existing population needs the migration decided in the brownfield task before its agents can hold real credentials.
- **Rotation is overlap-based**: register new → both `active` → flip traffic → revoke old. No controller-side private keys ever exist.

### A3 — Verify dependency + `set_current_tenant` wire (THE gap-closer)

A FastAPI dependency on `/v1/validate` (and any other agent-facing route) does verify-then-set. **`set_current_tenant()` has no request-path caller today — this is the missing wire.**

```python
# app/api/deps.py (new) — conceptual
SKEW = 60  # seconds clock skew; matters with <=15-min tokens

async def resolve_tenant_from_jwt(request) -> TenantContext:
    token = extract_bearer(request)
    if not token:
        return TenantContext.unverified()                 # fail-secure (A4 / §8)
    kid = unverified_header(token)["kid"]
    cred = get_credential_cached(kid)                      # in-proc LRU, NOT a per-call GSI hit
    if cred is None or cred.status != "active":
        return TenantContext.unverified()
    now = time.time()
    if not (cred.not_before - SKEW <= now <= cred.not_after + SKEW):
        return TenantContext.unverified(claimed_tenant_id=cred.tenant_id)
    try:
        claims = jwt.verify(token, cred.public_key, alg="ES256",
                            audience="sentra-controller", leeway=SKEW)
    except JWTError:
        return TenantContext.unverified(claimed_tenant_id=cred.tenant_id)
    if claims["tid"] != cred.tenant_id:                    # bind token<->key
        return TenantContext.tampered(claimed_tenant_id=cred.tenant_id)   # IDENTITY_TAMPERED
    if not claims["sub"].startswith(claims["tid"] + "-"):  # canonical-id prefix — DELIMITED
        return TenantContext.mismatch()                                  # IDENTITY_MISMATCH
    return TenantContext(tenant_id=claims["tid"], agent_id=claims["sub"])
```

> **Delimiter-safety (required):** use `startswith(tid + "-")`, never a bare `startswith(tid)`. `sub` is `{tenant}-{cloud}-{slug}-{hash}`, so without the trailing `-` a short tenant id (`t_01`) would falsely match a longer one (`t_01hxyz-aws-…`). This is a tenant-isolation check — it must not rely on ULID collision-improbability.

**Wiring into the real route** ([routes.py:56,88](../../src/security-controller/app/api/routes.py#L56)). The handler is `validate_tool_call(request: ValidationRequest, http_request: Request)` and delegates via `return await validation_service.validate_tool_call(request)`. The `set_current_tenant` wrap goes around **that** delegation:

```python
# app/api/routes.py validate_tool_call — conceptual delta (real names)
async def validate_tool_call(request: ValidationRequest,
                             ctx = Depends(resolve_tenant_from_jwt)):
    token = tenancy.set_current_tenant(ctx.tenant_id)      # <- THE missing wire
    try:
        if request.agent_id != ctx.agent_id:               # cross-check body (ValidationRequest.agent_id)
            return deny(IDENTITY_MISMATCH)
        return await validation_service.validate_tool_call(request)   # real delegation; now tenant-scoped
    finally:
        tenancy.reset_current_tenant(token)
```

**The JWT** (agent-side, LLD-23 SDK signs it):
```
header: { "alg":"ES256", "kid":"<uuid>", "typ":"JWT" }
claims: { "iss":"aegion-guard", "sub":"<{tenant}-{cloud}-{slug}-{hash}>", "tid":"<tenant_id>",
          "iat":..., "exp":..., "aud":"sentra-controller" }
```
> `sub` is the canonical `agent_id` and includes the 8-char native-resource hash that [`canonical_agent_id`](../../src/security-controller/app/services/discovery_service.py#L58) appends — `{tenant}-{cloud}-{slug}-{hash}`, **not** the bare `{tenant}-{cloud}-{slug}` shown in early LLD drafts. Implementers must not hardcode the 3-segment shape.

`tid` MUST equal the credential row's `tenant_id` and MUST be a **delimited** prefix of `sub` (`tid + "-"`). Either failing ⇒ reject.

**Shadow mode**: in `shadow`, verify + log resolved `tid` but do **not** route onto it (effective mode = `min(env ceiling, tenant.identity_mode)`; see WS-B). An uncredentialed agent keeps the legacy path — no brick, no exposure.

### A3.1 — Public-key cache (hot-path cost — load-bearing)

`resolve_tenant_from_jwt` MUST NOT hit the `kid-index` GSI on every `/v1/validate` (highest-QPS path; a global GSI funnels all tenants through one partition).

- **In-process LRU keyed by `kid`**, caching `{public_key, tenant_id, agent_id, status, not_before, not_after}`. Public keys are immutable per `kid`.
- `kid` misses **negatively cached briefly** to blunt enumeration (§9.4 tripwires).
- **Cache TTL ≤ 60s** — it is a *second* revocation budget alongside token lifetime. Across N instances the honest revocation bound **is** this TTL (a local bust on the instance serving a revoke is NOT load-bearing — don't rely on it).
- To get below TTL without per-request DDB reads: a **`revoked-since` shared signal** — one small DDB item per region carrying a monotonically-bumped revocation epoch, refreshed at most once per short interval (not per request); any cache entry created before the current epoch is invalidated.
- Net: ~zero per-request DDB reads; effective bound = `min(token TTL, cache TTL, refresh interval)`.

### A4 — `IDENTITY_UNVERIFIED` audit-tenant gap

A request with no/invalid credential has no proven tenant, but fail-secure DENY must still be audited — and **must not** leak into the `default` tenant's trail.

- Audit unverified requests under a **reserved system tenant `_unverified`** (never assignable; validated at tenant-creation in WS-D).
- If a `kid` *was* found but verify failed (bad sig/expired): **dual-tag** — stored under `_unverified` but annotated with `claimed_tenant_id` = the credential row's tenant, so a tenant's SOC sees spoof attempts against its agents.

### A5 — Token lifetime + SDK refresh (coordinate with LLD-23)

Short token lifetime (**≤15 min**) with SDK-side silent refresh from the held private key, so revocation propagates fast without a per-request revocation list.

## Error model (LLD §8)

| Condition | Response |
|---|---|
| No `Authorization` token | `IDENTITY_UNVERIFIED` → DENY; audit `_unverified`. Shadow: allow + log. |
| `kid` not found / revoked | `IDENTITY_UNVERIFIED` |
| Bad sig / expired / wrong `aud` | DENY; audit `_unverified` + `claimed_tenant_id` |
| `tid` ≠ credential's `tenant_id` | DENY `IDENTITY_TAMPERED` (key reuse across tenants) — **high-severity alert** |
| `tid` not a prefix of `sub` | DENY `IDENTITY_MISMATCH` |
| body `agent_id` ≠ verified `agent_id` | DENY `IDENTITY_MISMATCH` |

## Acceptance criteria

- [x] `sentra-agent-credentials` + `kid-index` GSI deployed; in purge list; **controller task role granted RW + GSI query, table name in task env** (CDK).
- [x] 4 credential APIs live; ownership-checked via **registry-row `tenant_id` compare or `tenant + "-"` prefix** (`403` on foreign agent); ES256-only.
- [x] `resolve_tenant_from_jwt` dependency wired into `/v1/validate`; `set_current_tenant` called per request in `try/finally`.
- [x] Public-key LRU + `revoked-since` signal; **no per-request GSI read** under load test.
- [x] Shadow mode verifies + logs without routing; uncredentialed agents unaffected.
- [x] `_unverified` audit bucket with `claimed_tenant_id` dual-tag (covered by WS-B isolation test).
- [x] Negative tests for all six error rows return the right code + DENY.

## Cross-references

- LLD §3 (design), §7.1.2 / §7.2 (shadow→enforce sequencing), §3.7 (`_unverified`), §10 Q1 (online revocation for dedicated).
- LLD-23 (SDK signs JWT, silent refresh), `features/multicloud-agent-import` (canonical id), `features/cedar-policy` (consumes `(tenant_id, agent_id)`).
