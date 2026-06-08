# Workstream 22: SOC Console Frontend (React SPA + nginx on ECS)

**Status:** ✅ DEPLOYED 2026-06-07 — live at https://console.aegionai.ai (Cognito-gated, `*.aegionai.ai` TLS, console task HEALTHY, dashboard auth intact).

> **M7 deploy log:** Storage (ECR `sentra/console`) ✅ → image push (`latest`+`milestone-1`) ✅ → Network+Compute ✅ (one fix: em-dash in `ConsoleTaskRole` description → IAM rejects non-ASCII; replaced with `-`, redeployed clean) → secret `sentra-mvp-console-api-key` populated from Usage-Plan key + console force-redeploy ✅. **Smoke:** `https://console.aegionai.ai` → `302` to Cognito with `redirect_uri=…console.aegionai.ai/oauth2/idpresponse`; TLS `ssl_verify=0`, cert `CN=*.aegionai.ai`; dashboard (raw ALB DNS) still `302`→Cognito (default_actions untouched).
**Owner:** Founder
**Start Date:** 2026-06-07
**LLD Reference:** [lld/21-api-inventory-for-ux.md](../lld/21-api-inventory-for-ux.md)
**Depends on:** [WS-21 SOC Console APIs](workstream-21-soc-console-apis.md) (P0 complete), [WS-16 API GW VPC Link](workstream-16-apigw-vpc-link-networking.md) (public `/v1/*` functional)
**Designs:** `.kombai/canvas/aegion-soc.canvas` (Overview, Threats, Audit Trail, Agent Inventory, Agent Detail, Discovery, Policy Library, Cedar Builder)

---

## Overview
Build the production SOC console as a **single-page React app** and ship it as an **nginx container on the existing ECS Fargate cluster**, behind the **Public ALB + Cognito**. nginx serves the static build and reverse-proxies `/v1/*` to the **public API Gateway** (`https://iw3limi4k7.execute-api.us-east-1.amazonaws.com/prod`), injecting `x-api-key` server-side so the key never reaches the browser.

### Locked decisions
1. **Routing/serving:** nginx (static SPA + `/v1` reverse-proxy + SPA history fallback).
2. **Repo layout:** single dedicated app at `web/console/` (no JS workspace yet — landing `frontend/` is temporary; revisit when a 2nd durable frontend appears).
3. **Compute:** **ECS Fargate** — add a 4th service `console` to cluster `sentra-mvp-cluster` via the existing `service_configs` loop in `cdk/stacks/compute_stack.py`. The loop is *mostly* config-driven but has two hardcoded spots that need targeted edits (NOT pure config): the `security_group_map` literal dict (compute_stack.py:1326) and the listener-dependency branch (`if service_name == "dashboard"`, :1369). See Task 22.20.
4. **ALB routing (resolved per review):** **host-based** — `console.<domain>` vs `dashboard.<domain>`. Chosen because it leaves the working dashboard listener `default_actions` **untouched** (lowest regression risk on the live Cognito auth) and gives the console its own Cognito callback URL. Prerequisite: a console hostname + ACM cert SAN (see Task 22.21). Avoid "console-as-default" until the dashboard is being retired.
5. **API-key model (resolved per review):** dedicated console api-key with value in Secrets Manager (independent rotation, no post-deploy script).
6. **nginx proxy target (resolved per review):** public API Gateway (identical contract + free Usage-Plan throttling).

### Goals
1. `web/console` SPA renders all WS-21 screens against live `/v1` data.
2. `x-api-key` is injected by nginx from Secrets Manager — **never** present in client JS.
3. Human access gated by existing **Public ALB + Cognito** (same as dashboard).
4. Dashboard (Streamlit) + security-controller services untouched.

