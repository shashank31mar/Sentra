# Console Design Spec — WS-G (lld/40 multi-tenant console)

**Status**: Design-of-record for the WS-G frontend build.
**Source**: distilled from the Kombai mockups in `.kombai/canvas/aegion-login.canvas`, extracted per-screen to
`.kombai/canvas/extracted/*.html` (29 variants). This doc is the coder's design reference; the raw HTML files
are the pixel-detail fallback (paths cited per screen).
**Consumed by**: `senior-sde-frontend` for `tasks/serverless-edition/ws-g-build/ws-g-frontend.md`.
**Last updated**: 2026-07-08

---

## 0. Decision-of-record: NAVY RETHEME (full fidelity to the canvas)

The founder directed "implement what's in the canvas I shared." The canvas is a **uniform institutional-navy
design system across all 29 screens** — NOT a per-page treatment. Therefore:

- **Remap the CSS-first `@theme` token layer** in `web/console/src/styles/index.css` to the navy palette (§1).
  This intentionally reskins the already-shipped screens too — that is correct; the canvas shows the whole
  console in navy, so the whole console becomes navy. This is one coherent theme change, not per-page overrides.
  **Do NOT introduce a per-page navy surface** (that fractures the theme).
- **Keep the existing font stack** (Space Grotesk display / IBM Plex Sans body / IBM Plex Mono). The mocks use
  Archivo/Lato; map **Archivo→Space Grotesk**, **Lato→IBM Plex Sans**. They are near-identical in character;
  adding Archivo/Lato webfonts is churn for no visible gain. IBM Plex Mono already matches — keep it for all
  numbers, ids, ARNs, timestamps, endpoints, code.
- Because tokens are the single source, the reskin ripples through every component that uses the `bg-*`/`text-*`
  utilities. Verify the shipped screens still read correctly after the remap (they should — same utility names,
  new token values).

---

## 1. Token remap (edit `web/console/src/styles/index.css` `@theme`)

Map mock hexes → tokens. Do not hardcode mock hexes in components; use the tokens.

| Token | New value (navy) | Old value | Semantic |
|---|---|---|---|
| `--color-bg` | `#060E1C` | `#010B13` | app background / `<main>` |
| `--color-surface` | `#0C1730` | (surface) | cards, tiles, table shell |
| `--color-surface-2` | `#0A1428` | (surface-2) | insets, thead, sidebar, code blocks |
| `--color-line` | `rgba(255,255,255,0.07)` | (line) | hairline borders |
| `--color-blue` (NEW) | `#4F86D6` | — | **primary accent**: links, active nav, chart "allowed", policy chip |
| `--color-blue-fill` (NEW) | `#2E5FB0` | — | filled primary buttons, active segment |
| `--color-blue-lt` (NEW) | `#8FB4EC` | — | highlighted-tile label, sorted-column header |
| `--color-green` | `#22E58B` | `#22E58B` (same) | allow / healthy / enforce / low-sev / positive delta |
| `--color-amber` | `#FFB020` | `#FFB020` (same) | warn / med-sev / shadow-mode / roadmap / PARTIAL / consent-required |
| `--color-pink` | `#FF3D71` | `#FF0080` | block / deny / danger / suspended / expired / high-risk / critical-sev |
| `--color-info` (NEW) | `#38BDF8` | — | ML classifier chip, cedar badge, injection category, write-op, imported status |
| `--color-sev-high` (NEW) | `#FF7A45` | — | sigma **high** tier (distinct from critical pink) |
| `--color-purple` (NEW) | `#B9A6F5` | — | `dedicated` plan badge |
| `--color-ink` | `#EAF1FB` | (ink) | primary text |
| `--color-secondary` | `#9DB0CE` | (secondary) | body/subtitle text |
| `--color-muted` | `#6B7E9E` | (muted) | labels, faint headers |
| `--color-faint` | `#4E607E` | (faint) | disabled, em-dash placeholders |
| cloud literals | AWS `#FF9900` · GCP `#4285F4` · Azure `#37A0E8` | — | cloud dot-pills / donuts (keep as literals) |

**Trust color thresholds (universal):** `≥80` green · `50–79` amber · `<50` pink. Build one `trustColor(n)` helper.

---

## 2. Shared chrome (build once, all screens)

