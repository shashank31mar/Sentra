# API Spec — Cloud Connections (Connect Account Wizard)

**Status:** ✅ Implemented — backend `connections_service.py` + `api/routes.py`, console wired (live + mock parity). **Azure added** — service-principal connect + Cognitive Services discovery via `services/scanners/azure_scanner.py` (feature §7/§12); gcp still 409.
**Owner:** Security Controller (`src/security-controller`) + Console (`web/console`) + CDK
**Related:** LLD 21 §6.4 (Connections), `feature.md` §6 (Import Record group F), §11 (new API)
**Consumed by:** `web/console` Connect Account wizard (`features/connect/ConnectAccountPage.tsx`)

> This document fixes the request/response contract for the **cloud-account connection** domain so the
> console can be built ahead of the backend. It supersedes the thin sketch in LLD 21 §6.4 and aligns the
> shapes with the existing `/v1/discovery/*` endpoints already shipped in `discovery_service.py`.

> **Integration notes (as-built):**
> - The `CloudConnection` response additionally carries `created_at` / `updated_at` (additive; ignored by the console).
> - The controller has **no global error handler**, so errors are FastAPI `{ "detail": … }` rather than the §1
>   envelope: a `"CODE: message"` string for the connections domain, a `{ error, error_type, … }` dict for
>   custom exceptions, or a pydantic list for 422. The console normalizes all of these in `lib/http.ts`
>   (`normalizeErrorBody`) into `{ error, error_code }` so toasts show the real cause.
> - `GET /v1/discovery/agents?connection_id=…` is accepted but a **no-op filter** in the P0 policy-derived
>   read-model; the console sends it for forward-compat.
> - `POST /v1/discovery/import` does **not** yet return `policy_id` / `interception_status`; the import-result
>   drawer already tolerates their absence.

---

## 1. Conventions (inherited from LLD 21 §2)

- Base path `/v1`, JSON, ISO-8601 UTC timestamps, `X-Api-Key` injected at the edge (never by the SPA).
- **Error envelope:** `{ "error": string, "error_code": string, "request_id"?: string }`.
- All records are **tenant-scoped** (`feature.md` §14.2): `tenant_id` comes from the operator session, never
  the request body. Not surfaced to the console.
- Secrets (the assumed role / SP / SA) live in a vault; the connection stores a **reference + scopes only**
  (`feature.md` §6 group F, §10.3).

## 2. Enums

| Enum | Values | Notes |
|------|--------|-------|
| `cloud_provider` | `aws \| gcp \| azure \| unknown` | **aws** + **azure** are wired; **gcp** returns `409 PROVIDER_NOT_AVAILABLE` on create. |
| `connection_status` | `connecting \| connected \| error \| disconnected` | `connecting` = created, credential not yet verified. `connected` = the live read-only probe succeeded (AWS AssumeRole / Azure SP token). `error` = last test failed (`error` field set). |
| `scan_status` | `scanning \| idle` | mirrors `/v1/discovery/platforms`. |

## 3. The `CloudConnection` object

```jsonc
{
  "id": "conn-aws-acme",
  "cloud_provider": "aws",
  "status": "connected",                 // connection_status
  "account_ref": "global-prod-01",       // human label / account alias; null until known
  "external_id": "ext-acme-9f3c2a",      // minted by us; enforced in the role trust policy (confused-deputy guard)
  "aegion_principal_arn": "arn:aws:iam::531109575379:root", // the principal the customer trusts in their role
  "role_arn": "arn:aws:iam::5311...:role/AegionDiscoveryRole", // set by the operator after deploying the stack; null until then
  "scopes": ["bedrock-agent:List*", "bedrock-agent:Get*", "lambda:GetFunction"], // least-privilege, read-only
  "agents_visible": 14,                  // from the last successful test/scan; null until tested
  "last_scan": "2026-06-10T18:31:00Z",   // null until first scan
  "connected_at": "2026-06-10T18:22:00Z",// null until status=connected
  "error": null                          // human message when status=error, else null
}
```