### Success Criteria
- [ ] `npm run build` in `web/console` produces a static bundle; `npm run dev` runs with a `/v1` proxy to the public API GW.
- [ ] Browser network tab shows **no** `x-api-key` on any request originating from client code (nginx adds it on the proxied hop).
- [ ] Loading the console URL unauthenticated triggers the Cognito challenge (ALB OIDC), same as dashboard.
- [ ] Overview, Threats, Audit, Agents, Discovery, Policies screens fetch real data with correct pagination (`next_token`) and error-envelope handling.
- [ ] `cdk diff` adds exactly: 1 ECS service + 1 task def + 1 target group + **1 new `CfnListenerRule` (carrying its own `authenticate-cognito` action, host-condition)** + 1 ECR repo + 1 Secrets Manager secret + 1 API key + 1 SG (or SG-map entry). The existing listener `default_actions` (dashboard auth) shows **no change**; **no replacement** of RestApi/ALB/Cognito.
- [ ] The new console listener rule includes an `authenticate-cognito` action (order 1) before the forward (order 2) — a bare forward rule would silently bypass the Cognito gate (security regression). Verified by the unauthenticated-challenge smoke step.

---

## Architecture

```
PROD
  Browser ─► Public ALB (HTTPS)
              ├─ CfnListenerRule: host=console.<domain> [auth-cognito → forward] → console_tg ─► ECS "console" (nginx)
              │                                     ├─ serves /  → static SPA (index.html fallback)
              │                                     └─ proxies /v1/* → API GW (public) + inject x-api-key
              └─ default_actions [auth-cognito → forward] → dashboard_tg ─► ECS "dashboard" (Streamlit)   [UNTOUCHED]
  API GW (public) ─► VPC Link ─► NLB ─► Private ALB ─► ECS "security-controller"

DEV
  Vite dev server (5173) ── proxy /v1 ──► https://iw3limi4k7…/prod/v1  (x-api-key from .env.local, server-side proxy)
```

**Security posture (MVP):** two layers — (1) ALB Cognito gate for humans; (2) Usage-Plan api-key for the API, injected server-side. Per-user attribution is via Cognito identity headers the ALB forwards; api-key is a shared service credential, deliberately kept out of the browser.

---

## Real construct/name references (verified via code read)
| Thing | Real name | File |
|---|---|---|
| ECS cluster | `self.ecs_cluster`, name `sentra-mvp-cluster` | `cdk/stacks/compute_stack.py` |
| Service config loop | `service_configs` dict → `for service_name, config in service_configs.items()` | compute_stack.py |
| Image pattern | `ecs.ContainerImage.from_registry(f"{account}.dkr.ecr.{region}.amazonaws.com/sentra/{svc}:latest")` | compute_stack.py |
| Public ALB | `self.public_alb`; HTTPS listener `self.public_https_listener` (`elbv2.CfnListener`) | compute_stack.py |
| Dashboard TG | `self.dashboard_tg` (port 8501) | compute_stack.py |
| Cognito refs | `cognito_stack.user_pool(.user_pool_arn)`, `.user_pool_client(.user_pool_client_id)`, `.user_pool_domain(.domain_name)` | cognito_stack.py |
| API key / plan | `self.api_key = apigateway.ApiKey(...)`, `self.usage_plan` | api_stack.py |
| RestApi | `SentraApi` (`apigateway.RestApi`), stage `prod` | api_stack.py |
| Cross-stack args | `ComputeStack(config, network_stack, storage_stack, cognito_stack)` | compute_stack.py |
| Config keys | `compute.ecs_cluster|ecr|ecs_tasks|alb`, `api_gateway`, `cognito` | cdk/config/{dev,prod}.yaml |
| **Public HTTPS listener** | `self.public_https_listener` is a raw **`elbv2.CfnListener`** (comment at :758: "L2 doesn't support authenticate-cognito"); Cognito lives in `default_actions` (authenticate-cognito order=1 → forward dashboard order=2). **No L2 `add_rule`/`AuthenticateCognitoAction` available** → console route = a hand-built `CfnListenerRule`. | compute_stack.py:759 |
| **SG map (hardcoded)** | `security_group_map` literal dict (:1326) keyed by the 5 known services → `security_groups=[security_group_map[service_name]]` (:1349). Unmapped service = `KeyError` at synth. | compute_stack.py:1326 |
| **Listener-dependency branch** | `if service_name == "dashboard": depend(public_https_listener) else: private_http_listener` (:1369). Console needs the **public** listener → branch must become `in ("dashboard","console")`. | compute_stack.py:1369 |

---

