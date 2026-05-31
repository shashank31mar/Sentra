# LLD 16: API Gateway VPC Link Networking

**Version**: 1.0
**Last Updated**: 2026-05-22
**Status**: Draft – Ready for Review
**Prerequisites**:
- [LLD 02: API Gateway Layer](02-api-gateway.md) — the original API Gateway design intent
- [LLD 01: CDK Infrastructure](01-cdk-infrastructure.md) — VPC, subnets, baseline stacks
- [design-hld.md §2.2](../design-hld.md) — five-layer split-ALB architecture

**Related Documents**:
- [LLD 15: Cross-Cloud Connectors](15-cross-cloud-connectors.md) — depends on this LLD being shipped
- [Workstream 16: API Gateway VPC Link Fix](../tasks/workstream-16-apigw-vpc-link-networking.md) — execution tracking
- [ADR-022](../adr.md#adr-022-fix-rest-api-gateway-via-nlb--vpc-link) — architectural decision record

---

## Table of Contents

1. [Why This Exists](#1-why-this-exists)
2. [Two-Entry-Point Architecture](#2-two-entry-point-architecture)
3. [CDK Compatibility Verification](#3-cdk-compatibility-verification)
4. [Stack Ownership Matrix](#4-stack-ownership-matrix)
5. [Cross-Stack Reference List](#5-cross-stack-reference-list)
6. [Cyclic-Dependency Analysis](#6-cyclic-dependency-analysis)
7. [Resource Specifications](#7-resource-specifications)
8. [Auth Model](#8-auth-model)
9. [Smoke-Test Procedure](#9-smoke-test-procedure)
10. [Risks](#10-risks)
11. [What This LLD Does Not Change](#11-what-this-lld-does-not-change)
12. [Cross-References](#12-cross-references)

---

## 1. Why This Exists

### 1.1 The Original Design Intent

[design-hld.md §2.2](../design-hld.md) defined two complementary entry points into AWS for the Sentra control plane:

- **Public ALB** — internet-facing, Cognito-authenticated, serves the Streamlit Dashboard to human users.
- **API Gateway (REST)** — internet-facing, API-key-authenticated, serves programmatic API traffic from Lambdas, future cross-cloud connectors, and CI tooling.

This split keeps human and machine traffic on appropriate auth models: SSO for humans, API keys + Usage Plans for machines. [LLD 02 §1.1](02-api-gateway.md) calls API Gateway "the **single public entry point** for Sentra MVP" for programmatic traffic.

### 1.2 What Was Actually Built (the bug)

The CDK helper at [`cdk/utils/api_gateway_helpers.py:58`](../cdk/utils/api_gateway_helpers.py) creates every API Gateway integration with:

```python
return apigateway.HttpIntegration(
    f"{alb_base_url}{path}",                                # internal-*.elb.amazonaws.com — VPC-only DNS
    options=apigateway.IntegrationOptions(
        connection_type=apigateway.ConnectionType.INTERNET, # ← bug
        ...
    )
)
```

`ConnectionType.INTERNET` requires the target hostname to be publicly routable. The integration targets the **Private ALB's** `internal-*.elb.amazonaws.com` DNS — which by AWS design only resolves from inside the VPC. **The API Gateway has never been functional** since this CDK was deployed.

### 1.3 How We Discovered It (2026-05-22)

During Workstream 15 Milestone 2 (cross-cloud policy + validator extensions) smoke-testing, we hit `/v1/health` and `/v1/validate` via the API Gateway URL `https://iw3limi4k7.execute-api.us-east-1.amazonaws.com/prod/` and got HTTP 500 with:

```
x-amzn-errortype: InternalServerErrorException
x-amzn-trace-id: Root=...
```

CloudWatch execution logs (`API-Gateway-Execution-Logs_iw3limi4k7/prod`) showed:

```
Execution failed due to configuration error: Invalid endpoint address
```

That error is API Gateway's way of saying "I can't route to the integration target". Confirmed root cause in CDK.

### 1.4 Who Else This Affects (Beyond Cross-Cloud)

The **Bedrock Action Group Lambda** at [`lambda/bedrock_agent_actions/index.py:79-94`](../lambda/bedrock_agent_actions/index.py) POSTs to the same broken URL — its `SENTRA_API_ENDPOINT` env var is set to `https://iw3limi4k7.execute-api.us-east-1.amazonaws.com/prod/v1/validate`. **Every Bedrock tool call has been silently failing**, falling back to fail-secure DENY responses. The demo orchestrator didn't strictly check those validation decisions, so the failure went unnoticed.

So this fix has two beneficiaries:

1. **Immediate**: Bedrock Lambda → controller calls start working (closes a silent failure that has been present since deploy).
2. **Workstream-15-unblocking**: Azure Function (M3 Phase 3b) can target the same API Gateway URL the Bedrock Lambda already uses.

### 1.5 Why We Cannot Bypass the Public ALB's Cognito

A tempting shortcut: add a `/v1/*` listener rule on the Public ALB that bypasses Cognito and forwards directly to the security-controller target group. **Rejected** because:

- The Public ALB has Cognito SSO as the default action. Adding a path that bypasses it would expose a publicly-routable endpoint with weaker auth than the dashboard pages it shares an ALB with.
- This is a SOC2 finding for an AI security product, and exactly the kind of thing a sharp investor or security review would flag.
- The Public ALB stays human-only. API traffic goes through the entry point designed for it: API Gateway.

### 1.6 Why This Is Its Own LLD

- Independently shippable and benefits multiple callers (Bedrock Lambda today, Azure Function next, any future programmatic caller), so it doesn't belong inside LLD 15.
- Cross-cloud demo depends on it but doesn't own it.

### 1.7 Intended Outcome

These are the post-deploy outcomes this LLD is written to produce. They are **not** current-state assertions — until [Workstream 16 Task 16.6](../tasks/workstream-16-apigw-vpc-link-networking.md) (the api_stack.py call-site wiring) lands and Task 16.11 deploys, every item below is aspirational.

- API Gateway URL is functional for all `/v1/*` paths.
- Bedrock Lambda calls succeed end-to-end (visible in CloudWatch + audit log).
- Workstream 15 M3 starts with a working downstream.
- Two-entry-point architecture is documented for future maintainers.

---

## 2. Two-Entry-Point Architecture

Two distinct traffic patterns into the AWS controller, each with the auth model that fits its consumers. Both converge at the Private ALB. Cognito on Public ALB stays untouched.

### 2.1 Dashboard Flow (HUMAN traffic — working today, untouched)

```
   ┌──────────┐
   │ Browser  │
   └────┬─────┘
        │ HTTPS  (https://sentra-public-alb-…/)
        ▼
   ┌────────────────────────────────────────────────────────┐
   │  Public ALB :443                                        │
   │  • ACM cert                                             │
   │  • Default action: authenticate-cognito → Cognito IdP   │
   │  • Default forward: dashboard_tg                        │
   └────────────────┬───────────────────────────────────────┘
                    ▼
            ┌───────────────────┐
            │ Dashboard ECS     │   Streamlit
            └────────┬──────────┘
                     │ internal calls (in-VPC)
                     ▼
   ┌────────────────────────────────────────────────────────┐
   │  Private ALB :80   (internal-only)                      │
   │  • Path rules → security_controller_tg                  │
   └────────────────┬───────────────────────────────────────┘
                    ▼
            ┌───────────────────┐
            │ Security          │
            │ Controller ECS    │
            └───────────────────┘

   Auth model: Cognito JWT (human SSO).
   Status: working today. Untouched by this LLD.
```

### 2.2 API Flow (PROGRAMMATIC traffic — what this LLD fixes)

```
   ┌────────────────────┐   ┌─────────────────────┐   ┌────────────────────┐
   │ Bedrock Lambda     │   │ Azure Function      │   │ Future: Cloud Run  │
   │ (AWS VPC)          │   │ (Azure eastus2)     │   │ (GCP, Phase 2)     │
   └─────────┬──────────┘   └──────────┬──────────┘   └─────────┬──────────┘
             └───────────┬─────────────┴────────────────────────┘
                         │ HTTPS POST + x-api-key
                         ▼
   ┌─────────────────────────────────────────────────────────────────────┐
   │  API Gateway (REST)                                                  │
   │  https://iw3limi4k7.execute-api.us-east-1.amazonaws.com/prod/v1/...  │
   │  • Usage Plan: API key validation + rate limiting                    │
   └────────────────────────┬─────────────────────────────────────────────┘
                            │ VPC Link  ◄── NEW (this LLD)
                            ▼
   ┌─────────────────────────────────────────────────────────────────────┐
   │  NLB :80                                                  ◄── NEW    │
   │  • Target type = ALB                                                 │
   │  • Target = Private ALB                                              │
   └────────────────────────┬─────────────────────────────────────────────┘
                            ▼
   ┌─────────────────────────────────────────────────────────────────────┐
   │  Private ALB :80   (same one as Dashboard flow)                      │
   │  • Path rules → security_controller_tg                               │
   └────────────────────────┬─────────────────────────────────────────────┘
                            ▼
                  ┌────────────────────┐
                  │ Security           │
                  │ Controller ECS     │
                  └────────────────────┘

   Auth model: API key + Usage Plan at API Gateway.
   The fix = adding the NLB + VPC Link layer the integration was always supposed to have.
```

### 2.3 Why This Architecture Is Right

- **Two entry points, two auth models, both correct.** Public ALB has Cognito for SSO; API Gateway has API keys for programmatic access. Each path uses the auth model that fits its consumers.
- **No security boundaries weakened.** Cognito stays. The Private ALB stays internal. API Gateway gains a proper VPC tunnel instead of trying to route over the internet to an internal hostname.
- **Single shared downstream.** Both flows converge at the Private ALB. The Security Controller ECS doesn't need to know which entry point a request came from.
- **No app-code changes required.** The controller doesn't need new middleware. API key validation happens at API Gateway. The controller trusts traffic that reached it through the gateway.
- **The Bedrock Lambda silent-failure is fixed for free.** Once the integration works, Lambda calls succeed without any Lambda-side change.

---

## 3. CDK Compatibility Verification

Verified 2026-05-22 against `aws-cdk-lib==2.114.1` (pinned in [`cdk/requirements.txt`](../cdk/requirements.txt)).

| Component | CDK construct | Available? | Evidence |
|---|---|---|---|
| REST API Gateway | `apigateway.RestApi` | ✅ Already in use | [`api_stack.py:120`](../cdk/stacks/api_stack.py#L120) |
| VPC Link for REST API | `apigateway.VpcLink` | ✅ | Already in use — [api_stack.py:203](../cdk/stacks/api_stack.py#L203) (`SentraApiVpcLink`); `cdk synth` resolves it without warnings |
| VPC Link connection type | `apigateway.ConnectionType.VPC_LINK` | ✅ | Required by the updated helper — [api_gateway_helpers.py:82](../cdk/utils/api_gateway_helpers.py#L82) |
| Network Load Balancer | `elbv2.NetworkLoadBalancer` | ✅ | Standard construct |
| NLB target type = ALB | `elbv2_targets.AlbTarget` | ✅ | Available since `aws-cdk-lib >= 2.30`; we're on 2.114.1 |
| AWS service compatibility | REST API + VPC Link + NLB target type = ALB | ✅ | AWS released NLB→ALB target type in 2021. REST API VPC Links target NLBs (exactly our pattern). |

**Confirmed**: every construct is available; the pattern is the canonical AWS-documented way to expose a private ALB through API Gateway.

---

## 4. Stack Ownership Matrix

Existing dependency direction: **Network → Compute → API** (Cognito feeds Compute; Monitoring sits downstream of Compute + API). No cycles today. The new resources follow the same direction.

| New Resource | Stack | Why this stack |
|---|---|---|
| **`nlb_sg`** Security Group | **Network Stack** | All SGs live in Network Stack (`public_alb_sg`, `private_alb_sg`, `security_controller_sg` per [`network_stack.py:172-182`](../cdk/stacks/network_stack.py#L172)) |
| **`api_nlb`** NLB | **Compute Stack** | Both ALBs live here (`public_alb` :501, `private_alb` :517) — NLB joins them |
| **NLB Target Group** (target = `private_alb`) | **Compute Stack** | NLB-internal, same stack as NLB |
| **`api_vpc_link`** VPC Link | **API Stack** | VPC Link is API-Gateway-side, references the API Gateway it serves |
| **`create_http_integration` helper update** | `cdk/utils/api_gateway_helpers.py` | Centralized helper; one edit cascades to all routes |
| **API Gateway route integration updates** | **API Stack** (existing routes) | Already there; switch helper invocations |

### Anti-pattern to avoid

Putting the NLB in the API Stack would force `Compute → API` for the NLB target (= Private ALB) reference, creating a cycle. **Don't.** NLB belongs with the other load balancers in Compute Stack.

---

## 5. Cross-Stack Reference List

Additions only — same direction as existing edges.

| From | To | What | Mechanism |
|---|---|---|---|
| Network Stack | Compute Stack | `nlb_sg` reference | Constructor arg (same pattern as existing `public_alb_sg`, `private_alb_sg`) |
| Compute Stack | API Stack | `api_nlb` reference | Constructor arg (same pattern as existing `private_alb` passed via `compute_stack.private_alb`) |

---

## 6. Cyclic-Dependency Analysis

- **Network Stack**: 0 upstream deps. Adds `nlb_sg`. No new edges.
- **Compute Stack**: depends on Network (existing). Adds `api_nlb`. Still only depends on Network.
- **API Stack**: depends on Compute (existing). Adds VPC Link referencing `api_nlb`. Still only depends on Compute.
- No reverse edges anywhere. Graph remains acyclic. ✅

---

## 7. Resource Specifications

### 7.1 `nlb_sg` (Network Stack)

```python
self.nlb_sg = ec2.SecurityGroup(
    self, "ApiNlbSG",
    vpc=vpc,
    allow_all_outbound=False,
    # IMPORTANT: descriptions must be ASCII-only and avoid > < (see "Deploy-time finding 2" below).
    description="Security group for API Gateway VPC Link to NLB (Workstream 16)",
)
# Inbound: TCP/80 from any IPv4 (see "Deploy-time finding 1" below).
self.nlb_sg.add_ingress_rule(
    peer=ec2.Peer.any_ipv4(),
    connection=ec2.Port.tcp(80),
    description="API Gateway VPC Link to NLB :80 (Workstream 16 - internal NLB, any-IPv4 safe)",
)
# Egress: NLB to Private ALB on TCP/80
self.nlb_sg.add_egress_rule(
    peer=self.private_alb_sg,
    connection=ec2.Port.tcp(80),
    description="NLB to Private ALB :80 (Workstream 16)",
)
```

#### Deploy-time finding 1 (2026-05-22): SG ingress source

The original spec called for `ec2.Peer.ipv4(vpc.vpc_cidr_block)` (10.0.0.0/16). **This produces silent traffic drops** with API Gateway returning "Invalid endpoint address" / 500. Diagnostic results:
- NLB reachable from inside the VPC (ECS exec curl: HTTP 200 in 4.4s).
- API Gateway logs show traffic sent to NLB DNS but no response (10s timeout).
- NLB CloudWatch `ProcessedBytes` = 0 — traffic never reached the NLB.
- After opening SG to `0.0.0.0/0`: instant HTTP 200 end-to-end.

**Root cause — AWS Hyperplane / PrivateLink mechanics:** REST API Gateway VPC Links are built on **AWS Hyperplane**, the same network-virtualization platform that backs PrivateLink. API Gateway itself lives in an AWS-managed account; traffic to the customer NLB does not traverse the customer VPC's data plane in a way that exposes a customer-routable source IP. Specifically:

- API Gateway (AWS-managed) connects via Hyperplane to the target NLB in the customer account.
- For NLB target groups with `Preserve client IP addresses` **disabled** (the default for NLB→ALB target type, which is our setup), the NLB terminates the inbound connection and originates a fresh one to its target — the Private ALB sees only the NLB's internal node IPs.
- The customer VPC Flow Logs therefore capture only the NLB→ALB hop (NLB internal IP → ALB IP), not the API Gateway→NLB hop.
- AWS does not publish a managed prefix list for the Hyperplane source IPs, so there is no narrower-than-`0.0.0.0/0` value that will reliably pass through the NLB SG.

**Resolution:** Use `ec2.Peer.any_ipv4()` for the NLB SG ingress. This is safe because the real access-control boundaries sit on either side of the NLB, not on the NLB itself:
1. The NLB is `internet_facing=False` — Hyperplane is the only path that can reach it; externally-routed IPs cannot.
2. API key + Usage Plan auth at API Gateway is the actual access-control boundary at the public edge.
3. Private ALB SG ingress is restricted to `nlb_sg` (i.e., only this specific NLB can reach the controller ECS).

NLB SGs are also optional in AWS — a missing SG behaves functionally identically to `0.0.0.0/0`. The SG is retained here primarily to give Private ALB's ingress rule a concrete sg-id to reference.

#### Future hardening: API Gateway Resource Policy

If we later need to restrict **which accounts, VPCs, or VPC endpoints** can invoke the API Gateway (beyond the current API-key + Usage Plan layer), the right control is an **API Gateway Resource Policy**, not a tighter NLB SG. Resource policies act at the API Gateway edge — before the Hyperplane hop — and can allow-list:

- specific AWS account IDs (`aws:SourceAccount`),
- specific source VPCs (`aws:SourceVpc`),
- specific VPC Endpoints (`aws:SourceVpce`) if we later add a private API Gateway endpoint.

This is the documented way to control "who can reach the API Gateway at all" and complements the API-key auth that controls "what the caller can do once they're in." Not needed for the current single-account, single-VPC dev setup; add it when we open the API to additional accounts or harden for production.

#### Deploy-time finding 2 (2026-05-22): SG description character set

EC2 rejects SG descriptions containing characters outside `a-zA-Z0-9. _-:/()#,@[]+=&;{}!$*`. The original LLD used Unicode arrows (`→`) and em-dashes (`—`); CloudFormation initially failed with `Character sets beyond ASCII are not supported`, and even after substituting `->` the deploy failed again because `>` is **not** in the allowed set.

**Resolution:** Use plain words ("to", "from") in SG and SG-rule descriptions. Avoid ASCII `>`, `<`, `*` (which is allowed but a special char in some shells/filters), and any Unicode.

### 7.2 `api_nlb` (Compute Stack)

```python
self.api_nlb = elbv2.NetworkLoadBalancer(
    self, "ApiNetworkLoadBalancer",
    vpc=network_stack.vpc,
    internet_facing=False,
    cross_zone_enabled=True,
    vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
    security_groups=[network_stack.nlb_sg],     # NLB SG support added in aws-cdk-lib >= 2.66; we're on 2.114.1
)
```

### 7.3 NLB Target Group + Listener (Compute Stack)

```python
self.api_nlb_target_group = elbv2.NetworkTargetGroup(
    self, "ApiNlbTargetGroup",
    vpc=network_stack.vpc,
    port=80,
    protocol=elbv2.Protocol.TCP,
    target_type=elbv2.TargetType.ALB,
    targets=[targets.AlbTarget(self.private_alb, 80)],
    # AWS limitation (verified 2026-05-23 via failed deploy): `deregistration_delay` cannot
    # be set on NLB target groups with `target_type=alb`. AWS API rejects modification with
    # `InvalidRequest: The value of 'deregistration_delay.timeout_seconds' cannot be modified
    # for target groups with target type 'alb'`. The 300s default applies but only matters
    # when individual targets are deregistered from a live TG, not when `cdk destroy`
    # removes the whole stack. WS15 M6 teardown is therefore unaffected.
    health_check=elbv2.HealthCheck(
        path="/v1/health",
        protocol=elbv2.Protocol.HTTP,
        # 'traffic-port' auto-tracks the target group's listener port (80) — preferred over
        # hardcoded "80" so a future port change in one spot does not silently desync.
        port="traffic-port",
        healthy_threshold_count=2,
        unhealthy_threshold_count=2,
        interval=Duration.seconds(30),
    ),
)
self.api_nlb_listener = self.api_nlb.add_listener(
    "ApiNlbListener",
    port=80,
    protocol=elbv2.Protocol.TCP,
    default_action=elbv2.NetworkListenerAction.forward(target_groups=[self.api_nlb_target_group]),
)
# CfnOutput so the API Stack and ops tooling can resolve the NLB DNS
CfnOutput(self, "ApiNlbDnsName", value=self.api_nlb.load_balancer_dns_name)
CfnOutput(self, "ApiNlbArn", value=self.api_nlb.load_balancer_arn)
```

### 7.4 `api_vpc_link` (API Stack)

```python
self.api_vpc_link = apigateway.VpcLink(
    self, "SentraApiVpcLink",
    description="API Gateway → Sentra Private ALB (via NLB) — Workstream 16",
    targets=[compute_stack.api_nlb],
)
```

### 7.5 `create_http_integration` Helper Update

```python
def create_http_integration(
    nlb_base_url: str,
    path: str,
    http_method: str = "POST",
    vpc_link: apigateway.IVpcLink = None,
    pass_query_params: Optional[Dict[str, str]] = None,
    include_api_key_header: bool = True,
) -> apigateway.HttpIntegration:
    """Create HTTP_PROXY integration via VPC Link to the NLB (which targets the Private ALB).

    Workstream 16: ConnectionType is now VPC_LINK (previously INTERNET, which never worked
    because the integration URI was the Private ALB's internal-* DNS).
    """
    request_params = {
        "integration.request.header.X-Correlation-ID": "context.requestId",
    }
    if include_api_key_header:
        request_params["integration.request.header.X-API-Key-ID"] = "context.identity.apiKeyId"
    if pass_query_params:
        for param_name, mapping in pass_query_params.items():
            request_params[f"integration.request.querystring.{param_name}"] = mapping

    return apigateway.HttpIntegration(
        f"{nlb_base_url}{path}",
        http_method=http_method,
        options=apigateway.IntegrationOptions(
            connection_type=apigateway.ConnectionType.VPC_LINK,
            vpc_link=vpc_link,
            request_parameters=request_params,
        ),
    )
```

### 7.6 API Stack Wiring

```python
# Replace the broken:  self.alb_base_url = f"http://{compute_stack.private_alb.load_balancer_dns_name}"
# With:
self.nlb_base_url = f"http://{compute_stack.api_nlb.load_balancer_dns_name}"

# Then every route integration call gets the vpc_link kwarg, e.g.:
integration=create_http_integration(
    self.nlb_base_url,
    "/v1/validate",
    "POST",
    vpc_link=self.api_vpc_link,
)
```

---

## 8. Auth Model

The Security Controller does **not** validate `x-api-key` at the app layer. Auth is enforced at the entry points:

- **Public ALB** validates Cognito JWT before forwarding any request.
- **API Gateway** validates the `x-api-key` header against its Usage Plan before forwarding any request via the VPC Link.

The controller trusts traffic that reaches it because such traffic has already passed the appropriate entry-point auth. This is the same model the codebase has always operated under — this LLD does not change it.

### Adding new programmatic callers

Any new caller (Azure Function, Cloud Run, CI script) must:

1. Obtain the API key from AWS Secrets Manager `sentra-api-key` (or its cross-cloud equivalent — Azure Key Vault, GCP Secret Manager).
2. POST to `https://iw3limi4k7.execute-api.us-east-1.amazonaws.com/prod/v1/<path>` with header `x-api-key: <40-char-value>`.
3. Receive `200` on ALLOW, `403` on rate-limit/key-failure, or normal application 4xx/5xx from the controller for downstream issues.

---

## 9. Smoke-Test Procedure

After deploying all three stacks and waiting for the VPC Link to reach `AVAILABLE` state:

1. **`/v1/health` returns 200** (was 500):
   ```bash
   KEY=$(aws secretsmanager get-secret-value --secret-id sentra-api-key --query SecretString --output text | jq -r .key)
   curl -i -H "x-api-key: $KEY" https://iw3limi4k7.execute-api.us-east-1.amazonaws.com/prod/v1/health
   ```

2. **`/v1/validate` returns expected payload with cross-cloud fields**:
   ```bash
   curl -i -X POST -H "x-api-key: $KEY" -H "Content-Type: application/json" \
     -d '{"request_id":"smoke-001","session_id":"sess-1","agent_id":"sentra-mvp-customer-service-agent","tool_name":"query_customers","tool_params":{"state":"CA"},"user_input":"Show CA customers","timestamp":"2026-05-22T18:00:00Z","operation_type":"READ"}' \
     https://iw3limi4k7.execute-api.us-east-1.amazonaws.com/prod/v1/validate
   # Expected: 200 with platform=bedrock, cloud_region=us-east-1
   ```

3. **Missing API key returns 403** (Usage Plan rejection):
   ```bash
   curl -i -X POST -d '{...}' https://iw3limi4k7…/prod/v1/validate
   # Expected: 403 with {"message": "Forbidden"}
   ```

4. **Bedrock Lambda end-to-end succeeds**: invoke the Bedrock secured agent via the demo orchestrator. Confirm CloudWatch logs show `validate_with_sentra` returning ALLOW/DENY decisions instead of timing out / failing.

5. **Existing unit tests still pass**: `pytest Sentra/src/security-controller/tests/ -q` returns the same green count as the last pre-fix run (no app code changed; this is a sanity check, not a regression test). Capture exact pass count in the workstream task entry.

6. **Dashboard flow untouched**: open `https://sentra-public-alb-…/` in a browser → expect Cognito SSO challenge → after login, dashboard loads. Confirms Cognito flow is unaffected.

---

## 10. Risks

| Risk | Mitigation |
|---|---|
| NLB → ALB target type construct not available in pinned CDK version | Verified §3: `targets.AlbTarget` exists in `aws-cdk-lib==2.114.1`. |
| VPC Link provisioning is slow (5–10 min on first creation) | Document the wait in Workstream 16 Task 16.11. Poll `aws apigateway get-vpc-link --vpc-link-id <id>` until `status=AVAILABLE`. |
| Compute Stack constructor signature change might break callers | Only caller is `app.py` (CDK app entrypoint); update once. `cdk synth` catches any breakage. |
| API Stack changes accidentally replace the `RestApi` resource (URL would change) | `cdk diff` in Task 16.10 explicitly checks for this. Integration-level changes alone don't replace `RestApi`. |
| Bedrock Lambda 5xx briefly during deploy cutover | Deploy is near-instant once VPC Link is `AVAILABLE`. Accept ≤30s window. |
| Dashboard flow accidentally affected | Public ALB and Cognito integration are not touched at all. Smoke-test step 6 confirms. |
| API Gateway Usage Plan rate-limits existing Bedrock Lambda traffic | Keep current plan limits; bump only if quotas surface as a real problem post-deploy. |
| **Behavior regression**: every Bedrock Lambda call has been silently fail-securing to DENY since deploy ([§1.4](#14-who-else-this-affects-beyond-cross-cloud)). Once the integration starts working, previously-masked legitimate DENY decisions will surface; conversely, flows that depended on the de-facto "all calls fail → caller falls through" behavior may now block. | Watch the demo orchestrator and dashboard for unexpected decision flips in the first hour post-deploy. If a demo scenario was implicitly relying on the broken pipeline, fix the scenario — do not roll back the integration. |

---

## 11. What This LLD Does Not Change

- **Public ALB**. Cognito stays exactly as is. Dashboard flow untouched.
- **Security Controller app code**. No middleware. No new endpoints. Workstream 15 M2 deploy (milestone-31) stands.
- **Private ALB path routing rules**. Reused as-is by the new API-side flow.
- **Bedrock Lambda code or env var**. Same `SENTRA_API_ENDPOINT`, same secret reference. Becomes functional after fix.
- **Cross-cloud demo design (LLD 15)**. Only a one-line cross-ref will be added to LLD 15 §7 pointing here.
- **Phase 2 GCP plan**. Unchanged.

---

## 12. Cross-References

| Document | Purpose |
|---|---|
| [LLD 02: API Gateway Layer](02-api-gateway.md) | Original API Gateway design intent; describes the routes that this LLD makes functional |
| [LLD 15: Cross-Cloud Connectors](15-cross-cloud-connectors.md) | M3 (Azure Function) consumer of the API Gateway URL this LLD fixes |
| [design-hld.md §2.2](../design-hld.md) | Split-ALB + API Gateway architecture |
| [ADR-022](../adr.md#adr-022-fix-rest-api-gateway-via-nlb--vpc-link) | Architectural decision record for the NLB + VPC Link approach |
| [Workstream 16](../tasks/workstream-16-apigw-vpc-link-networking.md) | Execution tracking for this LLD |
| [AWS Docs: REST API Gateway Private Integration via VPC Link](https://docs.aws.amazon.com/apigateway/latest/developerguide/getting-started-with-private-integration.html) | Canonical AWS-documented pattern |

---

## Changelog

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0 | 2026-05-22 | Workstream 16 | Initial LLD authoring. Documents the API Gateway VPC Link fix prerequisite to cross-cloud demo M3. |