**Shell** (already exists as `AppLayout` — reskin, don't rebuild): `flex` row. Left `<aside w-[224px]>` NavRail
(`bg --color-surface-2`, right hairline) + right column with a sticky `<header h-[56px]>` TopBar
(`bg rgba(10,20,40,0.82)` + `backdrop-blur(12px)`) and a scrolling `<main p-8 bg --color-bg>`.

**NavRail**: 56px brand row — gradient logo tile `linear-gradient(150deg,#2E5FB0,#01153D)`, "Aegion" wordmark,
mono chip top-right = **`SOC` (customer)** / **`PLATFORM` (platform console)**. Groups = uppercase label
(`10px bold tracking-[0.16em] --color-muted`) + items. Active item: `bg rgba(46,95,176,0.12)`, `--color-ink`
bold, 2px left rail bar `--color-blue`. **Canonical customer nav taxonomy (6 groups)** — reconcile the mocks'
drift to this: **MONITOR** (Overview, Activity feed, Threats) · **FORENSICS** (Decision detail, Session
forensics) · **ASSETS** (Agent Inventory, Topology, Residual Agents) · **ONBOARD** (Connect Account, Import
Agents, Deploy Agent) · **GOVERN** (Policies, Quarantine, Audit Trail) · **ACCOUNT** (Usage & billing).

**TopBar**: left = live status dot (green glow; **red on Decision-trail of a quarantined session**) + breadcrumb
`Aegion / … / <page>` (tail bold). Right cluster: Search pill w/ `⌘K`; **customer** → non-interactive tenant
chip `acme` (blue-border) — NOT a switcher (tenant fixed at login, ADR-039); **platform** → non-interactive
`PLATFORM · ALL TENANTS` blue-gradient globe pill + NO tenant chip; bell w/ red dot; avatar + name/role
(`Dana R. / Admin` customer, `Sarah Chen / Platform Operator` platform). `acme` / `Dana R.` are placeholder
data — bind to `useMe()`.

**PageHeader** (primitive exists — extend): `flex justify-between`, `items-end` on list pages / `items-start`
on detail pages. H1 = display 24px bold `--color-ink`; subtitle 13px `--color-secondary`, prefixed
`<tenant> · …`. Detail pages append a status pill inline after H1. Right slot = optional segmented toggle +
one filled primary CTA (`bg --color-blue-fill`).

---

## 3. Shared component patterns

**Card**: `rounded-2xl bg --color-surface border --color-line`. Table-card adds `overflow-hidden` + a
`px-6 py-4` header row (title 15–16px + 12px subtitle + right count-pill / "View all →") with a bottom hairline.

**KPI tile** (`rounded-2xl p-5`): eyebrow (`10px bold tracking-[0.14em] --color-muted`) + big **mono** number
(`27–28px --color-ink`, unit smaller `--color-secondary`) + delta/status row (`12px bold`: green ▲ / pink ▼).
Variants: **`highlight`** (hero, e.g. Trust) `bg linear-gradient(160deg,rgba(46,95,176,0.18),--color-surface)` +
blue border + `--color-blue-lt` label; **`danger`** (decayed trust / blocked-24h) pink border/gradient.
Grids `grid-cols-4|5|6`. Build `<KpiTile variant="default|highlight|danger">`.

**Decision pill** (universal): Blocked = `bg rgba(255,61,113,0.14) text --color-pink` + dot; Allowed =
`bg rgba(34,229,139,0.13) text --color-green` + dot.

**Filter toolbar**: `flex gap-3`; a segmented pill group (`bg --color-surface p-0.5`, active segment
`bg --color-blue-fill`), optional `<select>`/dropdown chips, a mono session-id input, a grow search input
(icon left). Optional trailing date-range button (`Last 24h ▾`).

**Standard table**: thead `bg --color-surface-2`, `11px bold tracking-[0.12em] --color-muted`, sticky; sorted
column tinted `--color-blue-lt` + caret. Rows `border-top --color-line`, hover `bg rgba(46,95,176,0.06)`,
~37–52px. Agent cell = bold name over mono id. Cloud = dot-pill. Trailing "View trail/detail" link
`--color-blue`. **Row-as-link** where a row navigates (whole `<tr>` click target + trailing chevron).

**Table primitive extension** (the platform grid + several customer tables need it): add to the existing
`Table` — **sticky header**, **`@tanstack/react-virtual` body** (add the dep), **sortable-header caret**, and a
**`rowHref` prop**. Footer: "Showing X–Y of N" + virtualized note + Rows-per-page + Prev/numbered/Next pager.

**Badges/pills** (extend existing `badges` + `StatusDot`): status-dot (active green / at-risk amber / suspended
pink / deleting pink); **identity-mode pill — canonical `enforce`(green) / `shadow`(blue) / `off`(grey)** — do
NOT ship "monitor" as an identity mode; plan badge (enterprise blue / dedicated purple / trial-free grey, mono);
risk pill (High pink / Med amber / Low green); **consent pill** (`Consent required` amber, triangle-alert);
roadmap markers (`ROADMAP`/`SOON`/`estimate`/`PARTIAL` amber micro-chips).

### New components not in today's primitive set (build these)
1. **SegmentedToggle** (24h/7d/30d, All/Blocked/Allowed) — pill group, active-segment fill.
2. **FacetFilterRow** — `Cloud/Status/Policy` dropdown chips + result count (Agent Inventory).
3. **ExpandableRow** — inline detail strip under a `<tr>` (Threats decision-trace, Sigma rule detail, Quarantine why-trace).
4. **ForensicTimeline** — gradient spine + colored ring nodes + per-request collapsible signal sub-tables (Decision trail).
5. **SignalsTable / validator-chip strip** — `sentra.*` source chips, DENY/ALLOW/FLAG/NOTE pills, severity tiers.
6. **PillToggle** switch (Sigma enabled on/off).
7. **CodeViewer** — syntax-highlighted (`.k` blue / `.s` green / `.c` muted / `.p` info) + a **format toggle**
   (YAML active / Cedar·JSON `SOON` when the compiled body is absent).
8. **PreviewBanner** (full-width, amber, 4px left border) + disabled-with-tooltip button (Usage, Quarantine, Policy detail).
9. **QuotaBar** — gradient fill + used/total label (Usage).
10. **Chart wrappers** on chart.js (already a dep): filled-area line, doughnut (`cutout:70%`), stacked bar,
    plus a force-cluster/Sankey for roadmap topology (sample-data only).
11. **LiveStatusDot / pulse** + auto-refresh pill (Activity "Auto-refresh · 15s").

---

## 4. Login / org-first entry (ADR-039) — DARK, dropping the SSO-Okta button

**Design-of-record: D's dark visual system + B2's correct content.** (`login-d-terminal-precision-dark-mono.html`
tokens + `login-b2-institutional-trust-sso-correct.html` copy.) D already uses Space Grotesk / IBM Plex + green
`#22E58B`. B2 is the only mock aligned with org-first→Cognito. All other login mocks show a `Continue with SSO ·
Okta` button — **do NOT build it** (we use our own Cognito pool, not the customer's IdP; IdP-SSO is ADR-035
roadmap only).

**Two-step flow, dark tokens:**
- **Step 1 — org entry** (static `org.html`, served unauth — NOT an SPA route; backend lane G0.3):
  centered card on `--color-bg`; optional subtle scanline/grid overlay. Copy: h2 **"Sign in to your
  organization"**, sub **"Enter your workspace to continue."**, label **"Organization"**, placeholder
  **"acme"**, mono suffix chip **".aegionai.ai"**, primary **"Continue"** (+arrow, `--color-green` fill,
  `#06210F` text), helper **"Contact your administrator"**. Client script: on Continue → `fetch
  /public/resolve-org?org=…` → on hit stash `sessionStorage["aegion.activeTenant"]=tenant_id` → redirect to
  Cognito hosted login; on miss → stay, show error **"We couldn't find an organization named "…". Check the
  spelling or contact your administrator."** (red border+ring, disable Continue).
- **Step 2 — post-resolve credentials** (Cognito hosted UI; we style the surrounding handoff): resolved-org
  chip (`A` avatar · `Acme Corp · acme` · **`Change`** link back to org page); h2 **"Sign in to <Org>"**; sub
  **"Use your Aegion credentials. Authentication is handled by our AWS Cognito hosted sign-in."**; fields
  **"Work email"** (`you@acme.io`) + **"Password"** w/ inline **"Forgot?"**; primary **"Sign in"**; sub-line
  **"Secured by AWS Cognito · hosted sign-in"**; footer **"Protected by AWS Cognito · SOC 2 Type II"**; info
  panel **"SSO to your own IdP (Okta / Entra) is on the roadmap (ADR-035). The pilot uses Aegion-hosted Cognito
  accounts."**

---

## 5. Per-screen specs (customer console)

Each cites its extracted HTML for pixel detail. All subtitles prefixed `<tenant> ·`. Statuses (BUILD/EXTEND/
VERIFY/PROMOTE) are per `tasks/serverless-edition/ws-g-console.md`.

- **Overview** (`console-overview-enhanced-institutional-navy.html`) — VERIFY/PROMOTE (M-G3.1). 5-col KPI
  (Threats Blocked / Active Agents / **Trust Score** highlight / Quarantined amber / Avg Latency) → 3-col chart
  row (2-col filled-line Decisions-over-time Allowed`--color-blue`/Blocked`--color-pink` + 1-col cloud doughnut)
  → Recent-decisions table (header note **"Near-real-time (≤15s pull) · this tenant"**) → 2-col bottom (Residual
  agents / Active sessions). No client tenant filter (server-scoped).
- **Activity feed** (`console-activity-feed-near-real-time-g3-1.html`) — **BUILD** (M-G3.2). PageHeader w/ inline
  pulsing **"Auto-refresh · 15s"** pill + "Updated 4s ago" + Pause/Resume; filter toolbar (segmented + threat
  `<select>` + session-id input + search); full-width table `TIME·AGENT·CLOUD·DECISION·THREAT·TOOL·SESSION·View
  detail`; newest row flashes (blue left bar); footer `Load more` + "Showing N of M · last 24h". Data: `GET
  /v1/decisions` cursor, `refetchInterval:15_000`. Rows link to `decisionDetailPath(session_id, request_id)`
  (composite). No socket/SSE.
- **Threats** (`console-threats-threat-explorer.html`) — EXTEND (M-G3.3). Filter (All/**Blocked**/Allowed +
  session-id + search); table `AGENT·DECISION·THREAT·TOOL·CLOUD·SESSION TRUST·SEEN·ACTION`; Quarantine button
  (pink outline, Blocked rows only, `useCan('quarantine.manage')`); **ExpandableRow** = decision-trace validator
  chips. Add **winning_source facet** (API-driven; PARTIAL until backend field lands, fallback
  `source.replace(/^sentra\./,'')`).
- **Decision trail** (`console-decision-trail-session-trail.html`) — **BUILD client** (M-G3.4). Route
  `/decisions/:sessionId/:requestId` (composite PK). PageHeader + Quarantined pill + `Export trail` + `Release
  session` (`quarantine.manage`); TopBar dot **red**. 4-col KPI strip (Trust decayed-red / Total Requests /
  Denied / Timeline) → **ForensicTimeline** (gradient spine, ring nodes, per-request card = USER INPUT quote +
  collapsible **SignalsTable** `SOURCE·DECISION·REASON·CONF·THREAT·MATCHED RULE·SEVERITY`). Binds WS-D `GET
  /v1/sessions/{id}/trail?request_id=`; PARTIAL + `DecisionTrace` fallback on 404/501; verdict panel
  `decisions.verdict`-gated.
- **Session forensics** (reuse decision-trail components) — **BUILD** (M-G3.5). Route `/sessions/:sessionId`.
  Derive header from decisions response (NO `GET /v1/sessions/{id}` — don't invent it); reuse `sessionsApi.list`
  + `.decisions()` + `DecisionTrace`.
- **Agent Inventory** (`console-agent-inventory.html`) — PROMOTE/GATE (M-G3.6). **FacetFilterRow** (Cloud/Status/
  Policy + count); table `AGENT·CLOUD·STATUS·POLICY·TRUST·REQUESTS·DENIED·SESSIONS·LAST SEEN·ACTIONS`; gate
  attach/detach/import `agents.write`; client-map ECS status→canvas (running=green, starting=amber, stopped=grey,
  **no-traffic→Idle not Active**).
- **Agent detail** (`console-agent-detail.html`) — PROMOTE (M-G3.6). PageHeader + running pill + `agt_…·
  LangChain · region` + AWS pill; 4-col KPI; tab bar Overview/Flow/Tools/Policy (2px blue underline); 3-col body
  (Tools table w/ op-tag colors + Recent decisions mini + Governing-policy card + Metadata card).
- **Topology** (`console-topology-flow-map.html`) — ROADMAP (M-G3.7). `GET /v1/topology` does NOT exist —
  render **amber ROADMAP badge + sample-data banner** ("Roadmap preview — flow-map data is illustrative …
  `GET /v1/topology` is unbuilt"); Sankey is a design mock; **zero network call to the nonexistent route**.
- **Policy Library** (`console-policy-library.html`) — VERIFY/GATE (M-G3.8). Sub-tabs Policies / Sigma rules;
  Policies table `POLICY·STATUS·VERSION·AGENTS·UPDATED·ACTIONS` (format badge cedar-info/yaml-grey); Sigma table
  `RULE·CATEGORY·SEVERITY·MATCHES·ENABLED` (**PillToggle**, 4-tier severity low-green/med-amber/high-`--color-sev-high`/critical-pink,
  **ExpandableRow** = desc+tags+patterns code+condition). Delete→`policies.delete`(admin); create/edit→
  `policies.write`(editor). Sigma category chip client-derived from `tags`.
- **Policy detail** (`console-policy-detail.html`) — VERIFY/GATE (M-G3.8). PageHeader mono name + yaml chip +
  Active + v-chip + `Edit`(editor)/`Disable`(admin); 3-col (Rules tab card w/ sub-tabs + **CodeViewer** w/
  **format toggle YAML/Cedar·JSON `SOON`** — Cedar/JSON PARTIAL when compiled body absent, never fabricate;
  Policy-elements card content_hash/s3_key/match_count; Allowed tools/agents chips).
- **Quarantine** (`console-quarantine.html`) — VERIFY/GATE (M-G3.10). Summary bar (N quarantined / auto / operator);
  table `SESSION·AGENT·USER·TRUST·REQUESTS·DENIED·LAST ACTIVITY·ACTION`; Unquarantine `quarantine.manage`(admin);
  **ExpandableRow** why-trace **degrades to `quarantine_status`** (amber ROADMAP chip) until origin+signals surface.
- **Audit Trail** (`console-audit-trail.html`) — VERIFY (M-G3.11). Filter (All/Blocked/Allowed + session-id +
  search + `Last 24h ▾`); table `AGENT·DECISION·DETAIL(wide)·CLOUD·TIME·View trail` (detail mono-amber when a
  sigma rule matched); verdict panel editor-gated; **NO CSV/PDF export** (deferred w/ FR-6.5).
- **Usage & billing** (`console-usage-billing-partial-g3-6.html`) — **BUILD** (M-G3.12, WS-H dep). Top
  **PreviewBanner** (`PARTIAL · WS-H`, references `/v1/usage`); disabled `Download invoice` + tooltip "Available
  when metering GA"; 4-col KPI w/ `estimate` chips; stacked-bar "Metered usage over time" (`partial period` chip);
  Plan card + **QuotaBar** + `indicative` chip; Usage-breakdown table. **Feature-flag OFF or PARTIAL until WS-H
  live** — no dark billing tab, no fabricated totals.
- **Connect Cloud** (`console-connect-cloud-account.html`) — VERIFY/GATE (M-G3.9). 3-step progress; provider
  cards (AWS/Azure/GCP); **grant fields are COPY-ONLY** (External ID + Principal ARN display+copy; only Role ARN
  is an input) — console never applies the grant; `Launch stack` external link; scopes card. Create/PUT/DELETE
  `connections.write`(admin); test/scan `connections.operate`(editor); don't re-enable descoped `/discovery/scan`.
- **Import Agents** (`console-import-agents.html`) — VERIFY/GATE (M-G3.9). 4 KPI; platform-scan bar (Azure often
  `not connected`); discovered-agents table (checkbox·NAME·CLOUD·FRAMEWORK·RISK·STATUS·FIRST SEEN); sticky
  bottom action bar (`N selected` + **Monitor/Enforce** toggle → `enforcement_mode` on `POST /discovery/import`);
  import gated `agents.write`. GCP "coming soon" where shown.
- **Deploy Agent** (`console-deploy-agent-onboard.html`) — currently `PlaceholderPage`; onboarding wizard
  (framework tiles → configure enforcement Shadow/Enforce + integration snippet → verify-traffic listener). Wire
  behind `ONBOARD` nav; no backend mutation beyond existing import.
- **Residual Agents** (`console-residual-agents.html`) — VERIFY (G2.7, read floor `identity.residual.read`).
  Amber banner ("Legacy self-asserted fallback is closing … retire is on the roadmap — GET-only, no mutation");
  fallback-roster table with **`Retire [SOON]` disabled** button (roadmap). Read-only.

---

## 6. Platform (cross-tenant) console — §6.11, M-G4

**Distinct identity via 5 chrome tells (same dark shell, flip on `is_platform`):** (1) brand chip `PLATFORM`
not `SOC`; (2) `PLATFORM · ALL TENANTS` scope pill, NO tenant switcher; (3) role label `Platform Operator`;
(4) reduced nav `FLEET` (Fleet Overview, Fleet Topology, Tenants) + `OVERSIGHT` (Audit, System Health);
(5) persistent `Cross-tenant read · audited` eyebrow on every read. Do NOT recolor the app — the tells are the
signal. Route tree is a **separate top-level branch gated at the router root on `is_platform === true`**
(false AND absent → `<Navigate to overview>`), NOT nested under the customer `AppLayout`.

- **Fleet Overview / Tenant Grid** — design-of-record **`platform-fleet-overview-ranked-table.html`** (the only
  mock matching the ship-first spec). 4 KPI (Tenants / Fleet Agents / Threats Blocked / Fleet Trust highlight)
  → 3-col chart row (fleet decisions line + identity-rollout `enforce/shadow/off`) → **ranked tenant registry**:
  header cites `GET /v1/platform/tenants · virtualized · server-side sort & filter`; **6 columns ship first —
  `# · Tenant(avatar+display_name+t_id) · Plan · Identity mode · Status · Created`** + the **new `Consent`
  column** (amber `Consent required` pill vs green granted/aggregate) + trailing chevron. **Rows are links only**
  (→ tenant drill-down), read-only, virtualized (`@tanstack/react-virtual`). Bottom 2-col (Agents-by-cloud +
  Fleet-risk aggregates). **Metric columns (Agents/Blocks24h/Trust/Decisions) light up later** — borrow the
  column renderers (trust bar+delta, block color-scaling, enforcement pill) from
  `platform-fleet-overview-command-split.html`; gate them behind "metrics present". Missing metric sorts LAST.
- **Tenant drill-down (consent 403)** — `platform-tenant-drill-down-consent-required-403-6-11.html`. Route
  `/platform/tenants/:tenantId` → `GET /v1/platform/tenants/{id}` (`require_platform`, dual-audits, `retry:false`).
  **Aggregate strip always visible** (green "AGGREGATE VISIBLE" — status/plan/mode/quota/members). The **403
  `CONSENT_REQUIRED`** state is a first-class empty card (NOT fake-200): `403` badge + `CONSENT_REQUIRED` amber +
  hero "Detailed access requires tenant consent" + `Request access`/`Break-glass access` + a two-col AVAILABLE-NOW
  (green) vs SEALED-UNTIL-CONSENT (amber, lock chips) split + audited footer. Distinct from 404. As-built the
  drill-down is served + audited `consent_state="false-unenforced"` (enforce OFF); the 403 empty-state renders
  only when enforce is flipped ON and consent absent. **Console must NOT reach tenant content by setting
  `X-Aegion-Tenant` to a target** (that hits the stricter break-glass gate) — use the metadata route only.
- **Fleet Topology** — `platform-fleet-topology-aggregate-6-11.html`. ROADMAP/aggregate-only: KPI + force-cluster
  provider bubbles + doughnut + identity-mode list + density bars; "individual tenants collapsed for scale";
  **zero live call** (aggregate framing). Footer: drill into a tenant's own topology (consent-gated) from the registry.
- **System Health** — ROADMAP (no per-region route; only a scalar `avg_latency_ms` exists) — roadmap badge, zero fetch.

**Platform API client (G4.2):** new `lib/api/platform.ts` + `lib/query/usePlatform.ts`; **MUST NOT attach
`X-Aegion-Tenant`**; `retry:false` on detail; metric fields OPTIONAL (parse-absent). Fleet KPIs/timeseries reuse
`metricsApi`/`decisionsApi` — the **server** auto-detects `is_platform`→`tenant_id=None`+audit; no client scope.

---

## 7. Cross-cutting design invariants (fail-secure, honesty)
- **Render-gate is UX-only, never the boundary.** Gated control = **not rendered** (not disabled — can't be
  re-enabled via devtools). Server `require_role`/`require_platform` is the boundary.
- **Never fabricate data.** 404/501 → PARTIAL banner; unbuilt route → ROADMAP badge + sample marker + zero fetch;
  compiled-Cedar/topology/usage-totals absent → honest degrade, never a blank page or invented numbers.
- **All "live" = ≤15s TanStack poll** labeled "near-real-time (≤15s pull)". No WebSocket/SSE.
- **403 on a mutation** → toast (sanitized message + request_id) + `invalidateQueries(['me'])`; does NOT log out
  (that's 401 only). `/v1/me` outage → mock `is_platform:false` → platform tree denied, not exposed.
- **Placeholder data in mocks** (`acme`, `Dana R.`, tenant counts 48 vs 1,000, `enforce/monitor` vs
  `enforce/shadow`) are NOT requirements — bind real data; canonical identity vocab is **`enforce/shadow/off`**.