## Milestone 1 — App scaffold (`web/console`)
**Task 22.1 — Create Vite + React 19 + TS app**
- Files: `web/console/{package.json,tsconfig*.json,vite.config.ts,index.html,eslint.config.js}`, `src/main.tsx`, `src/app/App.tsx`.
- Deps: `react@19`, `react-dom@19`, `react-router-dom@7`, `@tanstack/react-query@5`, `chart.js`, `react-chartjs-2`, `@tabler/icons-react`. Dev: `vite@8`, `@vitejs/plugin-react`, `@tailwindcss/vite`, `tailwindcss@4`, `typescript`, eslint set (mirror `frontend/`), optional `msw`.
- `vite.config.ts`: `react()` + `tailwindcss()` + `server.proxy['/v1'] → env VITE_API_BASE` with `x-api-key` header from `VITE_API_KEY` (dev only, via a proxy `configure` hook so the key is added server-side, not bundled).
- **Acceptance:** `npm run dev` boots; `npm run build` (`tsc -b && vite build`) green.

**Task 22.2 — Tailwind v4 theme tokens from canvas**
- File: `src/styles/index.css` with `@import "tailwindcss";` then `@theme { … }` capturing canvas tokens: `--color-bg #010B13`, panel `#06101A/#0B141C`, neon cyan `#0FFFFF`, pink `#FF0080`, green `#22E58B`, amber, text `#8DA2AE`, label `#7C909E`; fonts Space Grotesk (display) + IBM Plex Sans/Mono; radii. Global resets wrapped in `@layer base` (v4 requirement).
- **Acceptance:** sample element using tokens renders; no unlayered reset clobbering utilities.

## Milestone 2 — App shell (reused chrome)
**Task 22.3 — Providers + Router** — `QueryClientProvider`, `BrowserRouter`, route table → screens; root `<AppLayout>` = NavRail + TopBar + `<Outlet/>`.
**Task 22.4 — `components/ui` primitives + chrome** — `NavRail` (Monitor/Assets/Onboard/Govern), `TopBar` (breadcrumb, cloud selector, ⌘K search, user), `Card`, `Badge`, `StatusDot`, `Button`, `DataTable`, `ChartCard`. Mirror canvas markup → JSX; tokens not hex.

## Milestone 3 — Data layer
**Task 22.5 — `lib/http.ts`** — `fetch` wrapper: base `/v1`; **no api-key client-side**; parse error envelope `{error,error_code,request_id}`; `paginate()` threading `next_token`→`cursor`.
**Task 22.6 — `types/` from LLD §11** — enums (`cloud_provider`, `platform`, `decision`, `risk`, `threat_type`) + DTOs per endpoint. **Honor LLD §11.2 nullability explicitly**: model nullable fields (e.g. `trust_score: number | null`, optional enrich fields) as nullable in TS so the UI renders empty/partial fleets without crashing — do not assume non-null.
**Task 22.7 — `lib/api/*` + `lib/query/*`** — one client + TanStack hooks per domain. Polling for Overview/Threats.
**Task 22.8 — MSW mocks** to LLD shapes; toggle to live via `VITE_API_BASE`.

### API consumption matrix (from WS-21 / LLD-21)
| Screen | Endpoints |
|---|---|
| Overview | `GET /v1/metrics/overview`, `/metrics/platform-distribution`, `/metrics/decisions-timeseries` |
| Threats | `GET /v1/decisions` (`{decisions,total,next_token}`), `POST /v1/quarantine/{session_id}` |
| Audit Trail | `GET /v1/logs`, `GET /v1/logs/conversation/{conversation_id}`, **`POST /v1/decisions/{decision_id}/verdict`** (FP/FN review — verified at api_stack.py:861) |
| Agent Inventory | `GET /v1/agents` (`enrich=true`) |
| Agent Detail | `GET /v1/agents/{id}`, `/agents/{id}/tools`, `/sessions/{sid}/decisions` |
| Discovery | `GET /v1/discovery/{summary,platforms,agents}`, `POST /v1/discovery/import` |
| Policies / Cedar | `GET/POST/PUT/DELETE /v1/policies[/{id}]`, `GET /v1/sigma-rules`, `PATCH /v1/sigma-rules/{id}` |

