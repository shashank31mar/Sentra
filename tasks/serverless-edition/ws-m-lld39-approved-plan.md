# WS-M LLD (lld/39) — APPROVED PLAN (founder-signed 2026-07-05)

This is the human-approved plan packet for `lld/39-authz-rbac-edge-authorizer.md`.
The design-loop build phase drafts the LLD from THIS plan. All 4 open judgment calls are RESOLVED below.
Doc identifiers are LOCKED: this LLD is **lld/39** (36/37/38 taken); the new decision is **ADR-037** (ADR-036 taken by Detection-Depth Enforce Overrides). Do NOT use lld/36 or ADR-036.

Scope: full M1-M6 + M7 tests. WS-F's merge gate depends on M3, so the whole set is in scope.

---

## RESOLVED DECISIONS (founder sign-off — build to these)

**D1 — ADR-037 edge-authorizer mechanism = REST Lambda authorizer verifying the existing ES256 JWT.**
REQUEST-type API-Gateway Lambda authorizer validates the ES256 JWT the caller already presents (per-agent JWT for programmatic callers; optionally the ALB `x-amzn-oidc-data` for console), returns an IAM allow/deny policy + a context object (tenant_id, role, sub) that the app layer can consume. The single shared API key is DEMOTED to metering/usage-plan only; app-layer `require_role` stays as defense-in-depth. LLD commits the decision + design; full rollout stages (decision now, not necessarily full deploy in this WS).
WHY (AWS primary sources, cite in the ADR):
- Native JWT authorizer is HTTP-API(v2) ONLY; we are REST(v1) so a Lambda authorizer is the AWS-documented substitute. https://docs.aws.amazon.com/apigatewayv2/latest/api-reference/apis-apiid-authorizers-authorizerid.html · https://aws.amazon.com/blogs/compute/evaluating-access-control-methods-to-secure-amazon-api-gateway-apis/
- API keys are NOT an auth mechanism (AWS usage-plans best practice: "Don't use API keys for authentication or authorization... use an IAM role, a Lambda authorizer, or an Amazon Cognito user pool"). https://docs.aws.amazon.com/apigateway/latest/developerguide/api-gateway-api-usage-plans.html
- PORTABLE: verifying a standard RFC-7519 JWT at the edge ports 1:1 to Envoy/Kong/NGINX for the Azure/GCP/air-gapped editions (cross-vendor thesis). Cognito-authorizer + IAM-SigV4 are AWS-proprietary and were REJECTED as the edge contract. OWASP REST Security Cheat Sheet backs centralized-IdP + signed-JWT. https://cheatsheetseries.owasp.org/cheatsheets/REST_Security_Cheat_Sheet.html
- Our API Gateway IS the public edge (verified: API GW -> VpcLink -> NLB -> private ALB -> ECS, api_stack.py:253-267, compute_stack.py:633-706), so "defer, the ALB is the door" is NOT defensible.
Present the option table in the ADR (Lambda-authorizer chosen vs per-tenant-keys vs IAM vs defer) with the rationale; record as ADR-037.