## 4. Endpoints

### 4.1 `GET /v1/connections`
List the tenant's connections.
- **200:** `{ "connections": CloudConnection[] }`

### 4.2 `POST /v1/connections`
Create a connection and **mint the `external_id`** so the wizard can render the trust policy before the role exists.
- **Body:** `{ "cloud_provider": "aws" }`
- **201:** a `CloudConnection` with `status:"connecting"`, `external_id` + `aegion_principal_arn` + `scopes` populated, `role_arn:null`.
- **409 `PROVIDER_NOT_AVAILABLE`** when `cloud_provider` is not yet supported (gcp/azure in v1).

### 4.3 `GET /v1/connections/{id}`
- **200:** `CloudConnection` · **404 `NOT_FOUND`**

### 4.4 `PUT /v1/connections/{id}`
Attach/replace the connection's credential reference after the operator sets it up.
- **AWS body:** `{ "role_arn": "arn:aws:iam::5311...:role/AegionDiscoveryRole" }`
- **Azure body:** `{ "azure": { "subscription_id", "tenant_id", "client_id", "secret_ref" } }`
  — the SP's three GUIDs + a **vault reference** (Secrets Manager name/ARN) to the SP
  client-secret. The secret itself is never sent to or stored by the platform (feature §14);
  the projected connection echoes `azure_subscription_id` / `azure_tenant_id` / `azure_client_id`
  only (never the secret ref).
- **200:** updated `CloudConnection` (still `connecting` until tested) · **400 `VALIDATION_ERROR`**
  on a malformed ARN / GUID, or attaching Azure creds to an AWS connection (and vice-versa).

### 4.5 `POST /v1/connections/{id}/test`
Perform a live read-only probe with the stored credentials and confirm scope —
AWS: `sts:AssumeRole(external_id)` → `bedrock:ListAgents`; Azure: SP token →
Cognitive Services account/deployment list.
Flips `status` → `connected` on success (sets `connected_at`, `agents_visible`) or `error` on failure.
- **Body (optional):** `{ "role_arn": string }` — convenience to set + test in one call.
- **200:** `{ "ok": true,  "agents_visible": 14, "message": "AssumeRole OK · 14 agents visible" }`
- **200:** `{ "ok": false, "agents_visible": null, "message": "AccessDenied: external id mismatch" }` (test ran, role rejected — not an HTTP error)
- **404 `NOT_FOUND`** unknown connection.

### 4.6 `POST /v1/connections/{id}/scan`
Trigger discovery for this connection (async; mirrors the descoped `/v1/discovery/scan`).
- **202:** `{ "scan_id": "scan-9f2a", "status": "scanning", "discovered_count": null }`
- **409 `NOT_CONNECTED`** when `status != connected`.

### 4.7 `DELETE /v1/connections/{id}`
Disconnect (revoke the vault reference; retains imported agents).
- **204** · **404 `NOT_FOUND`**

## 5. Cross-references into existing endpoints

- `GET /v1/discovery/agents` gains an optional `connection_id` filter (`feature.md` §11) so the review
  table scopes to the just-connected account. **Backward compatible** — omitted ⇒ current policy-derived
  behavior. The console sends it only when present.
- `POST /v1/discovery/import` is unchanged (`{ agent_ids, enforcement_mode }` → per-agent results). The
  wizard hands off to the existing Import flow after a successful scan.

## 6. Wizard ↔ API sequence

```
choose AWS ──▶ POST /connections {cloud_provider}            → 201 {id, external_id, aegion_principal_arn, scopes}
deploy CFN  ──▶ (customer side, uses external_id)
paste ARN   ──▶ PUT  /connections/{id} {role_arn}            → 200
test        ──▶ POST /connections/{id}/test                  → 200 {ok, agents_visible}
connect+scan──▶ POST /connections/{id}/scan                  → 202 {scan_id}
            ──▶ navigate /import?connection={id}             → existing discovery/import review
```