> **Not exposed by WS-21 through the API Gateway (verified against `api_stack.py`) — descoped for this cut:**
> - `GET /v1/sessions/{sid}/signals` — only `…/decisions` is wired. Agent Detail's raw-signals/debug panel is **out** until a WS-21 follow-up exposes it (a developer hitting it now gets 403 from API GW for an unknown resource).
> - `POST /v1/discovery/scan` — explicitly descoped in WS-21 (only `agents/summary/platforms/import` exist). The Discovery "trigger scan" button has no backend → render it disabled with a "coming soon" tooltip, or drop it this cut.
> Both require a WS-21 follow-up task before the corresponding UI is wired.

## Milestone 4 — Screens
**22.9 Overview** · **22.10 Threats** · **22.11 Audit Trail** (incl. FP/FN Decision Review) · **22.12 Agent Inventory** · **22.13 Agent Detail** · **22.14 Discovery** · **22.15 Policy Library + Cedar Builder**.
- Each: build from the matching canvas node, wire its endpoints, loading/empty/error states.

## Milestone 5 — Containerization
**Task 22.16 — `docker/console/Dockerfile` (multi-stage)** — Stage 1 `node:22-alpine` build; Stage 2 `nginx:1.27-alpine` serve.
**Task 22.17 — `docker/console/nginx.conf`** — SPA fallback `try_files $uri /index.html`; `location /v1/ { proxy_pass <API GW>/v1/; proxy_set_header x-api-key "$SENTRA_API_KEY"; }` (key via `envsubst` from ECS secret).
- **CSP (concrete baseline, not a checkbox):** SPA calls only same-origin `/v1` (proxied) and loads Chart.js (no external CDN at runtime). Ship:
  `Content-Security-Policy: default-src 'self'; img-src 'self' data: https://i.pravatar.cc; font-src 'self' https://fonts.gstatic.com; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'`.
  (The Tabler webfont + Google Fonts links in `index.html` should be **self-hosted** in prod to keep `script-src 'self'` clean and drop the CDN allowances; note this as a build step.) Plus `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`.

## Milestone 6 — CDK infra (reuse existing stacks)

> **Status: implemented + validated 2026-06-07.** `cdk synth` EXIT=0. `cdk diff` (Network + Storage + Compute) is **additive** with only three modifications to existing resources, all intended:
> 1. `PublicHttpsListener` — **`Certificates` only** swapped self-signed → `*.aegionai.ai`. **`default_actions` (dashboard auth) NOT in the diff** = untouched (host-based routing as designed).
> 2. `TaskExecutionRole` policy — additive `secretsmanager:GetSecretValue` on the console secret + console log perms.
> 3. Callback Lambda + custom resource — multi-host (adds `console.aegionai.ai` + `dashboard.aegionai.ai` to Cognito callback/logout URLs).
>
> New `[+]`: ConsoleSG (+2 rules), `sentra/console` ECR repo, ConsoleTargetGroup, ConsoleListenerRule (own order-1 authenticate-cognito), ConsoleApiKeySecret, ConsoleTaskRole, ConsoleLogGroup, ConsoleTaskDef, ConsoleService, ConsoleUrl. Cognito: no diff. RestApi/ALB: not replaced. (Synth bug fixed: `CfnListenerRule.session_timeout` must be `int`.)

### Task 22.17b — Domain & TLS prerequisite (`aegionai.ai`, GoDaddy) — RESOLVES the host-routing blocker
The org owns **`aegionai.ai`** at GoDaddy. Use it for host-based routing AND to retire the current self-signed ALB cert.
- **Current state:** ALB imports a **self-signed** cert (`compute_stack.py:567`, hardcoded ARN `…/70506764-…`); Cognito callbacks point at the raw ALB DNS via a custom-resource Lambda (`compute_stack.py:956-1051`, `https://{alb_dns}/oauth2/idpresponse`). `route53` config has only a private zone `sentra.internal`.
- **DNS (keep at GoDaddy — simplest):** add CNAMEs → ALB DNS (`<public-alb>.us-east-1.elb.amazonaws.com`):
  - `console.aegionai.ai` → ALB  (the console host)
  - `dashboard.aegionai.ai` → ALB  (clean host for the existing Streamlit app; optional but recommended)
  - *(Alt: delegate `aegionai.ai` or a `aws.aegionai.ai` subdomain to a Route53 hosted zone for ALIAS/apex + CDK-native ACM DNS validation.)*
