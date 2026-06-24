# LLD 08: Authentication and ALB Architecture

**Version:** 2.1
**Last Updated:** 2026-06-23
**Status:** Implemented (Phase 2 edge auth) — multi-tenant control-plane auth designed in LLD-26, not yet built (§6.5)
**Prerequisites:** [LLD 01: Infrastructure](./01-infrastructure.md), [LLD 04: Dashboard](./04-dashboard-v2.md)
**Related:** [LLD 26: Multi-Tenancy](./26-multi-tenancy.md) — adds app-layer control-plane auth, operator↔tenant binding, RBAC, and `GET /v1/me` (§6.5)

---

## Table of Contents

1. [Overview](#1-overview)
2. [Problem Statement](#2-problem-statement)
3. [Architecture Options](#3-architecture-options)
4. [Phase 2 Architecture (Recommended)](#4-phase-2-architecture-recommended)
5. [Implementation Details](#5-implementation-details)
6. [Security Considerations](#6-security-considerations)
7. [Cost Analysis](#7-cost-analysis)
8. [Migration Plan](#8-migration-plan)
9. [Testing Strategy](#9-testing-strategy)
10. [Rollback Plan](#10-rollback-plan)
11. [Monitoring and Alerts](#11-monitoring-and-alerts)
12. [Troubleshooting](#12-troubleshooting)
13. [Future Enhancements](#13-future-enhancements)
14. [Summary](#14-summary)

---

## 1. Overview

### 1.1 Purpose

This LLD addresses a critical security compliance issue where the Streamlit Dashboard is exposed on a public Application Load Balancer (ALB) without authentication. This configuration violates security best practices and triggers automated security remediation by AppSec monitoring systems.

**Security Issue:**
The DyePack security automation plugin detects Streamlit applications exposed on public ALBs without authentication controls. When detected, the automation automatically removes ALB listeners to mitigate the security risk. This remediation affects all services sharing the ALB, causing a complete service outage.

### 1.2 Goals

1. **Immediate**: Prevent AppSec automation from removing ALB listeners
2. **Security**: Implement authentication for Dashboard access
3. **Architecture**: Separate public-facing and internal services
4. **Compliance**: Meet AWS security best practices
5. **Maintainability**: Create scalable, production-ready architecture

### 1.3 Non-Goals

- API key authentication for programmatic access (future enhancement)
- Multi-region deployment
- Custom identity provider integration (Phase 3)

> **Superseded for the control plane:** app-layer authentication/authorization on the controller (operator OIDC verification, tenant binding, RBAC) was a non-goal of this Phase-2 doc but **is now designed and in-scope** in [LLD-26 §3.4/§5.2/§6.3](./26-multi-tenancy.md) — see §6.5 below. The edge-only model here remains accurate for the dashboard; it is no longer the whole auth story.

---

## 2. Problem Statement

### 2.1 Current Architecture Issues


```
Current State (Single Public ALB):

Internet → Public ALB → Dashboard (8501) - NO AUTH ❌
                     → Security Controller (8080) - Exposed unnecessarily
                     → Customer Query Agent (8080) - Exposed unnecessarily  
                     → Payment Agent (8080) - Exposed unnecessarily
```

**Problems:**
1. ❌ Dashboard exposed without authentication (AppSec violation)
2. ❌ API services unnecessarily exposed to internet
3. ❌ Single point of failure (all services on one ALB)
4. ❌ No isolation between public UI and internal APIs
5. ❌ AppSec automation removes ALB listeners, breaking all services

### 2.2 Security Automation Detection

**Automated Security Monitoring:**
AppSec automation systems continuously scan AWS infrastructure for security violations. The ExposedStreamlit detection identifies Streamlit applications that are publicly accessible without proper authentication controls.

**Detection Criteria:**
- Public ALB (internet-facing) with no authentication
- Target group pointing to Streamlit application (port 8501)
- No authentication action configured in ALB listener rules
- No Web Application Firewall (WAF) or other security controls

**Automated Remediation:**
When a violation is detected, the security automation automatically removes ALB listeners to immediately mitigate the risk. This remediation is aggressive and affects all services sharing the ALB, not just the Dashboard, resulting in a complete service outage until the security issue is resolved.

---

## 3. Architecture Options

### 3.1 Option 1: Add Cognito Auth to Existing ALB (Phase 1)

**Architecture:**
```
Internet → Public ALB (with Cognito) → Dashboard (auth required)
                                     → API Services (no auth)
```

**Pros:**
- ✅ Quick fix (1-2 hours)
- ✅ Minimal infrastructure changes
- ✅ Low cost (+$0.05/user/month)
- ✅ Solves AppSec issue immediately

**Cons:**
- ❌ API services still publicly exposed
- ❌ No API authentication
- ❌ Single point of failure
- ❌ Not production-ready architecture

**Use Case:** Immediate AppSec fix, MVP/demo environments

### 3.2 Option 2: Split ALBs (Phase 2) ⭐ RECOMMENDED

**Architecture:**

```
Internet → Public ALB (with Cognito) → Dashboard only
           
VPC Internal → Private ALB → Security Controller
                           → Customer Query Agent
                           → Payment Agent
```

**Pros:**
- ✅ Dashboard isolated with authentication
- ✅ API services private (not internet-accessible)
- ✅ Better security posture
- ✅ Fault isolation (Dashboard issues don't affect APIs)
- ✅ Production-ready architecture
- ✅ Follows AWS Well-Architected Framework

**Cons:**
- ❌ More infrastructure (2 ALBs)
- ❌ Higher cost (+$16/month)
- ❌ Requires VPN/SSM for direct API testing

**Use Case:** Production environments, long-term solution

### 3.3 Option 3: Private ALB + VPN Only

**Architecture:**
```
VPN/SSM → Private ALB → Dashboard
                      → API Services
```

**Pros:**
- ✅ Most secure (nothing public)
- ✅ No authentication needed (network-level security)

**Cons:**
- ❌ Requires VPN setup
- ❌ Less convenient for demos
- ❌ Not suitable for external users

**Use Case:** Internal-only applications

---

## 4. Phase 2 Architecture (Recommended)

### 4.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         Internet                            │
└────────────────────────┬────────────────────────────────────┘
                         │
                         ▼
              ┌──────────────────────┐
              │   AWS Cognito        │
              │   User Pool          │
              └──────────┬───────────┘
                         │
                         │ OAuth 2.0 / OIDC
                         ▼
              ┌──────────────────────┐
              │   Public ALB         │
              │   (Internet-facing)  │
              │                      │
              │   Listener:          │
              │   - Port 80/443      │
              │   - Cognito Auth     │
              └──────────┬───────────┘
                         │
                         ▼
                    Dashboard
                    (ECS Task)
                         │
                         │ Internal API calls
                         │ (within VPC)
                         ▼
              ┌──────────────────────┐
              │   Private ALB        │
              │   (VPC Internal)     │
              │                      │
              │   Listener:          │
              │   - Port 80          │
              │   - No Auth          │
              └──────────┬───────────┘
                         │
         ┌───────────────┼───────────────┐
         │               │               │
         ▼               ▼               ▼
    Security      Customer      Payment
    Controller    Query Agent    Agent
    (ECS Tasks)   (ECS Task)     (ECS Task)
```

### 4.2 Network Architecture


```
VPC: 10.0.0.0/16

┌─────────────────────────────────────────────────────────────┐
│                    VPC (10.0.0.0/16)                        │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Public Subnets                                       │  │
│  │ - us-east-1a: 10.0.1.0/24                           │  │
│  │ - us-east-1b: 10.0.2.0/24                           │  │
│  │                                                      │  │
│  │  ┌──────────────────┐      ┌──────────────────┐     │  │
│  │  │  Public ALB      │←─────│ Internet Gateway │     │  │
│  │  │  (Dashboard)     │      └──────────────────┘     │  │
│  │  │  Public IPs      │                               │  │
│  │  └────────┬─────────┘                               │  │
│  └───────────┼──────────────────────────────────────────┘  │
│              │                                             │
│              │ Routes to Private Subnets                   │
│              ▼                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Private Subnets (with Egress via NAT)                │  │
│  │ - us-east-1a: 10.0.11.0/24                          │  │
│  │ - us-east-1b: 10.0.12.0/24                          │  │
│  │                                                      │  │
│  │  ┌──────────────────┐                               │  │
│  │  │  Dashboard       │ ← Connected to Public ALB     │  │
│  │  │  (ECS Task)      │                               │  │
│  │  └────────┬─────────┘                               │  │
│  │           │                                          │  │
│  │           │ Internal API calls                       │  │
│  │           ▼                                          │  │
│  │  ┌──────────────────┐                               │  │
│  │  │  Private ALB     │ ← VPC Internal Only           │  │
│  │  │  (API Services)  │                               │  │
│  │  │  Private IPs     │                               │  │
│  │  └────────┬─────────┘                               │  │
│  │           │                                          │  │
│  │     ┌─────┼─────┬─────────┐                         │  │
│  │     ▼     ▼     ▼         ▼                         │  │
│  │  [SC]  [CQA]  [PA]    (All ECS Tasks)               │  │
│  │                                                      │  │
│  │  NAT Gateway → Internet (for AWS API calls)         │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Isolated Subnets (No Internet Access)                │  │
│  │ - us-east-1a: 10.0.21.0/28                          │  │
│  │ - us-east-1b: 10.0.22.0/28                          │  │
│  │                                                      │  │
│  │  [VPC Endpoints: ECR, ECR Docker, CloudWatch Logs]  │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘

Legend:
SC  = Security Controller (ECS)
CQA = Customer Query Agent (ECS)
PA  = Payment Agent (ECS)

Subnet Allocation:
- Public:    10.0.1.0/24, 10.0.2.0/24      (Public ALB + NAT Gateway)
- Private:   10.0.11.0/24, 10.0.12.0/24    (ECS Services + Private ALB)
- Isolated:  10.0.21.0/28, 10.0.22.0/28    (VPC Endpoints)
```

### 4.3 Request Flow Examples

#### Example 1: User Accesses Dashboard

```
1. User Browser
   │ https://sentra-alb-public-123.us-east-1.elb.amazonaws.com/
   ▼
2. Public ALB
   │ No valid session cookie
   ▼
3. Cognito Login Page
   │ User enters credentials
   ▼
4. Cognito validates
   │ Returns auth code
   ▼
5. Public ALB
   │ Exchanges code for tokens
   │ Sets session cookie
   ▼
6. Dashboard Container
   │ Renders UI
   ▼
7. User sees Dashboard
```

#### Example 2: Dashboard Queries Customer Data

```
1. User clicks "Query Customers from CA"
   │
   ▼
2. Dashboard (Streamlit)
   │ POST http://sentra-private-alb-internal.us-east-1.elb.amazonaws.com/v1/agents/customer-query/query
   │ Body: {"message": "Show customers from CA", "session_id": "..."}
   ▼
3. Private ALB
   │ Routes to Customer Query Agent
   ▼
4. Customer Query Agent
   │ Calls Security Controller for validation
   │ POST http://sentra-private-alb-internal.us-east-1.elb.amazonaws.com/v1/validate
   ▼
5. Private ALB → Security Controller
   │ Validates request
   ▼
6. Security Controller returns ALLOW
   │
   ▼
7. Customer Query Agent
   │ Calls Bedrock Claude
   │ Queries DynamoDB
   ▼
8. Response flows back:
   CQA → Private ALB → Dashboard → Public ALB → User Browser
```

#### Example 3: External API Call (Testing)

```
Option A: Via VPN
VPN → Private ALB → API Services ✅

Option B: Via SSM Session Manager
SSM → Bastion Host → Private ALB → API Services ✅

Option C: Via Cloud9
Cloud9 (in VPC) → Private ALB → API Services ✅

Option D: Direct from Internet
Internet → Private ALB ❌ BLOCKED (no route)
```

---

## 5. Implementation Details

### 5.1 AWS Cognito Configuration


#### 5.1.1 User Pool

```python
user_pool = cognito.UserPool(
    self, "DashboardUserPool",
    user_pool_name="sentra-dashboard-users",
    
    # Sign-in configuration
    self_sign_up_enabled=False,  # Admin creates users
    sign_in_aliases=cognito.SignInAliases(
        email=True,
        username=False
    ),
    
    # Password policy
    password_policy=cognito.PasswordPolicy(
        min_length=12,
        require_uppercase=True,
        require_lowercase=True,
        require_digits=True,
        require_symbols=True,
        temp_password_validity=Duration.days(7)
    ),
    
    # Account recovery
    account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
    
    # MFA (optional, can enable later)
    mfa=cognito.Mfa.OPTIONAL,
    mfa_second_factor=cognito.MfaSecondFactor(
        sms=False,
        otp=True  # TOTP (Google Authenticator, etc.)
    ),
    
    # Email configuration
    email=cognito.UserPoolEmail.with_cognito(),  # Use Cognito's email service
    
    # User attributes
    standard_attributes=cognito.StandardAttributes(
        email=cognito.StandardAttribute(
            required=True,
            mutable=True
        ),
        given_name=cognito.StandardAttribute(
            required=False,
            mutable=True
        ),
        family_name=cognito.StandardAttribute(
            required=False,
            mutable=True
        )
    ),
    
    # Cleanup
    removal_policy=RemovalPolicy.DESTROY  # For dev/demo
)
```

#### 5.1.2 User Pool Client

```python
user_pool_client = cognito.UserPoolClient(
    self, "DashboardUserPoolClient",
    user_pool=user_pool,
    user_pool_client_name="sentra-dashboard-alb-client",
    
    # OAuth configuration (required for ALB)
    generate_secret=True,  # ALB requires client secret
    
    # Auth flows
    auth_flows=cognito.AuthFlow(
        user_password=True,
        user_srp=True,
        admin_user_password=True
    ),
    
    # OAuth settings
    o_auth=cognito.OAuthSettings(
        flows=cognito.OAuthFlows(
            authorization_code_grant=True  # Standard OAuth 2.0 flow
        ),
        scopes=[
            cognito.OAuthScope.OPENID,
            cognito.OAuthScope.EMAIL,
            cognito.OAuthScope.PROFILE
        ],
        callback_urls=[
            f"https://{public_alb.load_balancer_dns_name}/oauth2/idpresponse",
            f"http://{public_alb.load_balancer_dns_name}/oauth2/idpresponse"
        ],
        logout_urls=[
            f"https://{public_alb.load_balancer_dns_name}/",
            f"http://{public_alb.load_balancer_dns_name}/"
        ]
    ),
    
    # Token validity
    id_token_validity=Duration.hours(1),
    access_token_validity=Duration.hours(1),
    refresh_token_validity=Duration.days(30),
    
    # Security
    prevent_user_existence_errors=True
)
```

#### 5.1.3 Cognito Domain

```python
user_pool_domain = cognito.UserPoolDomain(
    self, "DashboardUserPoolDomain",
    user_pool=user_pool,
    cognito_domain=cognito.CognitoDomainOptions(
        domain_prefix="sentra-dashboard-mvp"  # Must be globally unique
    )
)

# Login URL: https://sentra-dashboard-mvp.auth.us-east-1.amazoncognito.com/login
```

#### 5.1.4 Handling Callback URL Circular Dependency

**Problem:**
The Cognito User Pool Client requires callback URLs that include the ALB DNS name. However, the ALB is created in the Compute Stack, while Cognito is in the Cognito Stack. This creates a circular dependency:
- Cognito Stack needs ALB DNS → depends on Compute Stack
- Compute Stack needs Cognito User Pool Client → depends on Cognito Stack

**Solution: Custom Resource Pattern**

Instead of creating the dependency at stack level, we use a **Custom Resource Lambda** in the Compute Stack to update callback URLs after the ALB is created.

**Implementation:**

1. **Initial Cognito Deployment (with placeholder URLs):**
```python
# In Cognito Stack
user_pool_client = cognito.UserPoolClient(
    self, "DashboardUserPoolClient",
    user_pool=user_pool,
    # ... other config ...
    o_auth=cognito.OAuthSettings(
        flows=cognito.OAuthFlows(
            authorization_code_grant=True
        ),
        scopes=[
            cognito.OAuthScope.OPENID,
            cognito.OAuthScope.EMAIL,
            cognito.OAuthScope.PROFILE
        ],
        # Use placeholder URLs initially
        callback_urls=["https://localhost/oauth2/idpresponse"],
        logout_urls=["https://localhost/"]
    )
)
```

2. **Custom Resource Lambda in Compute Stack:**
```python
# In Compute Stack (after ALB is created)

# Lambda function to update Cognito callback URLs
update_callback_lambda = lambda_.Function(
    self,
    "UpdateCallbackUrlsFunction",
    runtime=lambda_.Runtime.PYTHON_3_11,
    handler="index.handler",
    code=lambda_.Code.from_inline("""
import json
import boto3
import cfnresponse

cognito = boto3.client('cognito-idp')

def handler(event, context):
    print(f"Event: {json.dumps(event)}")

    try:
        request_type = event['RequestType']

        if request_type in ['Create', 'Update']:
            user_pool_id = event['ResourceProperties']['UserPoolId']
            client_id = event['ResourceProperties']['ClientId']
            alb_dns_name = event['ResourceProperties']['AlbDnsName']

            callback_urls = [f"https://{alb_dns_name}/oauth2/idpresponse"]
            logout_urls = [f"https://{alb_dns_name}/"]

            print(f"Updating User Pool Client {client_id}")
            print(f"Callback URLs: {callback_urls}")
            print(f"Logout URLs: {logout_urls}")

            # Get current client configuration
            response = cognito.describe_user_pool_client(
                UserPoolId=user_pool_id,
                ClientId=client_id
            )

            client_config = response['UserPoolClient']

            # Update callback URLs
            cognito.update_user_pool_client(
                UserPoolId=user_pool_id,
                ClientId=client_id,
                ClientName=client_config['ClientName'],
                CallbackURLs=callback_urls,
                LogoutURLs=logout_urls,
                AllowedOAuthFlows=client_config.get('AllowedOAuthFlows', ['code']),
                AllowedOAuthScopes=client_config.get('AllowedOAuthScopes', ['openid', 'email', 'profile']),
                AllowedOAuthFlowsUserPoolClient=client_config.get('AllowedOAuthFlowsUserPoolClient', True),
                SupportedIdentityProviders=client_config.get('SupportedIdentityProviders', ['COGNITO'])
            )

            print("Callback URLs updated successfully")
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {
                'CallbackURLs': ','.join(callback_urls),
                'LogoutURLs': ','.join(logout_urls)
            })

        elif request_type == 'Delete':
            # No cleanup needed
            print("Delete request - no action needed")
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {})

        else:
            print(f"Unknown request type: {request_type}")
            cfnresponse.send(event, context, cfnresponse.SUCCESS, {})

    except Exception as e:
        print(f"Error: {str(e)}")
        cfnresponse.send(event, context, cfnresponse.FAILED, {
            'Error': str(e)
        })
"""),
    timeout=Duration.seconds(30),
    description="Updates Cognito User Pool Client callback URLs after ALB creation",
)

# Grant Lambda permission to update Cognito
update_callback_lambda.add_to_role_policy(
    iam.PolicyStatement(
        actions=[
            "cognito-idp:DescribeUserPoolClient",
            "cognito-idp:UpdateUserPoolClient",
        ],
        resources=[cognito_stack.user_pool.user_pool_arn],
    )
)

# Create Custom Resource to trigger the update
CustomResource(
    self,
    "UpdateCallbackUrlsCustomResource",
    service_token=update_callback_lambda.function_arn,
    properties={
        "UserPoolId": cognito_stack.user_pool.user_pool_id,
        "ClientId": cognito_stack.user_pool_client.user_pool_client_id,
        "AlbDnsName": self.public_alb.load_balancer_dns_name,
    },
)
```

**Flow:**
```
1. Cognito Stack deploys
   └─> User Pool Client with localhost placeholders

2. Compute Stack deploys
   ├─> Public ALB created (gets DNS name)
   ├─> Custom Resource Lambda created
   └─> Lambda executes automatically
       └─> Updates Cognito callback URLs with actual ALB DNS

3. OAuth flow works
   └─> Cognito redirects to https://{ALB_DNS}/oauth2/idpresponse
```

**Benefits:**
- ✅ No circular dependency between stacks
- ✅ Automatic callback URL updates on ALB changes
- ✅ CloudFormation-managed lifecycle
- ✅ Idempotent and safe for stack updates

**Alternative Approaches (Not Used):**

| Approach | Why Not Used |
|----------|-------------|
| Hard-code ALB DNS in Cognito | DNS not known until ALB is created |
| Single stack with both | Loss of modularity, harder to maintain |
| Manual update script | Not CloudFormation-managed, error-prone |
| Cognito Custom Resource | Creates circular dependency |

### 5.2 Public ALB Configuration


```python
# Create Public ALB (Dashboard only)
public_alb = elbv2.ApplicationLoadBalancer(
    self,
    "PublicApplicationLoadBalancer",
    load_balancer_name="sentra-public-alb",
    vpc=network_stack.vpc,
    internet_facing=True,  # Public ALB
    vpc_subnets=ec2.SubnetSelection(
        subnet_type=ec2.SubnetType.PUBLIC
    ),
    security_group=network_stack.public_alb_sg,
    deletion_protection=False,  # Set to True for production
    idle_timeout=Duration.seconds(60)
)

# Target Group for Dashboard
dashboard_tg = elbv2.ApplicationTargetGroup(
    self,
    "DashboardTargetGroup",
    target_group_name="sentra-dashboard-tg",
    vpc=network_stack.vpc,
    port=8501,  # Streamlit port
    protocol=elbv2.ApplicationProtocol.HTTP,
    target_type=elbv2.TargetType.IP,
    health_check=elbv2.HealthCheck(
        path="/_stcore/health",
        interval=Duration.seconds(60),
        timeout=Duration.seconds(10),
        healthy_threshold_count=2,
        unhealthy_threshold_count=3
    ),
    deregistration_delay=Duration.seconds(30)
)

# HTTP Listener with Cognito Authentication
http_listener = public_alb.add_listener(
    "HttpListener",
    port=80,
    protocol=elbv2.ApplicationProtocol.HTTP,
    default_action=elbv2.ListenerAction.authenticate_cognito(
        user_pool=user_pool,
        user_pool_client=user_pool_client,
        user_pool_domain=user_pool_domain,
        next=elbv2.ListenerAction.forward(
            target_groups=[dashboard_tg]
        )
    )
)

# Optional: HTTPS Listener (requires ACM certificate)
# https_listener = public_alb.add_listener(
#     "HttpsListener",
#     port=443,
#     protocol=elbv2.ApplicationProtocol.HTTPS,
#     certificates=[certificate],
#     default_action=elbv2.ListenerAction.authenticate_cognito(...)
# )
```

### 5.3 Private ALB Configuration

```python
# Create Private ALB (API Services)
private_alb = elbv2.ApplicationLoadBalancer(
    self,
    "PrivateApplicationLoadBalancer",
    load_balancer_name="sentra-private-alb",
    vpc=network_stack.vpc,
    internet_facing=False,  # Private ALB (KEY!)
    vpc_subnets=ec2.SubnetSelection(
        subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
    ),
    security_group=network_stack.private_alb_sg,
    deletion_protection=False,
    idle_timeout=Duration.seconds(60)
)

# Target Groups for API Services
security_controller_tg = elbv2.ApplicationTargetGroup(
    self,
    "SecurityControllerTargetGroup",
    target_group_name="sentra-sc-tg",
    vpc=network_stack.vpc,
    port=8080,
    protocol=elbv2.ApplicationProtocol.HTTP,
    target_type=elbv2.TargetType.IP,
    health_check=elbv2.HealthCheck(
        path="/v1/health",
        interval=Duration.seconds(60),
        timeout=Duration.seconds(10),
        healthy_threshold_count=2,
        unhealthy_threshold_count=3
    )
)

customer_query_agent_tg = elbv2.ApplicationTargetGroup(
    self,
    "CustomerQueryAgentTargetGroup",
    target_group_name="sentra-cqa-tg",
    vpc=network_stack.vpc,
    port=8080,
    protocol=elbv2.ApplicationProtocol.HTTP,
    target_type=elbv2.TargetType.IP,
    health_check=elbv2.HealthCheck(
        path="/v1/health",
        interval=Duration.seconds(60),
        timeout=Duration.seconds(10),
        healthy_threshold_count=2,
        unhealthy_threshold_count=3
    )
)

payment_agent_tg = elbv2.ApplicationTargetGroup(
    self,
    "PaymentAgentTargetGroup",
    target_group_name="sentra-pa-tg",
    vpc=network_stack.vpc,
    port=8080,
    protocol=elbv2.ApplicationProtocol.HTTP,
    target_type=elbv2.TargetType.IP,
    health_check=elbv2.HealthCheck(
        path="/v1/health",
        interval=Duration.seconds(60),
        timeout=Duration.seconds(10),
        healthy_threshold_count=2,
        unhealthy_threshold_count=3
    )
)

# HTTP Listener with Path-Based Routing (NO AUTH)
private_http_listener = private_alb.add_listener(
    "PrivateHttpListener",
    port=80,
    protocol=elbv2.ApplicationProtocol.HTTP,
    default_action=elbv2.ListenerAction.fixed_response(
        status_code=404,
        content_type="text/plain",
        message_body="Not Found"
    )
)

# Routing rules
private_http_listener.add_action(
    "SecurityControllerRouting",
    priority=1,
    conditions=[
        elbv2.ListenerCondition.path_patterns([
            "/v1/validate*",
            "/v1/health",
            "/v1/logs*",
            "/v1/sessions*",
            "/v1/metrics*",
            "/v1/agents*",
            "/v1/policies*",
            "/v1/sigma-rules*"
        ])
    ],
    action=elbv2.ListenerAction.forward(
        target_groups=[security_controller_tg]
    )
)

private_http_listener.add_action(
    "CustomerQueryAgentRouting",
    priority=2,
    conditions=[
        elbv2.ListenerCondition.path_patterns([
            "/v1/agents/customer-query/*"
        ])
    ],
    action=elbv2.ListenerAction.forward(
        target_groups=[customer_query_agent_tg]
    )
)

private_http_listener.add_action(
    "PaymentAgentRouting",
    priority=3,
    conditions=[
        elbv2.ListenerCondition.path_patterns([
            "/v1/agents/payment/*"
        ])
    ],
    action=elbv2.ListenerAction.forward(
        target_groups=[payment_agent_tg]
    )
)
```

### 5.4 Security Groups


#### 5.4.1 Public ALB Security Group

```python
public_alb_sg = ec2.SecurityGroup(
    self,
    "PublicAlbSecurityGroup",
    vpc=vpc,
    security_group_name="sentra-public-alb-sg",
    description="Security group for public ALB (Dashboard only)",
    allow_all_outbound=False
)

# Ingress: Allow HTTP from internet
public_alb_sg.add_ingress_rule(
    peer=ec2.Peer.any_ipv4(),
    connection=ec2.Port.tcp(80),
    description="Allow HTTP from internet"
)

# Optional: Allow HTTPS
# public_alb_sg.add_ingress_rule(
#     peer=ec2.Peer.any_ipv4(),
#     connection=ec2.Port.tcp(443),
#     description="Allow HTTPS from internet"
# )

# Egress: Allow to Dashboard
public_alb_sg.add_egress_rule(
    peer=dashboard_sg,
    connection=ec2.Port.tcp(8501),
    description="Allow to Dashboard"
)

# CRITICAL: Egress to internet for Cognito authentication
# Required for ALB to exchange OAuth code with Cognito token endpoint
# Without this, ALB returns 500 Internal Server Error during OAuth flow
public_alb_sg.add_egress_rule(
    peer=ec2.Peer.any_ipv4(),
    connection=ec2.Port.tcp(443),
    description="Allow HTTPS to Cognito for OAuth token exchange"
)
```

**Important Security Note:**

The Public ALB **must** have egress HTTPS (port 443) access to the internet to complete the OAuth 2.0 authorization code flow with Cognito. During the OAuth flow:

1. User logs in at Cognito
2. Cognito redirects to ALB with authorization code
3. **ALB must call Cognito's token endpoint** (over HTTPS) to exchange code for tokens
4. If egress HTTPS is blocked, ALB returns `500 Internal Server Error`

This is a common pitfall when implementing ALB + Cognito authentication. The egress rule is safe because:
- ALB only initiates connections to AWS Cognito endpoints
- ALB does not accept inbound connections on port 443 egress
- Security group restricts ingress (inbound) traffic appropriately

#### 5.4.2 Private ALB Security Group

```python
private_alb_sg = ec2.SecurityGroup(
    self,
    "PrivateAlbSecurityGroup",
    vpc=vpc,
    security_group_name="sentra-private-alb-sg",
    description="Security group for private ALB (API services)",
    allow_all_outbound=False
)

# Ingress: Allow from Dashboard
private_alb_sg.add_ingress_rule(
    peer=dashboard_sg,
    connection=ec2.Port.tcp(80),
    description="Allow from Dashboard"
)

# Ingress: Allow from API services (for inter-service communication)
private_alb_sg.add_ingress_rule(
    peer=security_controller_sg,
    connection=ec2.Port.tcp(80),
    description="Allow from Security Controller"
)

private_alb_sg.add_ingress_rule(
    peer=customer_query_agent_sg,
    connection=ec2.Port.tcp(80),
    description="Allow from Customer Query Agent"
)

private_alb_sg.add_ingress_rule(
    peer=payment_agent_sg,
    connection=ec2.Port.tcp(80),
    description="Allow from Payment Agent"
)

# Egress: Allow to all API services
private_alb_sg.add_egress_rule(
    peer=security_controller_sg,
    connection=ec2.Port.tcp(8080),
    description="Allow to Security Controller"
)

private_alb_sg.add_egress_rule(
    peer=customer_query_agent_sg,
    connection=ec2.Port.tcp(8080),
    description="Allow to Customer Query Agent"
)

private_alb_sg.add_egress_rule(
    peer=payment_agent_sg,
    connection=ec2.Port.tcp(8080),
    description="Allow to Payment Agent"
)
```

#### 5.4.3 Dashboard Security Group

```python
dashboard_sg = ec2.SecurityGroup(
    self,
    "DashboardSecurityGroup",
    vpc=vpc,
    security_group_name="sentra-dashboard-sg",
    description="Security group for Dashboard ECS tasks",
    allow_all_outbound=False
)

# Ingress: Allow from Public ALB
dashboard_sg.add_ingress_rule(
    peer=public_alb_sg,
    connection=ec2.Port.tcp(8501),
    description="Allow from Public ALB"
)

# Egress: Allow to Private ALB (for API calls)
dashboard_sg.add_egress_rule(
    peer=private_alb_sg,
    connection=ec2.Port.tcp(80),
    description="Allow to Private ALB"
)

# Egress: Allow to DynamoDB (via VPC endpoint)
dashboard_sg.add_egress_rule(
    peer=ec2.Peer.any_ipv4(),
    connection=ec2.Port.tcp(443),
    description="Allow to AWS services (DynamoDB, CloudWatch)"
)
```

### 5.5 ECS Service Configuration

#### 5.5.1 Dashboard Service (Public ALB)

```python
dashboard_service = ecs.FargateService(
    self,
    "DashboardService",
    service_name="sentra-dashboard",
    cluster=ecs_cluster,
    task_definition=dashboard_task_def,
    desired_count=1,
    vpc_subnets=ec2.SubnetSelection(
        subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
    ),
    security_groups=[dashboard_sg],
    health_check_grace_period=Duration.seconds(120),
    circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
    enable_execute_command=True
)

# Attach to Public ALB
dashboard_service.attach_to_application_target_group(dashboard_tg)

# Environment variables
dashboard_task_def.default_container.add_environment(
    "SECURITY_CONTROLLER_URL",
    f"http://{private_alb.load_balancer_dns_name}"
)
dashboard_task_def.default_container.add_environment(
    "CUSTOMER_QUERY_AGENT_URL",
    f"http://{private_alb.load_balancer_dns_name}"
)
dashboard_task_def.default_container.add_environment(
    "PAYMENT_AGENT_URL",
    f"http://{private_alb.load_balancer_dns_name}"
)
```

#### 5.5.2 API Services (Private ALB)

```python
# Security Controller
security_controller_service = ecs.FargateService(
    self,
    "SecurityControllerService",
    service_name="sentra-security-controller",
    cluster=ecs_cluster,
    task_definition=security_controller_task_def,
    desired_count=1,
    vpc_subnets=ec2.SubnetSelection(
        subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
    ),
    security_groups=[security_controller_sg],
    health_check_grace_period=Duration.seconds(120),
    circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True)
)

security_controller_service.attach_to_application_target_group(
    security_controller_tg
)

# Customer Query Agent
customer_query_agent_service = ecs.FargateService(
    self,
    "CustomerQueryAgentService",
    service_name="sentra-customer-query-agent",
    cluster=ecs_cluster,
    task_definition=customer_query_agent_task_def,
    desired_count=1,
    vpc_subnets=ec2.SubnetSelection(
        subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
    ),
    security_groups=[customer_query_agent_sg],
    health_check_grace_period=Duration.seconds(120),
    circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True)
)

customer_query_agent_service.attach_to_application_target_group(
    customer_query_agent_tg
)

# Payment Agent
payment_agent_service = ecs.FargateService(
    self,
    "PaymentAgentService",
    service_name="sentra-payment-agent",
    cluster=ecs_cluster,
    task_definition=payment_agent_task_def,
    desired_count=1,
    vpc_subnets=ec2.SubnetSelection(
        subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
    ),
    security_groups=[payment_agent_sg],
    health_check_grace_period=Duration.seconds(120),
    circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True)
)

payment_agent_service.attach_to_application_target_group(
    payment_agent_tg
)
```

---

## 6. Security Considerations

### 6.1 Authentication Security

**Cognito Security Features:**
- ✅ Password complexity requirements (12+ chars, mixed case, numbers, symbols)
- ✅ Account lockout after failed login attempts
- ✅ Email verification for new users
- ✅ Optional MFA (TOTP)
- ✅ Session management with refresh tokens
- ✅ Secure token storage (httpOnly cookies)

**Session Security:**
- Session cookies are httpOnly (not accessible via JavaScript)
- Session timeout: 1 hour (configurable)
- Refresh token validity: 30 days
- Automatic session renewal

### 6.2 Network Security

**Network Prerequisites:**

**IMPORTANT**: Public ALB requires public subnets of at least **/27** CIDR size (per AWS documentation).
The original Network Stack used `/28` public subnets (16 IPs) which is too small for ALB deployment.

**Updated Subnet Configuration** (per ADR-019 and network_stack.py):
- **Public Subnets**: 10.0.1.0/24, 10.0.2.0/24 (upgraded from /28 to /24)
  - Used for: Public ALB + NAT Gateway
  - Size: 256 IPs per subnet (sufficient for ALB requirements)
- **Private Subnets**: 10.0.11.0/24, 10.0.12.0/24
  - Used for: ECS services (Dashboard, Security Controller, Agents) + Private ALB
  - Egress via NAT Gateway in public subnets
- **Isolated Subnets**: 10.0.21.0/28, 10.0.22.0/28
  - Used for: VPC Endpoints (ECR, ECR Docker, CloudWatch Logs, S3, DynamoDB)
  - No direct internet access

**Security Groups:**

**Public ALB:**
- Only Dashboard exposed
- Cognito authentication required
- Security group restricts egress to Dashboard only

**Private ALB:**
- No public IP addresses
- Only accessible from within VPC
- Security groups enforce least privilege

**ECS Tasks:**
- Run in private subnets
- No public IPs
- Egress via NAT Gateway for AWS API calls

### 6.3 Data Protection

**In Transit:**
- TLS 1.2+ for all external connections
- Internal VPC traffic (unencrypted but isolated)
- Option to add TLS for internal traffic

**At Rest:**
- DynamoDB encryption at rest (default)
- S3 encryption at rest (default)
- CloudWatch Logs encryption

### 6.4 Compliance

**AppSec Requirements:**
- ✅ Dashboard has authentication (Cognito)
- ✅ API services not publicly exposed
- ✅ Follows AWS security best practices
- ✅ No ExposedStreamlit violation

**AWS Well-Architected:**
- ✅ Security Pillar: Defense in depth
- ✅ Reliability Pillar: Fault isolation
- ✅ Cost Optimization: Right-sized resources
- ✅ Operational Excellence: Monitoring and logging

---

## 6.5 Multi-Tenant Control-Plane Authentication (LLD-26)

> **What changes vs. this doc's baseline:** the architecture above authenticates **at the edge only** — ALB `authenticate-cognito` gates the dashboard, and the controller's management endpoints (`/v1/agents`, `/v1/policies`, `/v1/connections`, …) trust that edge and have **no app-layer authz**. [LLD-26: Multi-Tenancy](./26-multi-tenancy.md) introduces the controller's **first in-app authentication and authorization**, because multi-tenant isolation cannot be enforced at the edge. Full design is canonical in LLD-26; summarized here so this doc is not read as "edge auth is the whole story."

**Control-plane (operator → console/API):**
- **`verify_alb_oidc` — net-new.** Every control-plane request is verified in-app: the ALB injects a signed `x-amzn-oidc-data` JWT of the Cognito claims; the controller fetches the ALB **regional public signing key** (`https://public-keys.auth.elb.{region}.amazonaws.com/{kid}`), **caches it, handles key rotation**, and validates signature + `exp`. Forged/expired → `401`. This is a security milestone, not plumbing (LLD-26 WS-D D3a).
- **Operator↔tenant resolution (`resolve_operator_tenant`).** From the verified `sub`, look up `sentra-tenant-members`, resolve the active tenant, and call `set_current_tenant()`. A multi-tenant operator may pass an `X-Aegion-Tenant` header, validated against their membership set (deny `403` if not a member); default = primary membership (LLD-26 §5.2).
- **RBAC (`require_role`).** A second dependency layered after tenant resolution gates control-plane mutations by role (`owner`/`admin`/`editor`/`viewer`); `_platform` is a reserved cross-tenant support capability, dual-audited (LLD-26 §6.3).
- **`GET /v1/me` — net-new endpoint.** Returns `{tenant_id, role, memberships[]}` so the console renders role-conditional UI and the tenant switcher.

**Data-plane (agent → `/v1/validate`):**
- **Agent-JWT verify (`resolve_tenant_from_jwt`).** Agents present a short-lived ES256 JWT signed by a key whose **public** half is in `sentra-agent-credentials`; the controller verifies it (delimited `tid`-prefix-of-`sub` check), derives `(tenant_id, agent_id)`, and sets the request tenant. This is distinct from the operator OIDC path above (LLD-26 §3.4).

These supersede the "Phase 3: API Authentication" placeholder (§13.1) for the control plane.

---

## 7. Cost Analysis

### 7.1 Infrastructure Costs

| Component | Current | Phase 2 | Delta |
|-----------|---------|---------|-------|
| **ALB** | 1 × $16/month | 2 × $16/month | +$16/month |
| **Cognito** | $0 | $0.05/user/month | +$0.05/user |
| **ECS Tasks** | 4 tasks | 4 tasks | $0 |
| **Data Transfer** | Minimal | Minimal | $0 |
| **Total** | ~$16/month | ~$32/month | +$16/month |

### 7.2 Cost Breakdown

**Public ALB:**
- Fixed: $16.20/month (730 hours)
- LCU: ~$5/month (estimated)
- **Total: ~$21/month**

**Private ALB:**
- Fixed: $16.20/month
- LCU: ~$3/month (internal traffic)
- **Total: ~$19/month**

**Cognito:**
- First 50,000 MAUs: Free
- Additional MAUs: $0.0055/MAU
- **Total: ~$0 for MVP (< 50K users)**

**Total Additional Cost: ~$16-20/month**

### 7.3 Cost Optimization

**Savings Opportunities:**
- Use Savings Plans for ECS Fargate (up to 50% savings)
- Right-size ECS tasks based on actual usage
- Use CloudWatch Logs retention policies (7 days for container logs)

---

## 8. Migration Plan

### 8.1 Pre-Migration Checklist

- [ ] Review and approve LLD
- [ ] Create Cognito User Pool and test login
- [ ] Update CDK code for split ALBs
- [ ] Test in dev environment
- [ ] Create rollback plan
- [ ] Schedule maintenance window
- [ ] Notify stakeholders

### 8.2 Migration Steps

**Step 1: Create Cognito Resources (30 min)**
```bash
# Deploy Cognito stack
cdk deploy SentraCognitoStack --profile sentra

# Create admin user
aws cognito-idp admin-create-user \
  --user-pool-id us-east-1_XXXXXXXXX \
  --username admin@sentra.com \
  --user-attributes Name=email,Value=admin@sentra.com \
  --temporary-password "TempPassword123!" \
  --profile sentra
```

**Step 2: Create Private ALB (30 min)**
```bash
# Deploy updated compute stack (creates Private ALB)
cdk deploy SentraComputeStack --profile sentra

# Verify Private ALB created
aws elbv2 describe-load-balancers \
  --names sentra-private-alb \
  --profile sentra
```

**Step 3: Update ECS Services (30 min)**
```bash
# Update Dashboard environment variables
# (points to Private ALB for API calls)

# Update API services
# (attach to Private ALB target groups)

# Deploy changes
cdk deploy SentraComputeStack --profile sentra
```

**Step 4: Update Public ALB (30 min)**
```bash
# Add Cognito authentication to Public ALB
# Remove API service routing from Public ALB
# Keep only Dashboard routing

cdk deploy SentraComputeStack --profile sentra
```

**Step 5: Verify and Test (30 min)**
```bash
# Test Dashboard login
open http://$(aws elbv2 describe-load-balancers \
  --names sentra-public-alb \
  --query 'LoadBalancers[0].DNSName' \
  --output text \
  --profile sentra)

# Test API services (from Dashboard)
# Verify inter-service communication
# Check CloudWatch Logs
```

**Total Migration Time: ~2.5 hours**

### 8.3 Validation Criteria

- ✅ Dashboard accessible via Public ALB with Cognito login
- ✅ API services accessible from Dashboard (via Private ALB)
- ✅ API services NOT accessible from internet
- ✅ All health checks passing
- ✅ No AppSec violations detected
- ✅ CloudWatch Logs showing successful requests

---

## 9. Testing Strategy

### 9.1 Unit Tests

**Cognito Authentication:**
- [ ] User can login with valid credentials
- [ ] User cannot login with invalid credentials
- [ ] Session expires after timeout
- [ ] Refresh token works correctly
- [ ] Logout clears session

**ALB Routing:**
- [ ] Public ALB routes to Dashboard only
- [ ] Private ALB routes to correct API services
- [ ] Path-based routing works correctly
- [ ] Health checks pass

### 9.2 Integration Tests

**Dashboard to API Services:**
- [ ] Dashboard can call Security Controller
- [ ] Dashboard can call Customer Query Agent
- [ ] Dashboard can call Payment Agent
- [ ] Inter-service communication works (CQA → SC, PA → SC)

**Security:**
- [ ] Unauthenticated users cannot access Dashboard
- [ ] API services not accessible from internet
- [ ] Security groups enforce correct rules

### 9.3 End-to-End Tests

**User Workflow:**
1. User visits Dashboard URL
2. Redirected to Cognito login
3. Enters credentials
4. Redirected back to Dashboard
5. Dashboard loads successfully
6. User queries customers (Dashboard → CQA → SC → DynamoDB)
7. Results displayed correctly

**API Workflow:**
1. Dashboard calls Customer Query Agent
2. CQA calls Security Controller for validation
3. SC validates and returns ALLOW
4. CQA queries DynamoDB
5. Response flows back to Dashboard

### 9.4 Performance Tests

**Load Testing:**
- 10 concurrent users accessing Dashboard
- 100 API requests/minute
- Measure latency (target: < 500ms p95)
- Verify auto-scaling works

**Stress Testing:**
- 50 concurrent users
- 500 API requests/minute
- Monitor ALB metrics
- Check for throttling

---

## 10. Rollback Plan

### 10.1 Rollback Triggers

- AppSec still removing listeners
- Authentication not working
- API services unreachable
- Performance degradation
- Critical bugs

### 10.2 Rollback Steps

**Option 1: Revert to Previous CDK Version**
```bash
# Revert CDK code
git revert <commit-hash>

# Deploy previous version
cdk deploy --all --profile sentra
```

**Option 2: Keep Private ALB, Remove Cognito**
```bash
# Remove Cognito authentication from Public ALB
# Keep split ALB architecture
# Temporarily allow unauthenticated Dashboard access

cdk deploy SentraComputeStack --profile sentra
```

**Option 3: Emergency Rollback**
```bash
# Delete new stacks
cdk destroy SentraCognitoStack --profile sentra

# Restore from CloudFormation snapshot
aws cloudformation update-stack \
  --stack-name SentraComputeStack \
  --use-previous-template \
  --profile sentra
```

### 10.3 Rollback Validation

- [ ] Dashboard accessible without authentication
- [ ] API services accessible (via original ALB)
- [ ] All services healthy
- [ ] No data loss
- [ ] CloudWatch Logs normal

---

## 11. Monitoring and Alerts

### 11.1 CloudWatch Metrics

**Public ALB:**
- `TargetResponseTime` (Dashboard latency)
- `HTTPCode_Target_4XX_Count` (Dashboard errors)
- `HTTPCode_ELB_5XX_Count` (ALB errors)
- `ActiveConnectionCount`
- `RequestCount`

**Private ALB:**
- `TargetResponseTime` (API latency)
- `HTTPCode_Target_4XX_Count` (API errors)
- `HealthyHostCount` (API service health)
- `UnHealthyHostCount`

**Cognito:**
- `SignInSuccesses`
- `SignInThrottles`
- `TokenRefreshSuccesses`
- `UserAuthentication`

### 11.2 CloudWatch Alarms

```python
# Dashboard unavailable
dashboard_alarm = cloudwatch.Alarm(
    self, "DashboardUnhealthyAlarm",
    alarm_name="sentra-dashboard-unhealthy",
    metric=dashboard_tg.metric_unhealthy_host_count(),
    threshold=1,
    evaluation_periods=2,
    datapoints_to_alarm=2
)

# API services unavailable
api_alarm = cloudwatch.Alarm(
    self, "ApiServicesUnhealthyAlarm",
    alarm_name="sentra-api-services-unhealthy",
    metric=security_controller_tg.metric_unhealthy_host_count(),
    threshold=1,
    evaluation_periods=2
)

# High error rate
error_alarm = cloudwatch.Alarm(
    self, "HighErrorRateAlarm",
    alarm_name="sentra-high-error-rate",
    metric=public_alb.metric_http_code_target_5_xx_count(),
    threshold=10,
    evaluation_periods=1,
    period=Duration.minutes(5)
)
```

### 11.3 Logging

**CloudWatch Log Groups:**
- `/ecs/sentra/dashboard` - Dashboard logs
- `/ecs/sentra/security-controller` - Security Controller logs
- `/ecs/sentra/customer-query-agent` - CQA logs
- `/ecs/sentra/payment-agent` - Payment Agent logs
- `/aws/cognito/userpools/sentra-dashboard-users` - Cognito logs

**Log Retention:**
- Container logs: 7 days
- Audit logs: 90 days
- Cognito logs: 30 days

---

## 12. Troubleshooting

### 12.1 Common OAuth Issues

#### Issue 1: 500 Internal Server Error on OAuth Callback

**Symptoms:**
- User successfully logs in at Cognito
- Browser redirects to `/oauth2/idpresponse?code=...`
- ALB returns 500 Internal Server Error

**Root Cause:**
ALB cannot reach Cognito token endpoint to exchange authorization code for tokens.

**Solution:**
Add egress HTTPS (port 443) rule to Public ALB security group:
```python
public_alb_sg.add_egress_rule(
    peer=ec2.Peer.any_ipv4(),
    connection=ec2.Port.tcp(443),
    description="Allow HTTPS to Cognito for OAuth token exchange"
)
```

**Verification:**
```bash
# Check ALB security group egress rules
aws ec2 describe-security-groups \
  --group-ids sg-xxxxxxxx \
  --query 'SecurityGroups[0].IpPermissionsEgress'
```

#### Issue 2: Callback URL Mismatch

**Symptoms:**
- Cognito returns error: "redirect_mismatch"
- User cannot complete login

**Root Cause:**
Callback URLs in Cognito User Pool Client don't match ALB DNS name.

**Solution:**
Verify Custom Resource executed successfully:
```bash
# Check Lambda logs
aws logs tail /aws/lambda/Sentra-DEV-Compute-Stack-UpdateCallbackUrlsFunction* \
  --since 1h \
  --follow

# Verify callback URLs
aws cognito-idp describe-user-pool-client \
  --user-pool-id us-east-1_XXXXXXXXX \
  --client-id xxxxxxxxxxxx \
  --query 'UserPoolClient.{CallbackURLs:CallbackURLs,LogoutURLs:LogoutURLs}'
```

#### Issue 3: Client Secret Error

**Symptoms:**
- CloudFormation error: "The user pool client must have a client secret"

**Root Cause:**
User Pool Client has `generate_secret=False` but ALB requires a client secret.

**Solution:**
Update Cognito User Pool Client:
```python
user_pool_client = cognito.UserPoolClient(
    # ...
    generate_secret=True,  # ALB REQUIRES client secret
    # ...
)
```

**Note:** AWS documentation can be confusing on this. ALB with Cognito **REQUIRES** a client secret.

#### Issue 4: Session Timeout Type Error

**Symptoms:**
- CloudFormation error: "type of argument session_timeout must be one of (str, NoneType); got int instead"

**Root Cause:**
ALB listener `session_timeout` parameter must be a string, not integer.

**Solution:**
```python
# INCORRECT
session_timeout=3600

# CORRECT
session_timeout="3600"
```

### 12.2 Debugging OAuth Flow

**Enable Detailed Logging:**

1. **ALB Access Logs:**
```python
public_alb.log_access_logs(
    bucket=s3.Bucket.from_bucket_name(self, "LogBucket", "my-alb-logs"),
    prefix="alb/public"
)
```

2. **Cognito Advanced Security:**
```bash
# Enable CloudWatch Logs for Cognito
aws cognito-idp set-user-pool-mfa-config \
  --user-pool-id us-east-1_XXXXXXXXX \
  --advanced-security-mode AUDIT
```

3. **CloudWatch Insights Query:**
```sql
fields @timestamp, @message
| filter @message like /oauth2/
| sort @timestamp desc
| limit 100
```

**OAuth Flow Checklist:**

- [ ] User Pool Client has `generate_secret=True`
- [ ] Callback URLs match ALB DNS exactly (including HTTPS)
- [ ] OAuth scopes include `openid`, `email`, `profile`
- [ ] ALB security group allows egress HTTPS (443)
- [ ] ALB listener has `authenticate-cognito` action with correct order
- [ ] User Pool Domain is accessible (e.g., `sentra-dashboard-mvp.auth.us-east-1.amazoncognito.com`)
- [ ] Session timeout is string format (e.g., `"3600"`)

### 12.3 Testing OAuth Locally

**Manual OAuth Flow Test:**

1. **Get Authorization Code:**
```bash
# Open in browser
ALB_DNS="sentra-public-alb-xxxxx.us-east-1.elb.amazonaws.com"
open "https://${ALB_DNS}/"
```

2. **Verify Redirect to Cognito:**
```
Expected URL:
https://sentra-dashboard-mvp.auth.us-east-1.amazoncognito.com/login?
  client_id=xxxxxxxxxxxx&
  response_type=code&
  scope=openid+email+profile&
  redirect_uri=https://${ALB_DNS}/oauth2/idpresponse
```

3. **After Login:**
```
Expected URL:
https://${ALB_DNS}/oauth2/idpresponse?code=xxxxx&state=xxxxx
```

4. **Verify Cookie Set:**
```bash
# Check browser cookies for AWSELBAuthSessionCookie
```

---

## 13. Future Enhancements

### 13.1 Phase 3: API Authentication

> **Update:** app-layer **control-plane** authentication is no longer a future placeholder — it is designed in [LLD-26](./26-multi-tenancy.md) (operator OIDC verify, tenant binding, RBAC; see §6.5). The items below remain relevant only for **programmatic/API-key** access by external automation, which LLD-26 does not cover.

**Add API Key Authentication:**
- API Gateway in front of Private ALB
- API keys for programmatic access
- Rate limiting per API key
- Usage plans and quotas

### 13.2 Phase 4: Custom Domain

**Add Custom Domain:**
- Route 53 hosted zone
- ACM certificate
- HTTPS only
- Custom domain: `dashboard.sentra.example.com`

### 13.3 Phase 5: Advanced Security

**WAF Integration:**
- AWS WAF on Public ALB
- Rate limiting rules
- Geo-blocking
- SQL injection protection

**GuardDuty:**
- Enable GuardDuty for VPC
- Monitor for suspicious activity
- Automated remediation

---

## 14. Summary

### 14.1 Key Decisions

| Decision | Rationale |
|----------|-----------|
| **Split ALBs** | Better security isolation, fault tolerance |
| **Cognito Auth** | AWS-native, low cost, easy integration |
| **Private ALB** | API services not exposed to internet |
| **Phase 2 First** | Production-ready architecture from start |

### 14.2 Success Criteria

- ✅ Dashboard accessible with authentication
- ✅ API services private (not internet-accessible)
- ✅ No AppSec violations
- ✅ All services healthy and operational
- ✅ Performance within SLAs (< 500ms p95)
- ✅ Cost within budget (+$16/month)

### 14.3 Timeline

| Phase | Duration | Status |
|-------|----------|--------|
| **Design** | 1 day | ✅ Complete |
| **Implementation** | 1 day | ✅ Complete |
| **Testing** | 0.5 day | ✅ Complete |
| **Deployment** | 0.5 day | ✅ Complete |
| **Total** | 3 days | ✅ Complete |

**Actual Implementation Notes:**
- Custom Resource pattern for callback URLs avoided circular dependency
- Security group egress HTTPS rule was critical for OAuth token exchange
- Client secret requirement caused initial confusion but was resolved
- All stacks deployed successfully: Network, Storage, Cognito, Compute, API, Monitoring

---

**End of LLD 08: Authentication and ALB Architecture**