**D2 — Anti-IDOR ownership = ONE generalized object-ownership helper.**
Generalize `_assert_owns_agent` (tenancy_routes.py:48, delimited-prefix check) into a single object-ownership helper asserting tenant-ownership across agent_id / policy_id / connection_id / session_id (each resource's tenant == ctx.tenant_id; agent keeps the delimited `ctx.tenant_id + "-"` prefix check). Matches OWASP API1:2023 BOLA ("check ownership in every function that uses client input to access a record") — one place to audit + test. https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/
Design note: this helper is a SHARED CONTRACT that WS-D/WS-G also touch (deps.py/tenancy_routes.py/routes.py are shared) — name it in Cross-references and coordinate the signature. Decide 403-vs-404 for cross-tenant existence-sensitive resources (RFC 9110 permits masking a forbidden resource as 404 to avoid leaking that an id is a real record in another tenant); default to 403 per the WS error model unless existence is sensitive — state the rule explicitly.

**D3 — Fix the fake-200 defect IN-SCOPE.**
routes.py:724-731 uses `return HTTPException(...)` instead of `raise` in a connection handler -> FastAPI serializes it as a 200 OK with an error body (violates engineering.md error-contract + master tenet 2 fail-secure). WS-M already edits these connection handlers to gate them, so fix it here (change return->raise, return the honest 4XX/5XX). Add a test asserting the failure path returns the real status code, not 200. Keep it a small, clearly-labeled sub-item under M2 (connections).

**D4 — Route 19 (post_session_signal, routes.py:453): design the dedicated data-plane producer credential, DEFER the build.**
The LLD DESIGNS a dedicated data-plane producer credential + tenant-scoping for `post_session_signal` (external-producer write) but flags the BUILD as staged/deferred (like M4 full-rollout and M5). Route 18 (post_decision_verdict, routes.py:916) gets authenticate + tenant-own NOW (derive operator_id from verified ctx, not body). Do not add net-new credential machinery to the shippable retrofit; pin the design so it isn't lost.

---

## OUTLINE (15 sections — follow project LLD template: Overview/Architecture/APIs/Data/Config/Errors/Monitoring/Cross-refs, <2000 lines, pseudo-code not production code, mermaid required incl. a SEQUENCE diagram for the auth flow)

1. Context — elaborates approved HLD serverless-edition sec 6.2(f) + sec 6.3 (AuthN/Z plane split) + sec 6.6 row(f); a COVERAGE RETROFIT reusing LLD-26 sec 5-6 / LLD-08 sec 6.5 primitives already built + live on dev. Name the three auth planes; state it does NOT re-litigate the Cognito-now decision. Lock lld/39 + ADR-037.
2. Architecture overview — the three auth planes (P1 operator->console control plane; P2 agent->PDP data plane; P3 API-Gateway edge) with a mermaid flow diagram AND a sequence diagram of the operator-mutation auth flow; the asymmetric-coverage vulnerability (tenancy_routes.py fully gated: 10 gates vs routes.py 1-of-19-gated) as the core problem statement; the retrofit boundary (coverage owner, NOT primitive owner).
3. Security (SEC-1..5 at implementation altitude) — THE BODY.
   3.1 authn: verify_alb_oidc (ES256, x-sentra-oidc-data->x-amzn-oidc-data fallback, per-kid LRU) — where it runs (per-request Depends). Include the signer-ARN hardening finding: today it verifies signature + exp but does NOT pin the ALB signer ARN (deps.py:282-319) — AWS best practice is to check the JWT header signer == expected ALB ARN, else any in-region ALB can mint a passing token. Fold in as a hardening item. https://aws.amazon.com/blogs/networking-and-content-delivery/security-best-practices-when-using-alb-authentication/
   3.2 authz: require_role(min_role) factory + require_platform + role_satisfies (_ROLE_ORDER viewer<editor<admin<owner ranks 0/1/2/3, unknown->False fail-secure); the PER-ROUTE ROLE MAP (all 18 routes + target gate, verified line numbers below).
   3.3 anti-IDOR object-ownership: the generalized helper (D2) — signature, where tenant-ownership is asserted for agent/policy/connection/session; 403-vs-404 rule.
   3.4 operator-identity derivation: drop X-Operator-Email as authority (default 'unknown', deps.py:8-9), derive from verified ctx.email/ctx.sub; keep X-Operator-Email at most as a legacy audit-label alias fed from ctx.email; derive self-asserted operator_id in quarantine/rollback/verdict from ctx, not body/query.
   3.5 M3 platform-scope gate on the fleet-global sigma-retire chain (update_sigma_rule routes.py:1446 -> SigmaRulesService._bump_enforcement_version sigma_rules_service.py:402) — WHY platform not tenant (store sentra-sigma-rules-metadata + S3 sigma_rules/llm/ NOT tenant-partitioned per lld/35 sec 13; a tenant-scoped role lets any tenant-admin retire a rule fleet-wide = the ADR-034 non-disableable-floor violation reached via the CRUD door). One call chain behind one door.
   3.6 audit events + fail-secure matrix (401/403/deny).
   3.7 the fake-200 fix (D3, routes.py:724-731 return-not-raise) as an in-scope fail-secure fix on the connection handlers WS-M already touches.
4. Edge authorizer + shared-API-key replacement (ADR-037, D1) — Plane 3. Option table (Lambda authorizer chosen / per-tenant scoped keys / IAM / defer) + the pick + rationale (AWS-cited); how it binds to the require_role layer + passes context; interaction with authorizationType-today + single shared key; the create-deployment gateway-flush footgun ([[apigw-per-resource-no-proxy]], [[sentra-prod-deploy-mechanism]]); WS-K K8-suite positive-authz coordination. Record ADR-037. Full rollout staged.
5. Verified-agent-identity (AD-7) GA-gate adjudication — Plane 2 residual. HLD sec 6.3/sec 8 resolves the SUBSTANCE: hard GA gate for money-movement/PHI, tenant-scoped API keys interim-only for non-money-movement design partners under DPA. What the LLD adjudicates = prod-activation TIMING + the coordination protocol with the WS-K two-latch enforce flip (effective = min(env ceiling, tenant.identity_mode)); credential issuance/rotation coverage drive; sequence after WS-0 money-movement routing. Reconcile the AD-7 status contradiction (ARCHITECTURE:332 'Roadmap' vs HLD/LLD-26 'enforcing on dev').
6. Federation seam consumption (ADR-035, design-only) — Plane 1. Consume the IdP-neutral VerifiedOperator{sub,email,idp_groups[]} seam WS-G designs (G3.7); NO IdP swap, NO rebuild of live membership/RBAC; SCIM/provider-switch DEFERRED (anti-goal).
7. Scaling — control-plane is low-QPS; per-route Depends adds one membership lookup (cached) + one O(1) ownership check; NO hot-path (/v1/validate) impact; the kid-LRU keeps OIDC verify off the network.
8. Resiliency & recovery — fail-secure per failure mode; no new stateful path (RTO/RPO N/A, reuses existing membership/credential stores owned by LLD-26); rollback = gate is additive Depends, revertible per-route; blast radius of a mis-scoped gate.
9. Networking — real topology (public ALB Cognito OIDC -> API Gateway public edge -> VpcLink -> NLB -> internal ALB -> controller); which hops strip x-amzn-oidc-* and why nginx re-emits x-sentra-oidc-data; ports/protocols reused, no new segmentation.
10. Database — reused tables only (sentra-tenant-members PK operator_sub/SK tenant_id; credential store; policy/connection/session/sigma stores); ownership-assertion access patterns; NO schema change (retrofit); note sigma store NOT tenant-partitioned (the M3 subtlety).
11. Cost — negligible incremental: one extra DDB point-read per mutating control-plane call (low-QPS), no validate-path cost.
12. Metering & billing — mostly N/A (control-plane authz); the ONE note: identity-DENY dual-tagging (security/audit + billing view, NOT the victim's quota series) per HLD sec 6.5 + [[identity-deny-not-metered]] — ensure newly-gated 403s don't silently escape the metering the trail expects.
13. Test matrix (M7 — tests are the arbiter) — per gated route: (a) missing/invalid OIDC->401, (b) below-role->403, (c) cross-tenant IDOR->403; the M3 BOTH-403 assertion (un-roled AND tenant-scoped-non-platform get 403, platform gets 200); the data-plane-reads-unchanged negative test (/trail, /signals still no require_role, cross-tenant returns zero rows via composite PK not RBAC); the fake-200 failure-path test (D3); WS-J canary pairs-with; WS-F CI-assertion pass.
14. Implementation-status table — DONE (primitives live on dev), NOT-DONE (18 ungated routes, edge authorizer, ADR-037), OPEN (AD-7 timing), with file:line evidence so plan-workstreams can skip built work.
15. Cross-references block — Implements FR-10.1/10.3/10.5/13.1/13.3/6.8/NFR-10; Decisions ADR-037(new)/ADR-035/ADR-034/ADR-019/AD-7/AD-8; Shared contracts (require_role/require_platform/verify_alb_oidc/resolve_operator_tenant/OperatorContext/the generalized ownership helper/the 18 routes/the sigma retire chain); Upstream LLD-26 sec 5-6 + LLD-08 sec 6.5 + lld/35 sec 3.3; Sibling refs WS-G/WS-A/WS-D/WS-F/WS-J/WS-K; Memory links.

## VERIFIED CURRENT LINE NUMBERS (WS doc's are stale — use these)
Policy CRUD: create_policy routes.py:1172, update_policy:1216, delete_policy:1271, set_policy_status:1313. Agent-policy bind: attach_agent_policy:882, detach_agent_policy:902. Connections: create_connection:742, update_connection:762, test_connection:788, scan_connection:808, delete_connection:822. Sigma: update_sigma_rule:1446 (-> _bump_enforcement_version sigma_rules_service.py:402). Quarantine: release_session:1816, quarantine_session:1730. Rollback: rollback_action:1601, rollback_conversation:1660. Discovery: discovery_import:697. Verdict: post_decision_verdict:916. Signals: post_session_signal:453. Correct-as-is data-plane read (DO NOT gate): get_session_trail:393. Positive template: tenancy_routes.py 10 gates (require_role lines 86/138/151/234/267/290/309/349 + require_platform 437/454), _assert_owns_agent:48. Only gated route in routes.py today: delete_feedback_subject ~:834 require_role('admin').

## PER-ROUTE TARGET GATE MAP
require_role('editor') + tenant-own: create_policy, update_policy, set_policy_status, attach_agent_policy, detach_agent_policy(+assert owns agent), test_connection, scan_connection, discovery_import(+tenant-scope imported ids).
require_role('admin') + tenant-own: delete_policy, create_connection, update_connection, delete_connection, release_session, quarantine_session, rollback_action, rollback_conversation.
require_platform (NOT tenant): update_sigma_rule + the _bump_enforcement_version write.
authenticate + tenant-own (derive operator from ctx): post_decision_verdict (18).
Design-only, build deferred (D4): post_session_signal (19) dedicated data-plane producer credential + tenant-scope.
UNCHANGED (no require_role, Invariant 6): get_session_trail, /signals reads.

## TENETS (anchor the doc)
1. Enforcement is local; the control plane is never on the action path — WS-M gates the CONTROL plane; must not add latency to /v1/validate.
2. Fail secure, never fail open — missing/invalid OIDC->401, below-role->403, unknown role->deny; the fake-200 finding directly violates this.
3. Deny-by-default, explainable — every 403 names its reason; audit attribution from verified ctx, not spoofable body/header.
4. Multi-tenant from the foundation, not retrofitted — anti-IDOR ownership assert on every mutation, not just authn.
5. HLD tie-breaker D: an unattributable verdict is a metering + isolation defect — derive operator/operator_id from verified ctx.
6. Reuse discipline — WS-M is the COVERAGE owner reusing primitives already built + live; do NOT rebuild LLD-26 sec 5-6 / LLD-08 sec 6.5 machinery. Build NOTHING new for RBAC (no Casbin/Oso/Cedar-for-console; the FastAPI Depends ladder IS the idiom).
7. HLD sec 6.2(f) (do not re-litigate): Cognito-now behind the IdP-neutral seam; server-derived sentra-tenant-members membership is the tenant authority, never email domain; provider switch done LAST.

## FOOTGUNS
- deps.py/routes.py/tenancy_routes.py shared with LLD-26/WS-D/WS-G — coordinate edits.
- After gating a route MUST re-flush API GW (create-deployment) or it 403s at the edge for the wrong reason ([[apigw-per-resource-no-proxy]], [[sentra-prod-deploy-mechanism]]).
- Do NOT gate data-plane reads get_session_trail/signals (Invariant 6 — isolation is structural via verified-JWT contextvar + composite PK, WS-D sec D5.3).
- Copying the tenant-scoped delete_feedback_subject pattern onto the sigma route = wrong-scope trap (M3 must be platform).