- **TLS (ACM, us-east-1):** request a cert for **`*.aegionai.ai`** (wildcard covers both hosts), **DNS-validated** by adding the ACM CNAME at GoDaddy. Then replace the self-signed ARN at `compute_stack.py:567` with the new cert ARN (move it to `config.compute.alb.certificate_arn`). Listener already reads `self.alb_certificate` (:766) — single-line swap.
  - **Provisioned 2026-06-07** (pending DNS validation): cert ARN `arn:aws:acm:us-east-1:531109575379:certificate/522142fe-acef-4a68-8c59-847fc28b9470`.
  - **ACM validation CNAME** to add at GoDaddy: name `_56d2301c51d30803977ddc5859fceacb` (label only; GoDaddy appends `.aegionai.ai`) → value `_67624683353e84c58e22c9de5224a861.jkddzztszm.acm-validations.aws`.
  - **App CNAME**: `console` → `sentra-public-alb-1320390749.us-east-1.elb.amazonaws.com` (public ALB DNS).
- **Cognito callbacks — this is a Lambda *code* edit, not an input change.** The inline callback Lambda **builds** the URLs internally from `alb_dns_name` (`compute_stack.py:983-984`: `callback_urls = [f"https://{alb_dns_name}/oauth2/idpresponse"]`, `logout_urls = [f"https://{alb_dns_name}/"]`), and `cognito_stack._get_callback_urls` (cognito_stack.py:177, confirmed to exist) does the same. Passing new CustomResource *properties* alone leaves the URLs unchanged — the handler body must be rewritten to accept/emit explicit host lists. Target set:
  - callbacks: `https://console.aegionai.ai/oauth2/idpresponse`, `https://dashboard.aegionai.ai/oauth2/idpresponse`
  - logout: `https://console.aegionai.ai/`, `https://dashboard.aegionai.ai/`
- **Config:** add `compute.alb.certificate_arn` and `compute.alb.console_host: console.aegionai.ai` (+ `dashboard_host`) to `dev.yaml`/`prod.yaml`.
- **Acceptance:** `https://console.aegionai.ai` resolves to the ALB, serves a valid (non-self-signed) cert, and triggers the Cognito challenge.

**Task 22.18 — ECR repo `sentra/console`.**
**Task 22.19 — API key in Secrets Manager** — dedicated console api-key with explicit `value` from a new secret; associate to `self.usage_plan`; reference same secret in console task `secrets={"SENTRA_API_KEY": ...}`.
**Task 22.20 — `console` ECS service (loop edits, NOT pure config)** — add `service_configs["console"]` (image `sentra/console:latest`, port 80, cpu/mem from config, `secrets={"SENTRA_API_KEY": ...}`, log group). **Required code edits the loop does not absorb:**
- **22.20a — SG:** add a `console_sg` in `network_stack.py` (egress 443 to the internet for the public API GW hop; ingress from `public_alb_sg` on 80) **and** add `"console": network_stack.console_sg` to the `security_group_map` dict (compute_stack.py:1326). Without this, synth throws `KeyError`. (Or, lowest-effort, map console to an existing permissive SG — but a dedicated SG is cleaner.)
- **22.20b — listener dependency:** change the branch at compute_stack.py:1369 from `if service_name == "dashboard"` to `if service_name in ("dashboard", "console")` so the console service depends on `public_https_listener`.

