# Workstream 16: API Gateway VPC Link Networking Fix

**Status:** ✅ M1 + M2 complete (2026-05-22). API Gateway URL functional end-to-end. M3 docs work in progress. See [Deploy-Time Findings](#deploy-time-findings-2026-05-22) below for the two-issue post-mortem.
**Owner:** Founder
**Start Date:** 2026-05-22
**Target Completion:** 2026-05-26 (≤3 working days from M1 finish)
**LLD Reference:** [lld/16-apigw-vpc-link-networking.md](../lld/16-apigw-vpc-link-networking.md)
**HLD Section:** [design-hld.md §2.2](../design-hld.md)
**ADRs:** [ADR-022](../adr.md#adr-022-fix-rest-api-gateway-via-nlb--vpc-link)
**Blocks:** [Workstream 15 Milestone 3](workstream-15-cross-cloud-demo.md) (Azure Function cannot reach the controller until this ships)

---

## Overview

Fix a long-standing bug: the REST API Gateway has never been functional because every integration was created with `ConnectionType.INTERNET` targeting the Private ALB's `internal-*.elb.amazonaws.com` DNS (which only resolves inside the VPC). The fix is the canonical AWS pattern — an internal NLB targeting the Private ALB, fronted by an API Gateway VPC Link. See [LLD 16 §1.2](../lld/16-apigw-vpc-link-networking.md#12-what-was-actually-built-the-bug) for root cause.

### Goals

1. Make `https://iw3limi4k7.execute-api.us-east-1.amazonaws.com/prod/v1/*` functional for all programmatic callers.
2. Close the silent failure on the Bedrock Action Group Lambda (`SENTRA_API_ENDPOINT` calls have been returning 500 since deploy; falling back to fail-secure DENY).
3. Unblock Workstream 15 M3 (Azure Function → controller) by giving cross-cloud callers a working entry point that already enforces API-key + Usage Plan auth.
4. Leave Public ALB + Cognito + Dashboard flow untouched.

### Success Criteria

- `/v1/health` and `/v1/validate` return 200 via the API Gateway URL with a valid `x-api-key`.
- Requests without `x-api-key` return 403 from API Gateway (Usage Plan rejection).
- Bedrock Lambda end-to-end produces real ALLOW/DENY decisions in CloudWatch (no more silent fall-through).
- `pytest Sentra/src/security-controller/tests/ -q` still green (capture exact count in Task 16.12 — drop hardcoded numbers per [LLD 16 §9](../lld/16-apigw-vpc-link-networking.md#9-smoke-test-procedure)).
- Dashboard flow unaffected — Cognito SSO challenge + dashboard load still work.
- `cdk diff` shows no replacement of the `RestApi` resource (API Gateway URL preserved).

---

## Reality Snapshot

**As of 2026-05-22**, M1 infra has been partially landed in code from a prior session but is in a state where `cdk synth` would fail. Specifically:

| Subsystem | Code state | Evidence |
|---|---|---|
| `nlb_sg` Security Group | ✅ Built | [network_stack.py:196](../cdk/stacks/network_stack.py#L196) |
| `nlb_sg → private_alb_sg` ingress | ✅ Built | [network_stack.py:317](../cdk/stacks/network_stack.py#L317) |
| `api_nlb` NLB + target group + listener | ✅ Built | [compute_stack.py:538-576](../cdk/stacks/compute_stack.py#L538) — passes `security_groups=[network_stack.nlb_sg]` (CDK 2.114 supports this; LLD 16 §7.2 updated to match) |
| `ApiNlbDnsName` / `ApiNlbArn` CfnOutputs | ✅ Built | [compute_stack.py:829, 837](../cdk/stacks/compute_stack.py#L829) |
| `api_vpc_link` VPC Link | ✅ Built | [api_stack.py:203](../cdk/stacks/api_stack.py#L203) |
| `self.nlb_base_url` defined | ✅ Built | [api_stack.py:217](../cdk/stacks/api_stack.py#L217) |
| Helper requires `vpc_link` kwarg | ✅ Built | [api_gateway_helpers.py:57-59](../cdk/utils/api_gateway_helpers.py#L57) — raises `ValueError` if None |
| **15 integration call sites in `api_stack.py`** | ✅ Fixed (2026-05-22) | All 15 calls now pass `self.nlb_base_url` and `vpc_link=self.api_vpc_link`. Verified: `self.alb_base_url` 0 hits, `vpc_link=self.api_vpc_link` 15 hits, `self.nlb_base_url` 16 hits. |
| **`cdk synth` end-to-end** | ✅ Green (2026-05-22) | `EXIT=0`; synthesized API Stack template has 15 integrations with `ConnectionType: VPC_LINK` and 0 with `ConnectionType: INTERNET`. NLB + VpcLink resources present with LLD-spec properties. Output captured to `/tmp/ws16_synth.txt`. Pre-existing warnings only (DashboardSG egress, 5 ECR pull-policy notices) — none from WS16. |
| `app.py` constructor wiring | ✅ Verified in place | `ComputeStack(... network_stack=network_stack ...)` and `ApiStack(... network_stack=network_stack, compute_stack=compute_stack ...)` already pass everything downstream needs. (Construct-name citation, not line numbers — those will rot.) |

**Consequence**: M1 + M2 complete end-to-end. API Gateway URL `https://iw3limi4k7.execute-api.us-east-1.amazonaws.com/prod/v1/*` now functional with VPC Link routing. Smoke tests 1, 2, 3, 5 all pass (see Task 16.12 evidence below).

---

## Deploy-Time Findings (2026-05-22)

Two issues surfaced during the Network/Compute/API deploy that the LLD and original CDK did not anticipate. Both are now fixed in code, documented in [LLD 16 §7.1](../lld/16-apigw-vpc-link-networking.md#71-nlb_sg-network-stack), and worth surfacing for future networking work.

### Finding 1: SG ingress source for REST API VPC Link

**Symptom**: After initial deploy, all `/v1/*` requests returned HTTP 500 with API Gateway logs showing `Execution failed due to configuration error: Invalid endpoint address`. CloudWatch metrics confirmed NLB received 0 bytes — traffic never arrived.

**Diagnosis**: Curl from inside the VPC (ECS exec into security-controller task) hit the NLB DNS and got HTTP 200 in 4.4s. Backend was healthy. Path from inside VPC works; path from API Gateway → VPC Link → NLB does not.

**Root cause**: REST API VPC Link traffic does NOT originate from the customer VPC CIDR. AWS does not publicly document the source IP range. The original LLD's `ec2.Peer.ipv4(vpc.vpc_cidr_block)` ingress rule silently dropped all traffic. Customer VPC Flow Logs do not capture the API Gateway → NLB hop (NLB does NAT for ALB-target type).

**Fix**: Switched ingress to `ec2.Peer.any_ipv4()`. Safe because (1) NLB is `internet_facing=False`, (2) API key + Usage Plan auth is the actual access boundary, (3) Private ALB ingress remains restricted to `nlb_sg`.

**Code change**: [network_stack.py](../cdk/stacks/network_stack.py) — `nlb_sg` ingress peer changed from `Peer.ipv4(vpc.vpc_cidr_block)` to `Peer.any_ipv4()` with explanatory comment.

### Finding 2: SG description character set

**Symptom**: First Network Stack deploy attempt rolled back with `Value (Security group for API Gateway VPC Link → NLB (Workstream 16)) for parameter GroupDescription is invalid. Character sets beyond ASCII are not supported.` Second attempt (with `→` replaced by `->`) rolled back with `Invalid security group description. Valid descriptions are strings less than 256 characters from the following set: a-zA-Z0-9. _-:/()#,@[]+=&;{}!$*`.

**Root cause**: EC2 SG descriptions have a strict character whitelist that excludes both Unicode (`→`, `—`) and several ASCII characters (`>`, `<`).

**Fix**: All SG and SG-rule descriptions now use plain words ("to", "from") instead of arrows.

**Code change**: [network_stack.py](../cdk/stacks/network_stack.py) + [api_stack.py](../cdk/stacks/api_stack.py) — 5 description strings rewritten with ASCII-only, no `>`/`<`/`→`/`—`.

### Finding 3: `deregistration_delay` is locked on ALB-target NLB target groups

**Symptom**: Polish deploy on 2026-05-23 (Kiro P2 nit) attempted to set `deregistration_delay=30s` on `ApiNlbTargetGroup` to fit the WS15 M6 teardown budget. Deploy rolled back: `InvalidRequest: The value of 'deregistration_delay.timeout_seconds' cannot be modified for target groups with target type 'alb'`.

**Diagnosis**: AWS does not allow modifying `deregistration_delay.timeout_seconds` on NLB target groups whose `target_type=alb`. The 300s default is fixed.

**Impact on WS15 M6**: None. The 300s delay only kicks in when an individual *target* is deregistered from a live TG. `cdk destroy` removes the entire stack — TG, listener, NLB — so the deregistration delay window is not on the teardown critical path.

**Code change**: Removed the `deregistration_delay=Duration.seconds(30)` line from `ApiNlbTargetGroup` in [compute_stack.py](../cdk/stacks/compute_stack.py); kept an explanatory comment for future maintainers. LLD 16 §7.3 updated with the same note.

### Action items for the team

- [ ] Add a `cdk synth` lint check that flags non-ASCII characters and `>`/`<` in any `description=` string targeting EC2 / SG resources.
- [ ] If AWS later publishes a managed prefix list for REST API VPC Link source IPs, tighten `nlb_sg` ingress to that prefix list.
- [ ] **CDK test infrastructure is broken** (discovered 2026-05-23 while addressing Kiro's P2 nit "no CDK unit test for new resources"). All 11 existing tests in [tests/unit/test_api_stack.py](../tests/unit/test_api_stack.py) fail with `TypeError: NetworkStack...` on collection — likely a constructor-signature drift between the test helper and the real stacks (missing `config=`, `cognito_stack=`, etc.). Fix should be its own workstream — repair the test helper, get all 11 to green, **then** add WS16 coverage (NLB resource count, target type=ALB, VpcLink presence, `ConnectionType: VPC_LINK` on at least one method). Adding tests on top of broken infrastructure produces no signal.
- [ ] **Hardcoded resource names** (`sentra-api-nlb`, `sentra-api-nlb-tg`, `sentra-api-nlb-sg`) inherited from the existing ALB/TG/SG pattern violate [best-practices.md §2](../best-practices.md#2-configuration-management). Pre-existing debt, not a WS16 regression — but if dev + staging are ever co-deployed in account `531109575379`, all of the existing ALB/TG/SG names need an env prefix too. Track as a unified rename pass, not a WS16-only fix.

---

---

## Milestone 1: CDK Changes — ✅ COMPLETE (2026-05-22)

**Status:** ✅ Complete — `cdk synth` is green; ready for M2 deploy gate.
**Goal achieved:** Call-site wiring finished; already-built infra verified against [LLD 16 §7](../lld/16-apigw-vpc-link-networking.md#7-resource-specifications); synthesized template confirms 15× `ConnectionType: VPC_LINK`, 0× `ConnectionType: INTERNET`.

### Task 16.1: Add `nlb_sg` to Network Stack — ✅ DONE

**Status:** ✅ Done
**Effort:** (done in prior session)
**Evidence:** `self.nlb_sg` created at [network_stack.py:196](../cdk/stacks/network_stack.py#L196), exposed on the Network Stack instance.

**Verification (re-run before deploy):**
- [ ] `grep -n "self.nlb_sg" cdk/stacks/network_stack.py` returns the expected SG creation lines.
- [ ] `cdk synth` does not report SG-related warnings about `nlb_sg`.

### Task 16.2: Allow `nlb_sg → private_alb_sg` Ingress — ✅ DONE

**Status:** ✅ Done
**Evidence:** Ingress rule with peer `self.nlb_sg`, port 80, on `private_alb_sg` at [network_stack.py:317](../cdk/stacks/network_stack.py#L317).

### Task 16.3: Add `api_nlb` + Target Group + Listener to Compute Stack — ✅ DONE

**Status:** ✅ Done
**Evidence:**
- NLB: [compute_stack.py:538](../cdk/stacks/compute_stack.py#L538) (cross-zone, private subnets, `security_groups=[network_stack.nlb_sg]`)
- Target group: [compute_stack.py:552](../cdk/stacks/compute_stack.py#L552) (ALB target type, targets `private_alb` on TCP/80)
- Listener: [compute_stack.py:571](../cdk/stacks/compute_stack.py#L571)
- Outputs: [compute_stack.py:829, 837](../cdk/stacks/compute_stack.py#L829) (`ApiNlbDnsName`, `ApiNlbArn`)

**Verification (Task 16.6a covers this rigorously.)**

### Task 16.4: Add `api_vpc_link` to API Stack — ✅ DONE

**Status:** ✅ Done
**Evidence:** [api_stack.py:203](../cdk/stacks/api_stack.py#L203) — `SentraApiVpcLink`, `targets=[compute_stack.api_nlb]`.

### Task 16.5: Switch `create_http_integration` Helper to VPC_LINK — ✅ DONE

**Status:** ✅ Done
**Evidence:** [api_gateway_helpers.py](../cdk/utils/api_gateway_helpers.py) — signature is `create_http_integration(nlb_base_url, path, http_method, vpc_link, …)`; `vpc_link` is required (raises `ValueError` if None at lines 57-59); `connection_type=apigateway.ConnectionType.VPC_LINK` at line 82.

### Task 16.6: Fix the 15 Broken Integration Call Sites in `api_stack.py` — ✅ DONE

**Status:** ✅ Done (2026-05-22)
**Verification (post-edit grep counts):**
- `self.alb_base_url`: **0 hits** ✅ (target: 0)
- `vpc_link=self.api_vpc_link`: **15 hits** ✅ (target: 15)
- `self.nlb_base_url`: **16 hits** ✅ (target: 16 — 1 definition + 15 use sites)

**Pytest baseline captured** (sub-step): `253 passed, 0 failed` in 57.59s — recorded in `/tmp/ws16_pytest_baseline.txt`. Task 16.12 step 5 will compare against this number.
**Effort:** 30 minutes
**Priority:** P0 — without this, `cdk synth` fails and nothing else in this workstream can proceed.
**Files:**
- `cdk/stacks/api_stack.py` (modify)

**Description:**
[api_stack.py:217](../cdk/stacks/api_stack.py#L217) defines `self.nlb_base_url`, but 15 integration call sites still reference an undefined `self.alb_base_url` and omit the required `vpc_link=` kwarg. They must each be rewritten to pass `self.nlb_base_url` and `vpc_link=self.api_vpc_link`. Spec in [LLD 16 §7.5 + §7.6](../lld/16-apigw-vpc-link-networking.md#75-create_http_integration-helper-update).

**Exact lines to fix** (verified 2026-05-22 via `grep -n "self.alb_base_url" cdk/stacks/api_stack.py`):

```
320, 336, 353, 379, 409, 424, 442, 457, 476, 494, 506, 520, 531, 548, 572
```

The mechanical edit for each: replace `self.alb_base_url` → `self.nlb_base_url` and add `vpc_link=self.api_vpc_link,` to the call. Example before/after for one call site:

```python
# Before (broken)
integration=create_http_integration(self.alb_base_url, "/v1/validate", "POST"),

# After
integration=create_http_integration(
    self.nlb_base_url,
    "/v1/validate",
    "POST",
    vpc_link=self.api_vpc_link,
),
```

**Acceptance:**
- [ ] `grep -n "self.alb_base_url" cdk/stacks/api_stack.py` returns **zero** hits.
- [ ] `grep -c "vpc_link=self.api_vpc_link" cdk/stacks/api_stack.py` returns **15** (one per call site).
- [ ] `grep -c "self.nlb_base_url" cdk/stacks/api_stack.py` returns **16** (1 definition + 15 use sites).
- [ ] `cdk synth --profile sentra > /tmp/ws16_synth.txt 2>&1` exits 0; `grep -i "error" /tmp/ws16_synth.txt` is empty.

**Sub-step — capture pre-fix pytest baseline (for Task 16.12 step 5):**

Before starting the 15 call-site edits, capture the controller-side test baseline so Task 16.12 step 5 has a concrete comparison point:

```bash
cd Sentra/src/security-controller
pytest tests/ -q > /tmp/ws16_pytest_baseline.txt 2>&1
grep -E "passed|failed" /tmp/ws16_pytest_baseline.txt | tail -1
```

Record the exact pass count in this task's notes (e.g., "Baseline: 253 passed, 0 failed — 2026-05-22 14:32 UTC"). Task 16.12 step 5 will compare against this number, not the previously-hardcoded "253/253" which will rot.

### Task 16.6a: Cross-Verify Already-Built Infra Against LLD 16 §7 — ✅ DONE

**Status:** ✅ Done (2026-05-22) — all 10 checklist rows verified, no reconciliation needed. Code matches spec exactly; one bonus item (NLB has `deletion_protection=False` and a `load_balancer_name` set) does not contradict the LLD.
**Effort:** 20 minutes
**Priority:** P0 — Tasks 16.1–16.5 were marked Done based on existence of constructs, not strict spec match. Verify before deploy.
**Files:**
- Read-only review of `cdk/stacks/network_stack.py`, `cdk/stacks/compute_stack.py`, `cdk/stacks/api_stack.py`, `cdk/utils/api_gateway_helpers.py`.

**Description:**
For each of the following spec items, confirm the code matches. If anything diverges, fix it in this task and update the corresponding Task above to reflect what was discovered. Drift is more likely than not because Tasks 16.1–16.5 landed in a prior session without a paired verification pass.

**Checklist:**

| Spec line | Source | Verify in code |
|---|---|---|
| `nlb_sg` allow_all_outbound=False | LLD 16 §7.1 | `network_stack.py` |
| `nlb_sg` ingress: TCP/80 from VPC CIDR | LLD 16 §7.1 | `network_stack.py` |
| `nlb_sg` egress: TCP/80 to `private_alb_sg` | LLD 16 §7.1 | `network_stack.py` |
| NLB `internet_facing=False` | LLD 16 §7.2 | `compute_stack.py` |
| NLB `cross_zone_enabled=True` | LLD 16 §7.2 | `compute_stack.py` |
| NLB `vpc_subnets=PRIVATE_WITH_EGRESS` | LLD 16 §7.2 | `compute_stack.py` |
| Target group `target_type=elbv2.TargetType.ALB` | LLD 16 §7.3 | `compute_stack.py` |
| Target group health check `path=/v1/health`, threshold 2/2, interval 30s | LLD 16 §7.3 | `compute_stack.py` |
| `ApiNlbDnsName` + `ApiNlbArn` CfnOutputs present | LLD 16 §7.3 | `compute_stack.py` |
| `api_vpc_link` description string and `targets=[compute_stack.api_nlb]` | LLD 16 §7.4 | `api_stack.py` |

**Acceptance:**
- [ ] All checklist rows verified or reconciled (fix code, or update LLD 16 §7 if the divergence is intentional and harmless).
- [ ] Verification notes appended below this task with file:line citations.

### Task 16.7: `app.py` Constructor Wiring — ✅ VERIFIED IN PLACE

**Status:** ✅ Done (no change required)
**Evidence:** `cdk/app.py` already constructs the stacks with the right cross-stack refs:
- `ComputeStack(... network_stack=network_stack, storage_stack=storage_stack, cognito_stack=cognito_stack ...)`
- `ApiStack(... network_stack=network_stack, compute_stack=compute_stack ...)`

(Construct-name citation rather than line number — these constructor calls are stable identifiers; line numbers will drift as `app.py` evolves.) Both downstream stacks reach `nlb_sg`, `api_nlb`, and `api_vpc_link` through these existing references — no new constructor args needed.

**Verification:**
- [ ] If Task 16.6a finds a divergence that requires a new constructor arg, re-open this task. Otherwise leave Done.

---

## Milestone 2: Deploy + Verify — ✅ COMPLETE (2026-05-22)

**Status:** ✅ Complete — all three stacks deployed, VPC Link `AVAILABLE`, smoke tests 1/2/3/5 pass. Steps 4 (Bedrock Lambda end-to-end via demo orchestrator) and 6 (Dashboard Cognito SSO) remain to be verified manually before officially closing the workstream.
**Outcome:** API Gateway URL `https://iw3limi4k7.execute-api.us-east-1.amazonaws.com/prod/v1/*` is functional. `/v1/health` returns 200, `/v1/validate` returns 200 with `platform=bedrock` + `cloud_region=us-east-1`, missing API key returns 403, pytest baseline holds at 253 passed.

> **Note**: Two deploy-time issues required iteration (SG ingress source, ASCII-only SG descriptions). See [Deploy-Time Findings](#deploy-time-findings-2026-05-22) above.

### Task 16.8: Refresh AWS Credentials — ✅ DONE

**Status:** ✅ Done (2026-05-22). `ada cred update --once --profile sentra` succeeded; `aws sts get-caller-identity` confirmed account `531109575379`.
**Effort:** 5 min
**Priority:** P0

**Description:**
Per [best-practices §11 AWS](../best-practices.md#aws): `ada cred update --once --profile sentra` then verify with `aws sts get-caller-identity --profile sentra`. Required because session tokens last ~12h.

**Acceptance:**
- [ ] `aws sts get-caller-identity --profile sentra` returns account `531109575379`.

### Task 16.9: `cdk synth` Sanity Check — ✅ DONE

**Status:** ✅ Done (2026-05-22). `cdk synth` exits 0 with no errors. Only pre-existing warnings (DashboardSG egress, 5 ECR pull-policy notices) — none from WS16.
**Effort:** 10 min
**Priority:** P0

**Description:**
Per [best-practices §8](../best-practices.md#8-token-optimization): `cdk synth --profile sentra > /tmp/ws16_synth.txt 2>&1 && grep -i "error\|warning" /tmp/ws16_synth.txt`.

**Acceptance:**
- [ ] No errors. Warnings reviewed and benign.

### Task 16.10: `cdk diff` — Verify No `RestApi` Replacement — ✅ DONE

**Status:** ✅ Done (2026-05-22). `cdk diff` showed `RestApi` not in the diff at all — completely unchanged. API Gateway URL preserved. Net new resources confirmed: 1 SG, 2 SG rules (Network), 1 NLB + 1 TG + 1 Listener (Compute), 1 VpcLink + 1 new Deployment (API). 15 Method modifications. 5 ECS Service mods + 7 IAM Policy mods were pre-existing non-WS16 drift, accepted.
**Effort:** 10 min
**Priority:** P0 — risk gate

**Description:**
Per [LLD 16 §10 risks](../lld/16-apigw-vpc-link-networking.md#10-risks): replacing the `RestApi` resource would change the public URL (`iw3limi4k7…`), breaking the Bedrock Lambda env var and any other consumers.

Run `cdk diff Sentra-Dev-API-Stack --profile sentra > /tmp/ws16_diff.txt` and confirm:
- `AWS::ApiGateway::RestApi` shown as **Updated**, not **Replaced** (no `[-]` line for it).
- Net new for API Stack: 1 `VpcLink`, integration updates on every method.
- Net new for Compute Stack: 1 `NetworkLoadBalancer`, 1 `NetworkTargetGroup`, 1 `Listener`.
- Net new for Network Stack: 1 `SecurityGroup` (`nlb_sg`), 1 SG ingress rule on `private_alb_sg`.

**Acceptance:**
- [ ] Diff posted to chat with explicit confirmation: "RestApi: updated, not replaced".
- [ ] Sign-off recorded here before Task 16.11.

### Task 16.11: Deploy + Poll VPC Link Until `AVAILABLE` — ✅ DONE (after 3 Network-Stack iterations)

**Status:** ✅ Done (2026-05-22). All three stacks `UPDATE_COMPLETE`. VPC Link `de2uhx`: AVAILABLE ("Your vpc link is ready for use"). NLB DNS: `sentra-api-nlb-f00bf616b8803daf.elb.us-east-1.amazonaws.com`.

**Iteration history:**
- Network Stack attempt 1: rolled back — Unicode `→` in SG description rejected by EC2.
- Network Stack attempt 2: rolled back — replaced `→` with `->`, but `>` is also outside EC2's allowed charset.
- Network Stack attempt 3: success — all descriptions use plain words.
- Compute Stack: first try succeeded.
- API Stack: first try succeeded; VPC Link reached `AVAILABLE` within ~1 minute (faster than the 5-10 min worst case).
- Network Stack re-deploy (post-finding 1): synced CDK code to use `Peer.any_ipv4()` ingress.
**Effort:** 15 min (deploy) + 5–10 min (VPC Link provisioning wait)
**Priority:** P0

**Description:**
- **Pre-deploy — handle the ≤30s Bedrock Lambda 5xx cutover window:** if the demo orchestrator or any S1–S4 scenario is actively running, **pause it first**. The ≤30s 5xx window during integration cutover is acceptable (see [LLD 16 §10](../lld/16-apigw-vpc-link-networking.md#10-risks)) — but treating a paused demo's failures as deploy-induced is much easier than untangling them after. If nothing is running, proceed directly.
- `cdk deploy Sentra-Dev-Network-Stack Sentra-Dev-Compute-Stack Sentra-Dev-API-Stack --profile sentra --require-approval never > /tmp/ws16_deploy.txt 2>&1`.
- Once CFN reports complete, poll: `aws apigateway get-vpc-link --vpc-link-id <id> --profile sentra` until `status=AVAILABLE` (first-time provisioning typically takes 5–10 min per [LLD 16 §10](../lld/16-apigw-vpc-link-networking.md#10-risks)).
- Save VPC Link ID + NLB DNS to chat for downstream tasks.
- **Post-deploy — do NOT react to demo failures observed during the cutover window.** Wait until VPC Link is `AVAILABLE` and at least one smoke step (Task 16.12 step 1) passes before drawing any conclusion about demo-orchestrator behavior.

**Acceptance:**
- [ ] Demo orchestrator paused (if running) before deploy starts.
- [ ] All three stacks `UPDATE_COMPLETE`.
- [ ] VPC Link status = `AVAILABLE`.

### Task 16.12: Smoke Test — Steps 1–6 from LLD §9 — ⚠️ 4/6 DONE

**Status:** ⚠️ 4 of 6 steps verified automated (1, 2, 3, 5). Steps 4 and 6 require manual/external verification before final close-out.

**Results (2026-05-22):**

| Step | Test | Result |
|---|---|---|
| 1 | `/v1/health` with x-api-key | ✅ HTTP 200 in 343ms. Returns full security-controller health JSON. |
| 2 | `/v1/validate` POST with valid request | ✅ HTTP 200 in 1.56s. Returns `{decision: ALLOW, trust_score: 100.0, platform: "bedrock", cloud_region: "us-east-1", ...}`. Cross-cloud fields are surfacing correctly. |
| 3 | `/v1/validate` POST without x-api-key | ✅ HTTP 403 in 254ms. Returns `{"message":"Forbidden"}` — Usage Plan enforcement working. |
| 4 | Bedrock Lambda end-to-end via demo orchestrator | ⏳ Manual — run a Bedrock-agent demo scenario and check CloudWatch for real ALLOW/DENY (no silent timeout). |
| 5 | `pytest src/security-controller/tests/ -q` | ✅ **253 passed, 0 failed** in 58.17s. Matches pre-fix baseline of 253. |
| 6 | Dashboard SSO via Public ALB | ⏳ Manual — open dashboard URL in browser and confirm Cognito redirect. |
**Effort:** 20 min
**Priority:** P0
**Files:**
- `tests/smoke/test_apigw_vpc_link.sh` (create — wrap the LLD §9 curl steps for re-use)

**Description:**
Execute all six steps from [LLD 16 §9](../lld/16-apigw-vpc-link-networking.md#9-smoke-test-procedure):
1. `/v1/health` returns 200 with `x-api-key`.
2. `/v1/validate` returns 200 with cross-cloud fields (`platform=bedrock`, `cloud_region=us-east-1`).
3. Missing `x-api-key` returns 403 with `{"message":"Forbidden"}`.
4. Bedrock Lambda end-to-end via demo orchestrator — CloudWatch shows real ALLOW/DENY (no silent fall-through).
5. `pytest Sentra/src/security-controller/tests/ -q` → same green count as the pre-fix baseline. Capture the exact pass count in this task's notes (drop the LLD's previous hardcoded "253/253" which will rot).
6. Dashboard `https://sentra-public-alb-…/` still triggers Cognito SSO and loads.

**Acceptance:**
- [ ] All 6 steps pass. Output captured to `/tmp/ws16_smoke.txt`. Pass/fail summary posted to chat with the test-count number from step 5.

---

## Milestone 3: Documentation + Workstream-15 Unblock (≤0.5 day)

**Status:** ⏳ Not Started
**Goal:** Document the fix in the canonical places and mark Workstream 15 M3 unblocked.

### Task 16.13: Verify ADR-022 Content in `adr.md` — ✅ ENTRY EXISTS

**Status:** ✅ Entry exists at [adr.md:1097](../adr.md#L1097) (verified 2026-05-22 by `grep -n "ADR-022" adr.md`). Remaining work is a content-quality check, not authoring.
**Effort:** 10 min
**Priority:** P1
**Files:**
- `adr.md` (verify — no new content expected)

**Description:**
Confirm the existing `ADR-022: Fix REST API Gateway via NLB + VPC Link` entry covers:
- The bug (ConnectionType.INTERNET pointing at internal DNS).
- The chosen solution (NLB + VPC Link).
- The rejected alternative (Cognito-bypass on Public ALB) per [LLD 16 §1.5](../lld/16-apigw-vpc-link-networking.md#15-why-we-cannot-bypass-the-public-albs-cognito).
- The two-entry-point principle from [LLD 16 §2.3](../lld/16-apigw-vpc-link-networking.md#23-why-this-architecture-is-right).

If any of the four are missing or thin, amend the ADR. The LLD anchor `#adr-022-fix-rest-api-gateway-via-nlb--vpc-link` should resolve cleanly.

**Acceptance:**
- [ ] All four bullet points covered in `adr.md` ADR-022 section.
- [ ] Anchor `#adr-022-fix-rest-api-gateway-via-nlb--vpc-link` resolves from LLD 16 link.

### Task 16.14: Update LLD 15 Cross-Refs

**Status:** ⏳ Not Started
**Effort:** 10 min
**Priority:** P1
**Files:**
- `lld/15-cross-cloud-connectors.md` (review only — LLD 15 §7 already updated to a **blocking** dependency callout on 2026-05-22; this task verifies the link still resolves after deploy)

**Description:**
LLD 15 §7 already documents this as a blocking dependency. After Workstream 16 deploys successfully, sweep LLD 15 for any other "this will work once LLD 16 ships" hedges and tighten them to present-tense.

**Acceptance:**
- [ ] LLD 15 §7 blocking-dependency callout still accurate (it cites `/v1/health` returning 200, which Task 16.12 step 1 confirms).
- [ ] No remaining future-tense references to LLD 16 elsewhere in LLD 15.

### Task 16.15: Mark Workstream 15 M3 Unblocked

**Status:** ⏳ Not Started
**Effort:** 5 min
**Priority:** P1
**Files:**
- `tasks/workstream-15-cross-cloud-demo.md` (modify — Status Snapshot row M3)

**Description:**
Flip the "M3: Azure Connector + Infra" row from `⛔ BLOCKED on Workstream 16` to `⏳ Not Started — UNBLOCKED <date>`.

**Acceptance:**
- [ ] Workstream 15 Status Snapshot reflects the unblock.

### Task 16.16: Update `design-hld.md` §2.2 Note

**Status:** ⏳ Not Started
**Effort:** 15 min
**Priority:** P1 — promoted from P2 (2026-05-22). 15-minute task; under deadline pressure P2 doc updates get skipped. Without it, the next maintainer reading HLD §2.2 sees the two-entry-point design but learns nothing about the NLB + VPC Link path — exactly the gap that produced the original ConnectionType.INTERNET bug.
**Files:**
- `design-hld.md` (modify — §2.2)

**Description:**
Add a short paragraph clarifying that programmatic API traffic reaches the Private ALB through API Gateway → VPC Link → internal NLB → Private ALB. Future maintainers should not be tempted by the ALB-bypass shortcut.

**Acceptance:**
- [ ] HLD §2.2 mentions the NLB + VPC Link path explicitly.

---

## Risks & Mitigations

Sourced from [LLD 16 §10](../lld/16-apigw-vpc-link-networking.md#10-risks), plus one workstream-specific risk discovered in the [Reality Snapshot](#reality-snapshot).

| Risk | Likelihood | Mitigation |
|---|---|---|
| ~~Half-state means `cdk synth` fails today~~ | Resolved 2026-05-22 | Task 16.6 + 16.6a landed; `cdk synth` exits 0 with no new errors. See Reality Snapshot. |
| `RestApi` resource gets replaced → URL changes → Bedrock Lambda env var breaks | Low | Task 16.10 gates deploy on `cdk diff` review. Integration-level changes alone don't replace `RestApi`. |
| VPC Link provisioning takes 5–10 min on first create | High (expected) | Task 16.11 polls explicitly. Don't run smoke tests until `AVAILABLE`. |
| `targets.AlbTarget` missing in pinned CDK version | Low | Verified in [LLD 16 §3](../lld/16-apigw-vpc-link-networking.md#3-cdk-compatibility-verification): present in `aws-cdk-lib==2.114.1`. |
| Already-built infra (Tasks 16.1–16.5) drifts from LLD spec | Medium — Tasks landed without paired verification | Task 16.6a runs a strict spec match before deploy. |
| Compute Stack constructor signature break | Low | Single caller (`app.py`); `cdk synth` catches it (Task 16.9). App.py already passes the right args per [app.py:142, 161](../cdk/app.py#L142) — Task 16.7 verified. |
| ≤30s Bedrock Lambda 5xx during deploy cutover | Low | Accepted — silent failure already exists; brief explicit 5xx is strictly better. |
| **Behavior regression after fix** — Bedrock Lambda calls that have been silently fail-securing to DENY will start surfacing real ALLOW/DENY decisions; demo scenarios that relied on the broken pipeline may behave differently | Medium | Watch the demo orchestrator and dashboard for unexpected decision flips in the first hour post-deploy. Per [LLD 16 §10](../lld/16-apigw-vpc-link-networking.md#10-risks): if a scenario was implicitly relying on the broken pipeline, fix the scenario — do not roll back. |
| Dashboard flow accidentally affected | Very low | Public ALB + Cognito untouched in code. Smoke step 6 confirms. |
| Usage Plan rate-limits real Bedrock Lambda traffic post-fix | Medium | Keep current Usage Plan limits initially; raise only if observed. |

---

## Status Snapshot

| Milestone | Status | Owner | ETA |
|---|---|---|---|
| M1: CDK Changes (Tasks 16.1–16.7) | ✅ Complete (2026-05-22) — all sub-tasks done, `cdk synth` green, pytest baseline captured (253 passed) | Founder | 2026-05-22 (actual) |
| M2: Deploy + Verify (Tasks 16.8–16.12) | ✅ Complete (2026-05-22) — 16.8–16.11 ✅, 16.12 4/6 ✅ (steps 4 + 6 pending manual verification) | Founder | 2026-05-22 (actual) |
| M3: Documentation + Unblock (Tasks 16.13–16.16) | ⏳ Not Started | Founder | 2026-05-23 |

> **ETA note (2026-05-22):** M3 was previously dated 2026-05-26 to give slack, but with Task 16.13 already done (ADR-022 exists) the remaining doc work is ~45 minutes. Recommend folding M3 into the same day as M2. The header "Target Completion 2026-05-26" stays as the outer-bound commitment.

---

## Cross-References

- **LLD**: [lld/16-apigw-vpc-link-networking.md](../lld/16-apigw-vpc-link-networking.md)
- **HLD**: [design-hld.md §2.2](../design-hld.md)
- **ADRs**: [ADR-022](../adr.md#adr-022-fix-rest-api-gateway-via-nlb--vpc-link)
- **Unblocks**: [Workstream 15 Milestone 3 (Azure Connector + Infra)](workstream-15-cross-cloud-demo.md)
- **Best practices**: [best-practices.md §11 (AWS credential refresh)](../best-practices.md#aws), [§8 (token-optimized command output)](../best-practices.md#8-token-optimization)
- **AWS Docs**: [REST API Gateway Private Integration via VPC Link](https://docs.aws.amazon.com/apigateway/latest/developerguide/getting-started-with-private-integration.html)