**Task 22.21 — `console_tg` + hand-built Cognito listener rule** — new `console_tg` as an **L2 `elbv2.ApplicationTargetGroup`** (port 80, health `/`, `target_type=ip` for Fargate awsvpc). **Use L2, not `CfnTargetGroup`** — the service-loop binds via `service.attach_to_application_target_group()` (compute_stack.py:1367), which requires an L2 TG; a raw `CfnTargetGroup` would force a custom attachment path in 22.20. Mixing L1 rule + L2 TG is fine: reference `console_tg.target_group_arn` in the rule. Because `self.public_https_listener` is a raw **`CfnListener`** (no L2 `add_rule`), add a separate **`elbv2.CfnListenerRule`** against `self.public_https_listener.ref` that **replicates the authenticate-cognito action by hand** (you cannot reuse the L2 `AuthenticateCognitoAction`):
  ```python
  elbv2.CfnListenerRule(
    self, "ConsoleListenerRule",
    listener_arn=self.public_https_listener.ref,
    priority=10,
    conditions=[elbv2.CfnListenerRule.RuleConditionProperty(
        field="host-header",
        host_header_config=elbv2.CfnListenerRule.HostHeaderConfigProperty(
            values=[console_host]))],
    actions=[
      elbv2.CfnListenerRule.ActionProperty(  # order 1 — MUST come first
        type="authenticate-cognito", order=1,
        authenticate_cognito_config=elbv2.CfnListenerRule.AuthenticateCognitoConfigProperty(
            user_pool_arn=cognito_stack.user_pool.user_pool_arn,
            user_pool_client_id=cognito_stack.user_pool_client.user_pool_client_id,
            # MUST be fully-qualified to match the existing default_actions (:774), else login redirect fails:
            user_pool_domain=f"{cognito_stack.user_pool_domain.domain_name}.auth.{self.region}.amazoncognito.com")),
      elbv2.CfnListenerRule.ActionProperty(   # order 2
        type="forward", order=2, target_group_arn=console_tg.ref),
    ])
  ```
  - **Do NOT touch the listener `default_actions`** (dashboard auth) — host-based routing keeps it intact.
  - **Prerequisite:** `console_host` must resolve to the ALB and the ALB cert must cover it (ACM SAN). If no DNS/cert is available yet, this is a blocking sub-dependency — flag it before deploy.
  - **Security check:** a forward-only rule (missing the order-1 authenticate-cognito action) = an unauthenticated console. The 22.25 unauthenticated-challenge smoke step is the backstop, but the rule must be authored correctly here.
**Task 22.22 — config + outputs** — add `compute.ecs_tasks.console` to `dev.yaml`/`prod.yaml`; add the `console_host` value to config; `CfnOutput ConsoleUrl`. **Also a `network_stack.py` edit** for `console_sg` (see 22.20a).

## Milestone 7 — Build, deploy, smoke
**22.23 build & push** (extend `scripts/build_and_push_images.sh`) · **22.24 deploy** · **22.25 smoke** (Cognito challenge; Overview loads; `/v1` 200; no `x-api-key` in browser; dashboard SSO intact).

---

## Open decisions — RESOLVED (per Kiro review 2026-06-07)
- [x] **ALB routing:** **host-based** — `console.aegionai.ai` vs `dashboard.aegionai.ai` (domain owned at GoDaddy). Leaves dashboard `default_actions` untouched. Prerequisite satisfied by **Task 22.17b** (GoDaddy CNAME + `*.aegionai.ai` ACM cert, replacing today's self-signed cert).
- [x] **API-key model:** dedicated console key with value in **Secrets Manager**.
- [x] **nginx proxy target:** **public API Gateway** (identical contract + Usage-Plan throttling).

## Review follow-ups folded in (Kiro, 2026-06-07)
- Issue 1 (Cognito listener) → Task 22.21 rewritten: hand-built `CfnListenerRule` with its own order-1 authenticate-cognito action; default_actions untouched.
- Issue 2 (service loop not pure-config) → Tasks 22.20a (SG map + `network_stack` `console_sg`) and 22.20b (listener-dependency branch).
- Issue 3 (non-exposed endpoints) → `/sessions/{sid}/signals` and `/discovery/scan` removed from the matrix and flagged as WS-21 follow-ups.
- Smaller gaps → cdk-diff criterion matched to host-based routing; CSP baseline specified (22.17); types nullability tied to LLD §11.2 (22.6); app-dep versions pinned + compat verified (risk table).

## Risks
| Risk | Likelihood | Mitigation |
|---|---|---|
| api-key leaks to browser | Low | Injected only on nginx proxied hop; smoke test asserts absence; CSP |
| ALB change breaks dashboard Cognito | Low | Host-based routing = **additive** `CfnListenerRule`; dashboard `default_actions` never edited; smoke step re-checks dashboard SSO |
| Console rule ships without auth (forward-only) | Medium | Rule must carry order-1 authenticate-cognito action (Task 22.21); unauthenticated-challenge smoke step is the backstop |
| `deployment-qa.md` "private API" note misleads future work | Medium | Add a stale-note pointing to WS-16 |
| Vite 8 / React 19 / TS 6 toolchain mismatch | Low | Toolchain pinned to `frontend/package.json` (vite@8, react@19, ts@6, tailwind@4) |
| **App-dep compat** (react-router-dom@7, @tanstack/react-query@5, chart.js@4 + react-chartjs-2@5, @tabler/icons-react@3) — not present in `frontend/` | Low | **Verified 2026-06-07**: installed + `tsc -b && vite build` green under React 19. Versions pinned in `web/console/package.json`; RR7/RQ5 are React-19-compatible majors |
| Build context size bloats image | Low | `.dockerignore`; build from `web/console` context |

## Post-deploy hotfix (2026-06-07) — live-data crash
- **Crash:** Overview white-screened with `Cannot destructure property 'icon' of … undefined`. Real `/v1/metrics/platform-distribution` returns `cloud_provider: "unknown"` (LLD-21 §10.1: cloud_provider is unreliable in real data), which wasn't in the icon map.
- **Fix:** every enum→style lookup (cloud icons, decision/risk/discovery/cloud badges, agent/policy/trust status colors) is now defensive with a neutral fallback + shows the API-provided label; added a route **`RouteErrorBoundary`** so any data quirk degrades gracefully instead of white-screening. Shipped as console **milestone-2** (digest verified live).
- **Backend follow-up (not frontend):** `/v1/metrics/overview` currently returns **500** (the long-known "validation metrics not emitted to CloudWatch" blocker). The UI handles it with an inline error+retry card (no crash) — but the Overview KPIs stay empty until the controller emits those metrics.

## Code review fixes (Kiro, 2026-06-07) — all folded in
- **B1 (blocker)**: `SENTRA_API_BASE` was missing the `/prod` stage → every `/v1` call would 403/404. Fixed in `docker/console/Dockerfile`, `compute_stack.py`, README; re-synth confirms `…/prod`.
- **B2**: `Decision` reduced to `ALLOW | DENY` (REDACT is `/validate`-only, not the console feed — LLD-21 §2).
- **B3**: `Platform` gained `azure_foundry` (LLD-21 §2/§10.1).
- **B6**: discovery import realigned to `{ agent_ids, enforcement_mode? }` (WS-21 D2 RESOLVED) — dropped `policy_template_id`.
- **B4/B5**: lint now green — `ApiException` carries `cause`; DiscoveryPage toggle uses `if/else`.
- **B7**: removed the jsdelivr Tabler webfont `<link>` (CSP-blocked + redundant with `@tabler/icons-react`).
- **B8**: added `public/favicon.svg` (no more 404).
- **B9**: corrected the mock-adapter comment (lazy chunk, never fetched in prod — not dead-code-eliminated).
- B10 (mock `i.pravatar.cc` avatar): noted for real-auth integration; demo-only.
- Verified: `npm run build` green, `npm run lint` 0 errors, `cdk synth` EXIT=0.

## Responsive / mobile (2026-06-07)
The canvas is a desktop SOC layout; made the app responsive without changing the desktop design:
- **NavRail** → off-canvas drawer + backdrop on `<lg`, static `w-56` rail on `lg+`; **TopBar** gains a hamburger and condenses (search icon-only, cloud selector hidden `<md`, user text hidden `<sm`).
- **Grids** collapse: Overview KPIs `1→3` cols (hero `lg:col-span-2 row-span-2`), stat row `2→4`, platform `1→3`, chart/feed `1→[62%_1fr]`; Discovery + Agent Detail `2→4`; two-col panels stack. Hero number uses `clamp()`. Page padding `p-4 sm:p-6 lg:p-8`.
- Tables stay in `overflow-x-auto` (scroll horizontally on mobile; page itself never overflows — verified docW==winW at 390px).
- Fixed a React key warning in Audit Trail (keyed `Fragment` per expandable row). Build + lint green; desktop unchanged.

## Cross-references
- [WS-21 APIs](workstream-21-soc-console-apis.md) · [LLD 21](../lld/21-api-inventory-for-ux.md) · [WS-16 API GW](workstream-16-apigw-vpc-link-networking.md) · `cdk/stacks/{compute,api,cognito}_stack.py` · `docker/dashboard/`
