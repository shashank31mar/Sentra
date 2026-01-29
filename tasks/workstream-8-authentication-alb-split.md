# Workstream 8: Authentication and ALB Architecture (Phase 2) ✅ COMPLETE

**Component**: Split ALB Architecture with Cognito Authentication
**Status**: ✅ **IMPLEMENTATION COMPLETE**
**Completion Date**: November 23, 2025
**Actual Duration**: 3 days (2.5 days ahead of 5.5 day estimate)
**Owner**: Infrastructure Team
**Prerequisites**: Workstream 7 (AI Agents), LLD 08 (Authentication and ALB Architecture)

**Implementation Summary:**
- ✅ All 6 stacks deployed successfully
- ✅ OAuth authentication working end-to-end
- ✅ Dashboard protected with Cognito
- ✅ API services private (not internet-accessible)
- ✅ Critical security group issue resolved (HTTPS egress for OAuth)
- ✅ Documentation complete (LLD 08 v2.0)

---

## AWS Configuration

**Critical**: All tasks use:
- **Account ID**: `531109575379`
- **Profile**: `sentra`
- **Region**: `us-east-1`

```bash
# Refresh credentials daily
ada cred update --once

# Verify
export AWS_PROFILE=sentra AWS_REGION=us-east-1
aws sts get-caller-identity
```

---

## ⚠️ IMPORTANT: Clean Slate Approach

**Before implementing Phase 2, we will DELETE the existing stack and redeploy from scratch.**

### Why Clean Slate?

1. **Avoid Complex Migrations**: Splitting an existing ALB is complex and error-prone
2. **Prevent Resource Conflicts**: Security groups, target groups, and listeners can conflict
3. **Faster Implementation**: Clean deployment is faster than in-place migration
4. **Easier Rollback**: If issues occur, we can quickly redeploy the old stack
5. **No Downtime Concerns**: This is a dev/demo environment, not production

### What Gets Deleted?

- ✅ **Monitoring Stack** (monitors Compute/API stacks - will be recreated)
- ✅ **API Stack** (depends on old ALB - will be recreated)
- ✅ **Compute Stack** (ECS services, ALB, target groups)
- ✅ **Network Stack** (subnet CIDR change requires recreation)
- ❌ **Storage Stack** (DynamoDB, S3, ECR) - **PRESERVED**

**Important**: API Stack and Monitoring Stack also need deletion because they depend on Compute Stack resources (ALB) that will be replaced.

### Data Safety

**No data loss** - All data is in Storage Stack which is NOT deleted:
- DynamoDB tables (session-context, policies, demo data)
- S3 buckets (sigma rules, policies, artifacts)
- CloudWatch Logs (audit logs)
- ECR images (Docker containers)

---

## Milestone 0: Pre-Implementation Preparation (Day 0 - 0.5 day)

**Updated Duration**: Reduced from 1 day to 0.5 day (removed unnecessary documentation of resources that will be deleted).

### Task 0: Git Backup and Data Verification

**Why This Task Matters:**
- ✅ **Git Backup**: Only way to rollback if Phase 2 fails
- ✅ **Storage Verification**: Ensure data is safe before deleting stacks
- ❌ **No Old Config Documentation**: We're deleting/recreating everything from CDK code - old configs are irrelevant

---

**Part A: Create Git Rollback Package**

```bash
# Save current CDK code (CRITICAL for rollback)
git branch backup-pre-phase2
git push origin backup-pre-phase2

# Tag current state
git tag -a v1.0-pre-phase2 -m "Backup before Phase 2 implementation"
git push origin v1.0-pre-phase2

# Verify backup created
git branch -a | grep backup-pre-phase2
git tag | grep v1.0-pre-phase2

# Expected output:
# remotes/origin/backup-pre-phase2
# v1.0-pre-phase2
```

---

**Part B: Verify Storage Stack Data Exists**
```bash
# Verify DynamoDB tables exist and have data
aws dynamodb scan --table-name sentra-demo-customers --select COUNT --profile sentra
aws dynamodb scan --table-name sentra-demo-orders --select COUNT --profile sentra
aws dynamodb scan --table-name sentra-session-context --select COUNT --profile sentra

# Verify S3 bucket exists
aws s3 ls s3://sentra-mvp-artifacts-531109575379-us-east-1/ --profile sentra

# Verify ECR images exist
aws ecr describe-images --repository-name sentra/customer-query-agent --profile sentra
aws ecr describe-images --repository-name sentra/payment-agent --profile sentra
aws ecr describe-images --repository-name sentra/security-controller --profile sentra
aws ecr describe-images --repository-name sentra/dashboard --profile sentra
```

**Acceptance Criteria:**
- ✅ Git backup branch created (`backup-pre-phase2`)
- ✅ Git tag created (`v1.0-pre-phase2`)
- ✅ Storage Stack exists and contains data:
  - DynamoDB: sentra-demo-customers (>0 records)
  - DynamoDB: sentra-demo-orders (>0 records)
  - S3: sentra-mvp-artifacts bucket exists
  - ECR: All 4 Docker images exist (security-controller, dashboard, customer-query-agent, payment-agent)
- ✅ Rollback plan ready (can checkout backup-pre-phase2 branch if Phase 2 fails)

---

## Milestone 1: Delete Existing Stacks (Day 1 - 1 day) ✅ COMPLETE

**Status**: ✅ Complete (November 23, 2025)

**Updated Duration**: Increased from 0.5 day to 1 day due to additional stacks (Monitoring, API) requiring deletion.

### Task 1A: Delete Monitoring Stack ✅ COMPLETE

**Status**: ✅ Complete (November 23, 2025)

**Why First?** Monitoring Stack has CloudWatch alarms that reference Compute Stack and API Stack resources. Must delete before deleting those stacks.

```bash
# Delete Monitoring Stack
cdk destroy Sentra-DEV-Monitoring-Stack --profile sentra --force

# Or via CloudFormation
aws cloudformation delete-stack \
  --stack-name Sentra-DEV-Monitoring-Stack \
  --profile sentra

# Wait for deletion (3-5 minutes)
aws cloudformation wait stack-delete-complete \
  --stack-name Sentra-DEV-Monitoring-Stack \
  --profile sentra

# Verify deletion
aws cloudformation describe-stacks \
  --stack-name Sentra-DEV-Monitoring-Stack \
  --profile sentra 2>&1 | grep "does not exist"
```

**Acceptance Criteria:**
- ✅ Monitoring Stack deleted
- ✅ CloudWatch alarms deleted
- ✅ SNS topics deleted

---

### Task 1B: Delete API Stack ✅ COMPLETE

**Status**: ✅ Complete (November 23, 2025)

**Why Second?** API Stack has a VPC Link that points to the ALB in Compute Stack. Must delete before deleting Compute Stack.

```bash
# Delete API Stack
cdk destroy Sentra-DEV-API-Stack --profile sentra --force

# Or via CloudFormation
aws cloudformation delete-stack \
  --stack-name Sentra-DEV-API-Stack \
  --profile sentra

# Wait for deletion (5-10 minutes - VPC Link takes time)
aws cloudformation wait stack-delete-complete \
  --stack-name Sentra-DEV-API-Stack \
  --profile sentra

# Verify deletion
aws cloudformation describe-stacks \
  --stack-name Sentra-DEV-API-Stack \
  --profile sentra 2>&1 | grep "does not exist"

# Verify VPC Link deleted
aws apigatewayv2 get-vpc-links --profile sentra
```

**Acceptance Criteria:**
- ✅ API Stack deleted
- ✅ API Gateway deleted
- ✅ VPC Link deleted
- ✅ Usage plan deleted

---

### Task 1C: Delete Compute Stack ✅ COMPLETE

**Status**: ✅ Complete (November 23, 2025)

**Step 1: Stop ECS Services (Graceful Shutdown)**
```bash
# Scale down all services to 0
aws ecs update-service \
  --cluster sentra-mvp-cluster \
  --service sentra-security-controller \
  --desired-count 0 \
  --profile sentra

aws ecs update-service \
  --cluster sentra-mvp-cluster \
  --service sentra-dashboard \
  --desired-count 0 \
  --profile sentra

aws ecs update-service \
  --cluster sentra-mvp-cluster \
  --service sentra-customer-query-agent \
  --desired-count 0 \
  --profile sentra

aws ecs update-service \
  --cluster sentra-mvp-cluster \
  --service sentra-payment-agent \
  --desired-count 0 \
  --profile sentra

# Wait for tasks to stop (2-3 minutes)
sleep 180
```

**Step 2: Delete Compute Stack**
```bash
# Delete via CDK
cdk destroy SentraComputeStack --profile sentra --force

# Or via CloudFormation
aws cloudformation delete-stack \
  --stack-name SentraComputeStack \
  --profile sentra

# Wait for deletion (10-15 minutes)
aws cloudformation wait stack-delete-complete \
  --stack-name SentraComputeStack \
  --profile sentra
```

**Step 3: Verify Deletion**
```bash
# Verify stack deleted
aws cloudformation describe-stacks \
  --stack-name SentraComputeStack \
  --profile sentra 2>&1 | grep "does not exist"

# Verify ECS cluster deleted
aws ecs describe-clusters \
  --clusters sentra-mvp-cluster \
  --profile sentra

# Verify ALB deleted
aws elbv2 describe-load-balancers \
  --names sentra-alb \
  --profile sentra 2>&1 | grep "not found"
```

**Acceptance Criteria:**
- ✅ All ECS services stopped
- ✅ Compute Stack deleted
- ✅ ECS cluster deleted
- ✅ ALB deleted
- ✅ Target groups deleted

---

### Task 1D: Delete Network Stack ✅ COMPLETE

**Status**: ✅ Complete (November 23, 2025)

**Step 1: Delete Network Stack**
```bash
# Delete via CDK
cdk destroy SentraNetworkStack --profile sentra --force

# Or via CloudFormation
aws cloudformation delete-stack \
  --stack-name SentraNetworkStack \
  --profile sentra

# Wait for deletion (5-10 minutes)
aws cloudformation wait stack-delete-complete \
  --stack-name SentraNetworkStack \
  --profile sentra
```

**Step 2: Verify Deletion**
```bash
# Verify stack deleted
aws cloudformation describe-stacks \
  --stack-name SentraNetworkStack \
  --profile sentra 2>&1 | grep "does not exist"

# Verify VPC deleted
aws ec2 describe-vpcs \
  --filters "Name=tag:Name,Values=sentra-mvp-vpc" \
  --profile sentra

# Verify security groups deleted
aws ec2 describe-security-groups \
  --filters "Name=tag:Project,Values=sentra-mvp" \
  --profile sentra
```

**Acceptance Criteria:**
- ✅ Network Stack deleted
- ✅ VPC deleted
- ✅ Security groups deleted
- ✅ VPC endpoints deleted
- ✅ Route53 private hosted zone deleted

---

### Task 1E: Verify Storage Stack Intact ✅ COMPLETE

**Status**: ✅ Complete (November 23, 2025)
- DynamoDB: sentra-demo-customers (500 records) ✅
- DynamoDB: sentra-demo-orders (500 records) ✅
- DynamoDB: sentra-session-context (0 records) ✅
- ECR: All 4 images exist ✅
- S3: Artifacts bucket exists ✅

**Verify Data Preserved**
```bash
# Verify Storage Stack still exists
aws cloudformation describe-stacks \
  --stack-name SentraStorageStack \
  --profile sentra

# Verify DynamoDB tables still have data
aws dynamodb scan --table-name sentra-demo-customers --select COUNT --profile sentra
aws dynamodb scan --table-name sentra-demo-orders --select COUNT --profile sentra

# Verify S3 bucket still exists
aws s3 ls s3://sentra-mvp-artifacts-531109575379-us-east-1/ --profile sentra

# Verify ECR images still exist
aws ecr describe-images --repository-name sentra/customer-query-agent --profile sentra
aws ecr describe-images --repository-name sentra/payment-agent --profile sentra
```

**Acceptance Criteria:**
- ✅ Storage Stack exists
- ✅ DynamoDB tables have data
- ✅ S3 bucket exists
- ✅ ECR images exist
- ✅ No data loss

---

## Milestone 2: Update CDK Code (Day 2-3 - 2 days) ✅ COMPLETE

**Status**: ✅ Complete (November 23, 2025)

### Task 4: Fix Port Numbers in Network Stack ✅ COMPLETE

**Status**: ✅ Complete (November 23, 2025)

**File:** `cdk/stacks/network_stack.py`

**Problem:** Customer Query Agent and Payment Agent using wrong ports (8002, 8003 instead of 8080)

**Changes:**
```python
# BEFORE (WRONG)
self.customer_query_agent_sg.add_ingress_rule(
    peer=self.alb_sg,
    connection=ec2.Port.tcp(8002),  # ❌ WRONG
    description="Allow ALB to forward requests to Customer Query Agent API",
)

self.payment_agent_sg.add_ingress_rule(
    peer=self.alb_sg,
    connection=ec2.Port.tcp(8003),  # ❌ WRONG
    description="Allow ALB to forward requests to Payment Agent API",
)

# AFTER (CORRECT)
self.customer_query_agent_sg.add_ingress_rule(
    peer=self.alb_sg,
    connection=ec2.Port.tcp(8080),  # ✅ CORRECT
    description="Allow ALB to forward requests to Customer Query Agent API",
)

self.payment_agent_sg.add_ingress_rule(
    peer=self.alb_sg,
    connection=ec2.Port.tcp(8080),  # ✅ CORRECT
    description="Allow ALB to forward requests to Payment Agent API",
)
```

**Acceptance Criteria:**
- ✅ Port 8080 used for Customer Query Agent
- ✅ Port 8080 used for Payment Agent
- ✅ Code compiles without errors

---

### Task 4B: Update Network Stack Public Subnet Size ✅ COMPLETE

**Status**: ✅ Complete (November 23, 2025) - Already configured correctly

**File:** `cdk/stacks/network_stack.py`

**Problem:** Public ALB requires minimum /27 CIDR size (per AWS documentation). Current public subnets are /28 (16 IPs) which is too small.

**Current Configuration (WRONG):**
```python
ec2.SubnetConfiguration(
    subnet_type=ec2.SubnetType.PUBLIC,
    name="Public",
    cidr_mask=28,  # ❌ TOO SMALL for ALB
)
```

**Updated Configuration (CORRECT):**
```python
ec2.SubnetConfiguration(
    subnet_type=ec2.SubnetType.PUBLIC,
    name="Public",
    cidr_mask=24,  # ✅ Sufficient for Public ALB + NAT Gateway
)
```

**Subnet CIDR Ranges (after update):**
- **Public**: 10.0.1.0/24, 10.0.2.0/24 (upgraded from /28 to /24)
- **Private**: 10.0.11.0/24, 10.0.12.0/24 (no change)
- **Isolated**: 10.0.21.0/28, 10.0.22.0/28 (no change)

**Update Documentation in Code:**
```python
# Public subnets for NAT Gateway and Public ALB (10.0.1.0/24, 10.0.2.0/24)
# Updated from /28 to /24 to accommodate Public ALB (requires minimum /27 per AWS)
# ADR-019: Split ALB architecture requires Public ALB in public subnets
ec2.SubnetConfiguration(
    subnet_type=ec2.SubnetType.PUBLIC,
    name="Public",
    cidr_mask=24,  # /24 to accommodate Public ALB + NAT Gateway
),
```

**Acceptance Criteria:**
- ✅ Public subnet CIDR mask changed from 28 to 24
- ✅ Comments updated to reflect ADR-019
- ✅ Subnet ranges documented in docstring
- ✅ Code compiles without errors

---

### Task 5: Add Security Groups for Split ALBs ✅ COMPLETE

**Status**: ✅ Complete (November 23, 2025)

**File:** `cdk/stacks/network_stack.py`

**Add Two New Security Groups:**

```python
# 1. Public ALB Security Group (Dashboard only)
self.public_alb_sg = ec2.SecurityGroup(
    self,
    "PublicAlbSG",
    vpc=self.vpc,
    security_group_name="sentra-public-alb-sg",
    description="Security group for Public ALB (Dashboard only)",
    allow_all_outbound=False
)

# Ingress: Allow HTTP from internet
self.public_alb_sg.add_ingress_rule(
    peer=ec2.Peer.any_ipv4(),
    connection=ec2.Port.tcp(80),
    description="Allow HTTP from internet"
)

# Egress: Allow to Dashboard only
self.public_alb_sg.add_egress_rule(
    peer=self.dashboard_sg,
    connection=ec2.Port.tcp(8501),
    description="Allow to Dashboard"
)

# 2. Private ALB Security Group (API services)
self.private_alb_sg = ec2.SecurityGroup(
    self,
    "PrivateAlbSG",
    vpc=self.vpc,
    security_group_name="sentra-private-alb-sg",
    description="Security group for Private ALB (API services)",
    allow_all_outbound=False
)

# Ingress: Allow from Dashboard
self.private_alb_sg.add_ingress_rule(
    peer=self.dashboard_sg,
    connection=ec2.Port.tcp(80),
    description="Allow from Dashboard"
)

# Ingress: Allow from API services (inter-service communication)
self.private_alb_sg.add_ingress_rule(
    peer=self.security_controller_sg,
    connection=ec2.Port.tcp(80),
    description="Allow from Security Controller"
)

self.private_alb_sg.add_ingress_rule(
    peer=self.customer_query_agent_sg,
    connection=ec2.Port.tcp(80),
    description="Allow from Customer Query Agent"
)

self.private_alb_sg.add_ingress_rule(
    peer=self.payment_agent_sg,
    connection=ec2.Port.tcp(80),
    description="Allow from Payment Agent"
)

# Egress: Allow to all API services
self.private_alb_sg.add_egress_rule(
    peer=self.security_controller_sg,
    connection=ec2.Port.tcp(8080),
    description="Allow to Security Controller"
)

self.private_alb_sg.add_egress_rule(
    peer=self.customer_query_agent_sg,
    connection=ec2.Port.tcp(8080),
    description="Allow to Customer Query Agent"
)

self.private_alb_sg.add_egress_rule(
    peer=self.payment_agent_sg,
    connection=ec2.Port.tcp(8080),
    description="Allow to Payment Agent"
)
```

**Update Dashboard Security Group:**
```python
# Dashboard needs to call Private ALB
self.dashboard_sg.add_egress_rule(
    peer=self.private_alb_sg,
    connection=ec2.Port.tcp(80),
    description="Allow Dashboard to call Private ALB"
)
```

**Remove Old ALB Security Group:**
```python
# Delete or comment out the old self.alb_sg
# It will be replaced by public_alb_sg and private_alb_sg
```

**Add CloudFormation Outputs:**
```python
CfnOutput(
    self,
    "PublicAlbSgId",
    value=self.public_alb_sg.security_group_id,
    description="Security group ID for Public ALB",
    export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-public-alb-sg-id",
)

CfnOutput(
    self,
    "PrivateAlbSgId",
    value=self.private_alb_sg.security_group_id,
    description="Security group ID for Private ALB",
    export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-private-alb-sg-id",
)
```

**Acceptance Criteria:**
- ✅ `public_alb_sg` created
- ✅ `private_alb_sg` created
- ✅ Dashboard can reach Private ALB
- ✅ Old `alb_sg` removed
- ✅ Code compiles without errors

---

### Task 6: Create Cognito Stack ✅ COMPLETE

**Status**: ✅ Complete (November 23, 2025)

**File:** `cdk/stacks/cognito_stack.py` (NEW FILE)

**Create Complete Cognito Stack:**


```python
"""
Sentra MVP - Cognito Stack
Creates AWS Cognito User Pool for Dashboard authentication

Reference: LLD 08 Section 5.1
"""

from aws_cdk import (
    Stack,
    RemovalPolicy,
    CfnOutput,
    Duration,
    aws_cognito as cognito,
)
from constructs import Construct
from typing import Dict, Any


class CognitoStack(Stack):
    """
    Cognito Stack - User Authentication

    Creates:
    - Cognito User Pool
    - User Pool Client (for ALB integration)
    - User Pool Domain (hosted UI)

    Exports:
    - User Pool ID and ARN
    - User Pool Client ID
    - User Pool Domain
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        config: Dict[str, Any],
        **kwargs
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        cognito_config = config.get("cognito", {})
        naming_config = config.get("naming", {})
        prefix = naming_config.get("prefix", "sentra-mvp")

        # Create User Pool
        self.user_pool = cognito.UserPool(
            self,
            "DashboardUserPool",
            user_pool_name=cognito_config.get("user_pool_name", "sentra-dashboard-users"),
            
            # Sign-in configuration
            self_sign_up_enabled=False,  # Admin creates users
            sign_in_aliases=cognito.SignInAliases(
                email=True,
                username=False
            ),
            
            # Password policy
            password_policy=cognito.PasswordPolicy(
                min_length=cognito_config.get("password_min_length", 12),
                require_uppercase=True,
                require_lowercase=True,
                require_digits=True,
                require_symbols=True,
                temp_password_validity=Duration.days(7)
            ),
            
            # Account recovery
            account_recovery=cognito.AccountRecovery.EMAIL_ONLY,
            
            # MFA (optional)
            mfa=cognito.Mfa.OPTIONAL if cognito_config.get("mfa_enabled", False) else cognito.Mfa.OFF,
            
            # Email configuration
            email=cognito.UserPoolEmail.with_cognito(),
            
            # User attributes
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(
                    required=True,
                    mutable=True
                )
            ),
            
            # Cleanup
            removal_policy=RemovalPolicy.DESTROY
        )

        # Create User Pool Client (for ALB)
        self.user_pool_client = cognito.UserPoolClient(
            self,
            "DashboardUserPoolClient",
            user_pool=self.user_pool,
            user_pool_client_name="sentra-dashboard-alb-client",
            
            # OAuth configuration (required for ALB)
            generate_secret=True,  # ALB requires client secret
            
            # Auth flows
            auth_flows=cognito.AuthFlow(
                user_password=True,
                user_srp=True,
                admin_user_password=True
            ),
            
            # OAuth settings (callback URLs will be updated after ALB creation)
            o_auth=cognito.OAuthSettings(
                flows=cognito.OAuthFlows(
                    authorization_code_grant=True
                ),
                scopes=[
                    cognito.OAuthScope.OPENID,
                    cognito.OAuthScope.EMAIL,
                    cognito.OAuthScope.PROFILE
                ],
                callback_urls=[
                    "http://localhost/oauth2/idpresponse"  # Placeholder, will be updated
                ],
                logout_urls=[
                    "http://localhost/"  # Placeholder, will be updated
                ]
            ),
            
            # Token validity
            id_token_validity=Duration.hours(1),
            access_token_validity=Duration.hours(1),
            refresh_token_validity=Duration.days(30),
            
            # Security
            prevent_user_existence_errors=True
        )

        # Create Cognito Domain (hosted UI)
        self.user_pool_domain = cognito.UserPoolDomain(
            self,
            "DashboardUserPoolDomain",
            user_pool=self.user_pool,
            cognito_domain=cognito.CognitoDomainOptions(
                domain_prefix=cognito_config.get("domain_prefix", "sentra-dashboard-mvp")
            )
        )

        # CloudFormation Outputs
        CfnOutput(
            self,
            "UserPoolId",
            value=self.user_pool.user_pool_id,
            description="Cognito User Pool ID",
            export_name=f"{prefix}-user-pool-id",
        )

        CfnOutput(
            self,
            "UserPoolArn",
            value=self.user_pool.user_pool_arn,
            description="Cognito User Pool ARN",
            export_name=f"{prefix}-user-pool-arn",
        )

        CfnOutput(
            self,
            "UserPoolClientId",
            value=self.user_pool_client.user_pool_client_id,
            description="Cognito User Pool Client ID",
            export_name=f"{prefix}-user-pool-client-id",
        )

        CfnOutput(
            self,
            "UserPoolDomain",
            value=self.user_pool_domain.domain_name,
            description="Cognito User Pool Domain",
            export_name=f"{prefix}-user-pool-domain",
        )
```

**Update app.py to include Cognito Stack:**
```python
# In cdk/app.py
from stacks.cognito_stack import CognitoStack

# Add after StorageStack
cognito_stack = CognitoStack(
    app,
    "SentraCognitoStack",
    config=config,
    env=env
)
```

**Acceptance Criteria:**
- ✅ `cognito_stack.py` created
- ✅ User Pool configured
- ✅ User Pool Client configured
- ✅ User Pool Domain configured
- ✅ Outputs defined
- ✅ Code compiles without errors

---

### Task 6C: Update app.py to Add CognitoStack ✅ COMPLETE

**Status**: ✅ Complete (November 23, 2025)

**File:** `cdk/app.py`

**Add Import:**
```python
# At the top of the file, update the import statement
from stacks import NetworkStack, StorageStack, ComputeStack, ApiStack, MonitoringStack
from stacks.cognito_stack import CognitoStack  # ADD THIS LINE
```

**Add CognitoStack Creation:**
```python
# Add after storage_stack creation (around line 124)
# Create Cognito Stack (Workstream 8)
cognito_stack = CognitoStack(
    app,
    f"{stack_prefix}-Cognito-Stack",
    config=config,
    env=env,
    description=f"Sentra MVP ({environment}) - Cognito User Pool for Dashboard Authentication",
)

# Add stack-level tags
for key, value in config.get("tags", {}).items():
    cdk.Tags.of(cognito_stack).add(key, value)
```

**Location**: Insert between `storage_stack` and `compute_stack` creation.

**Acceptance Criteria:**
- ✅ Import statement added
- ✅ CognitoStack instantiated
- ✅ Stack tags applied
- ✅ Code compiles without errors

---

### Task 6D: Update app.py to Pass CognitoStack to ComputeStack ✅ COMPLETE

**Status**: ✅ Complete (November 23, 2025)

**File:** `cdk/app.py`

**Update ComputeStack Instantiation:**
```python
# Update the existing ComputeStack creation (around line 127)
compute_stack = ComputeStack(
    app,
    f"{stack_prefix}-Compute-Stack",
    config=config,
    network_stack=network_stack,
    storage_stack=storage_stack,
    cognito_stack=cognito_stack,  # ADD THIS LINE
    env=env,
    description=f"Sentra MVP ({environment}) - ECS Cluster, ECR Repositories, IAM Roles, ALB, ECS Services",
)
compute_stack.add_dependency(network_stack)  # Needs VPC
compute_stack.add_dependency(storage_stack)  # Needs DynamoDB/S3 for IAM permissions
compute_stack.add_dependency(cognito_stack)  # ADD THIS LINE - Needs Cognito for Public ALB auth
```

**Acceptance Criteria:**
- ✅ `cognito_stack` parameter added to ComputeStack constructor
- ✅ Dependency added: `compute_stack.add_dependency(cognito_stack)`
- ✅ Code compiles without errors

---

### Task 7: Update Compute Stack - Split ALB ✅ COMPLETE

**Status**: ✅ Complete (November 23, 2025)

**File:** `cdk/stacks/compute_stack.py`

**Part A: Import Cognito Stack**
```python
def __init__(
    self,
    scope: Construct,
    construct_id: str,
    config: Dict[str, Any],
    network_stack,
    storage_stack,
    cognito_stack,  # NEW: Add Cognito Stack reference
    **kwargs
) -> None:
```

**Part B: Create Public ALB (Dashboard Only)**
```python
# Public ALB - Dashboard only
self.public_alb = elbv2.ApplicationLoadBalancer(
    self,
    "PublicApplicationLoadBalancer",
    load_balancer_name="sentra-public-alb",
    vpc=network_stack.vpc,
    internet_facing=True,  # Public
    vpc_subnets=ec2.SubnetSelection(
        subnet_type=ec2.SubnetType.PUBLIC
    ),
    security_group=network_stack.public_alb_sg,
    deletion_protection=False,
    idle_timeout=Duration.seconds(60)
)

# Dashboard Target Group
self.dashboard_tg = elbv2.ApplicationTargetGroup(
    self,
    "DashboardTargetGroup",
    target_group_name="sentra-dashboard-tg",
    vpc=network_stack.vpc,
    port=8501,
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

# Public ALB Listener with Cognito Authentication
self.public_http_listener = self.public_alb.add_listener(
    "PublicHttpListener",
    port=80,
    protocol=elbv2.ApplicationProtocol.HTTP,
    default_action=elbv2.ListenerAction.authenticate_cognito(
        user_pool=cognito_stack.user_pool,
        user_pool_client=cognito_stack.user_pool_client,
        user_pool_domain=cognito_stack.user_pool_domain,
        next=elbv2.ListenerAction.forward(
            target_groups=[self.dashboard_tg]
        )
    )
)
```

**Part C: Create Private ALB (API Services)**
```python
# Private ALB - API services only
self.private_alb = elbv2.ApplicationLoadBalancer(
    self,
    "PrivateApplicationLoadBalancer",
    load_balancer_name="sentra-private-alb",
    vpc=network_stack.vpc,
    internet_facing=False,  # Private (KEY!)
    vpc_subnets=ec2.SubnetSelection(
        subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS
    ),
    security_group=network_stack.private_alb_sg,
    deletion_protection=False,
    idle_timeout=Duration.seconds(60)
)

# Target Groups for API Services
self.security_controller_tg = elbv2.ApplicationTargetGroup(
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

self.customer_query_agent_tg = elbv2.ApplicationTargetGroup(
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

self.payment_agent_tg = elbv2.ApplicationTargetGroup(
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

# Private ALB Listener with Path-Based Routing (NO AUTH)
self.private_http_listener = self.private_alb.add_listener(
    "PrivateHttpListener",
    port=80,
    protocol=elbv2.ApplicationProtocol.HTTP,
    default_action=elbv2.ListenerAction.fixed_response(
        status_code=404,
        content_type="text/plain",
        message_body="Not Found"
    )
)

# Routing rules for Private ALB
self.private_http_listener.add_action(
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
        target_groups=[self.security_controller_tg]
    )
)

self.private_http_listener.add_action(
    "CustomerQueryAgentRouting",
    priority=2,
    conditions=[
        elbv2.ListenerCondition.path_patterns([
            "/v1/agents/customer-query/*"
        ])
    ],
    action=elbv2.ListenerAction.forward(
        target_groups=[self.customer_query_agent_tg]
    )
)

self.private_http_listener.add_action(
    "PaymentAgentRouting",
    priority=3,
    conditions=[
        elbv2.ListenerCondition.path_patterns([
            "/v1/agents/payment/*"
        ])
    ],
    action=elbv2.ListenerAction.forward(
        target_groups=[self.payment_agent_tg]
    )
)
```

**Part D: Update Service Configurations**

Update the `service_configs` dictionary to use the correct target groups:

```python
service_configs = {
    "security-controller": {
        "log_group_name": "/ecs/sentra/security-controller",
        "port": 8080,
        "task_role": self.security_controller_task_role,
        "target_group": self.security_controller_tg,  # Private ALB
        "environment": {
            # ... existing env vars ...
        },
        "health_check_command": ["CMD-SHELL", "curl -f http://localhost:8080/v1/health || exit 1"],
    },
    "dashboard": {
        "log_group_name": "/ecs/sentra/dashboard",
        "port": 8501,
        "task_role": self.dashboard_task_role,
        "target_group": self.dashboard_tg,  # Public ALB
        "environment": {
            "PORT": "8501",
            "SERVICE_NAME": "dashboard",
            "SESSION_CONTEXT_TABLE": storage_stack.session_context_table.table_name,
            "AUDIT_LOG_GROUP": storage_stack.audit_log_group.log_group_name,
            "AWS_REGION": self.region,
            # IMPORTANT: Use Private ALB for API calls
            "SECURITY_CONTROLLER_URL": f"http://{self.private_alb.load_balancer_dns_name}",
            "CUSTOMER_QUERY_AGENT_URL": f"http://{self.private_alb.load_balancer_dns_name}",
            "PAYMENT_AGENT_URL": f"http://{self.private_alb.load_balancer_dns_name}",
        },
        "health_check_command": ["CMD-SHELL", "curl -f http://localhost:8501/_stcore/health || exit 1"],
    },
    "customer-query-agent": {
        "log_group_name": "/ecs/sentra/customer-query-agent",
        "port": 8080,
        "task_role": self.customer_query_agent_task_role,
        "target_group": self.customer_query_agent_tg,  # Private ALB
        "environment": {
            # ... existing env vars ...
            "SECURITY_CONTROLLER_URL": f"http://{self.private_alb.load_balancer_dns_name}",
            "PAYMENT_AGENT_URL": f"http://{self.private_alb.load_balancer_dns_name}",
        },
        "health_check_command": ["CMD-SHELL", "curl -f http://localhost:8080/v1/health || exit 1"],
    },
    "payment-agent": {
        "log_group_name": "/ecs/sentra/payment-agent",
        "port": 8080,
        "task_role": self.payment_agent_task_role,
        "target_group": self.payment_agent_tg,  # Private ALB
        "environment": {
            # ... existing env vars ...
            "SECURITY_CONTROLLER_URL": f"http://{self.private_alb.load_balancer_dns_name}",
        },
        "health_check_command": ["CMD-SHELL", "curl -f http://localhost:8080/v1/health || exit 1"],
    },
}
```

**Part E: Add CloudFormation Outputs**
```python
# Public ALB Outputs
CfnOutput(
    self,
    "PublicAlbDnsName",
    value=self.public_alb.load_balancer_dns_name,
    description="Public ALB DNS name (Dashboard access)",
    export_name=f"{prefix}-public-alb-dns-name",
)

CfnOutput(
    self,
    "PublicAlbArn",
    value=self.public_alb.load_balancer_arn,
    description="Public ALB ARN",
    export_name=f"{prefix}-public-alb-arn",
)

# Private ALB Outputs
CfnOutput(
    self,
    "PrivateAlbDnsName",
    value=self.private_alb.load_balancer_dns_name,
    description="Private ALB DNS name (API services - VPC internal only)",
    export_name=f"{prefix}-private-alb-dns-name",
)

CfnOutput(
    self,
    "PrivateAlbArn",
    value=self.private_alb.load_balancer_arn,
    description="Private ALB ARN",
    export_name=f"{prefix}-private-alb-arn",
)
```

**Acceptance Criteria:**
- ✅ Public ALB created (internet-facing)
- ✅ Private ALB created (internal)
- ✅ Cognito authentication on Public ALB
- ✅ Path-based routing on Private ALB
- ✅ Dashboard uses Private ALB for API calls
- ✅ All target groups configured
- ✅ Code compiles without errors

---

### Task 8: Update Configuration Files ✅ COMPLETE

**Status**: ✅ Complete (November 23, 2025)

**File:** `cdk/config/environments/dev.yaml`

**Add Cognito Configuration:**
```yaml
cognito:
  user_pool_name: sentra-dashboard-users
  domain_prefix: sentra-dashboard-mvp  # Must be globally unique
  password_min_length: 12
  mfa_enabled: false  # Optional for MVP

alb:
  public:
    name: sentra-public-alb
    internet_facing: true
  private:
    name: sentra-private-alb
    internet_facing: false
```

**Acceptance Criteria:**
- ✅ Cognito config added
- ✅ ALB config updated
- ✅ YAML syntax valid

---

### Task 8B: Verify and Update Subnet Configuration (if needed) ✅ COMPLETE

**Status**: ✅ Complete (November 23, 2025) - Configuration verified, no changes needed

**File:** `cdk/config/dev.yaml`

**IMPORTANT**: Verify that the subnet configuration in `dev.yaml` matches the actual network stack implementation.

**Current network_stack.py Configuration:**
- Public subnets: /24 (updated for Public ALB)
- Private subnets: /24
- Isolated subnets: /28

**Check dev.yaml:**
```yaml
vpc:
  subnets:
    public:  # May not exist in current config
      - cidr_mask: 24  # Should match network_stack.py
    private:
      - cidr_mask: 24  # Should match network_stack.py
    isolated:
      - cidr_mask: 28  # Should match network_stack.py
```

**Note:** The `dev.yaml` may not have explicit `public` subnet configuration because it's hardcoded in `network_stack.py`. This is acceptable as long as `network_stack.py` has been updated (Task 4B).

**Verification:**
```bash
# Check if dev.yaml needs updating
grep -A 10 "subnets:" cdk/config/dev.yaml

# Expected: Should see private and isolated subnets defined
# Public subnet size is hardcoded in network_stack.py (line 83: cidr_mask=24)
```

**Action:**
- ✅ If `dev.yaml` has no `public` subnet config: **NO ACTION NEEDED** (hardcoded in network_stack.py)
- ⚠️ If `dev.yaml` has `public` subnet with cidr_mask: 28: **UPDATE TO 24**

**Acceptance Criteria:**
- ✅ Subnet configuration verified
- ✅ No conflicts between dev.yaml and network_stack.py
- ✅ Public subnet size is /24 (either in dev.yaml or hardcoded in network_stack.py)

---

## Milestone 3: Deploy New Infrastructure (Day 4 - 0.5 day) ✅ COMPLETE

**Status**: ✅ Complete (November 23, 2025)

### Task 9: Deploy Stacks in Order ✅ COMPLETE

**Status**: ✅ Complete (November 23, 2025)

**Deployed Stacks:**
- Network Stack: VPC, Security Groups, Service Discovery
- Cognito Stack: User Pool (ready for HTTPS)
- Compute Stack: Split ALB (Public + Private), ECS Services
- API Stack: API Gateway
- Monitoring Stack: CloudWatch Dashboard & Alarms

**Key URLs:**
- Dashboard: http://sentra-public-alb-1709534853.us-east-1.elb.amazonaws.com
- API Gateway: https://b94mmiog0k.execute-api.us-east-1.amazonaws.com/prod/

**Step 1: Synthesize CDK**
```bash
# Verify CDK code compiles
cdk synth --profile sentra

# Check for errors
echo $?  # Should be 0
```

**Step 2: Deploy Network Stack**
```bash
cdk deploy SentraNetworkStack --profile sentra

# Wait for completion (5-10 minutes)
# Verify outputs
aws cloudformation describe-stacks \
  --stack-name SentraNetworkStack \
  --query 'Stacks[0].Outputs' \
  --profile sentra
```

**Step 3: Deploy Cognito Stack**
```bash
cdk deploy SentraCognitoStack --profile sentra

# Wait for completion (2-3 minutes)
# Save User Pool ID
USER_POOL_ID=$(aws cloudformation describe-stacks \
  --stack-name SentraCognitoStack \
  --query 'Stacks[0].Outputs[?OutputKey==`UserPoolId`].OutputValue' \
  --output text \
  --profile sentra)

echo "User Pool ID: $USER_POOL_ID"
```

**Step 4: Deploy Compute Stack**
```bash
cdk deploy SentraComputeStack --profile sentra

# Wait for completion (15-20 minutes)
# Save ALB DNS names
PUBLIC_ALB_DNS=$(aws cloudformation describe-stacks \
  --stack-name SentraComputeStack \
  --query 'Stacks[0].Outputs[?OutputKey==`PublicAlbDnsName`].OutputValue' \
  --output text \
  --profile sentra)

PRIVATE_ALB_DNS=$(aws cloudformation describe-stacks \
  --stack-name SentraComputeStack \
  --query 'Stacks[0].Outputs[?OutputKey==`PrivateAlbDnsName`].OutputValue' \
  --output text \
  --profile sentra)

echo "Public ALB DNS: $PUBLIC_ALB_DNS"
echo "Private ALB DNS: $PRIVATE_ALB_DNS"
```

**Step 5: Update Cognito Callback URLs**
```bash
# Get User Pool Client ID
CLIENT_ID=$(aws cloudformation describe-stacks \
  --stack-name SentraCognitoStack \
  --query 'Stacks[0].Outputs[?OutputKey==`UserPoolClientId`].OutputValue' \
  --output text \
  --profile sentra)

# Update callback URLs with actual ALB DNS
aws cognito-idp update-user-pool-client \
  --user-pool-id $USER_POOL_ID \
  --client-id $CLIENT_ID \
  --callback-urls "http://$PUBLIC_ALB_DNS/oauth2/idpresponse" \
  --logout-urls "http://$PUBLIC_ALB_DNS/" \
  --profile sentra
```

**Acceptance Criteria:**
- ✅ Network Stack deployed
- ✅ Cognito Stack deployed
- ✅ Compute Stack deployed
- ✅ All stacks show CREATE_COMPLETE
- ✅ Cognito callback URLs updated
- ✅ No deployment errors

---

## Milestone 4: Create Users and Test (Day 5 - 1 day) ✅ COMPLETE

**Status**: ✅ Complete (November 23, 2025)

### Task 10: Create Cognito Admin User ✅ COMPLETE

**Status**: ✅ Complete (November 23, 2025)

**Users Created:**
- admin@sentra.com / TempPassword123!
- demo@sentra.com / DemoPassword123!

**Using Automated Script (Recommended):**

```bash
# Option 1: Create users with default credentials (dev/demo only)
# Default users: admin@sentra.com / TempPassword123!, demo@sentra.com / DemoPassword123!
./scripts/create-cognito-users.sh dev

# Option 2: Create specific user via command line
./scripts/create-cognito-users.sh --email admin@sentra.com --password "MySecurePassword123!" dev

# Option 3: Create users from environment variables
export SENTRA_ADMIN_EMAIL="admin@sentra.com"
export SENTRA_ADMIN_TEMP_PASSWORD="TempPassword123!"
./scripts/create-cognito-users.sh dev

# Option 4: Create users from config file
cp scripts/.cognito-users.conf.example scripts/.cognito-users.conf
# Edit .cognito-users.conf with your users
./scripts/create-cognito-users.sh dev
```

**Delete Users (if needed):**
```bash
# Delete specific user
./scripts/create-cognito-users.sh --delete --email admin@sentra.com dev

# Delete all users from config file or defaults
./scripts/create-cognito-users.sh --delete dev
```

**Script Features:**
- ✅ Automatically retrieves User Pool ID from CloudFormation
- ✅ Idempotent (safe to run multiple times)
- ✅ Supports multiple credential sources
- ✅ Includes delete functionality
- ✅ No credentials in version control

**Acceptance Criteria:**
- ✅ Admin user created (using script or manual command)
- ✅ Temporary password set
- ✅ User can login
- ✅ Script works for create/delete operations

---

### Task 11: Test Dashboard Access ✅ COMPLETE

**Status**: ✅ Complete (November 23, 2025)

**Critical Issue Discovered & Resolved:**

During initial testing, OAuth authentication was failing with `500 Internal Server Error` at the callback URL (`/oauth2/idpresponse`).

**Root Cause:** Public ALB security group was missing egress HTTPS (port 443) rule needed to reach Cognito token endpoint for OAuth code exchange.

**Solution Applied:**
```python
# In network_stack.py
public_alb_sg.add_egress_rule(
    peer=ec2.Peer.any_ipv4(),
    connection=ec2.Port.tcp(443),
    description="Allow HTTPS to Cognito for OAuth token exchange"
)
```

**Why This Was Critical:**
- ALB must call Cognito's token endpoint (over HTTPS) to exchange authorization code for tokens
- Without this egress rule, ALB cannot complete OAuth flow
- This is a common pitfall in ALB + Cognito authentication implementations

**Additional Fixes:**
1. **Custom Resource Pattern:** Moved callback URL update logic from Cognito Stack to Compute Stack using Lambda Custom Resource to avoid circular dependency
2. **Client Secret:** Confirmed ALB **REQUIRES** `generate_secret=True` (AWS docs can be confusing on this)
3. **Session Timeout:** Changed from integer `3600` to string `"3600"` (CDK type requirement)

**Documentation Updated:**
- LLD 08 Section 5.1.4: Custom Resource pattern documented
- LLD 08 Section 5.4.1: Security group HTTPS egress requirement documented
- LLD 08 Section 12: Troubleshooting guide added with all OAuth issues

**Current Status:**
- ✅ OAuth flow working end-to-end
- ✅ Users can login successfully
- ✅ Session management working
- ✅ Dashboard loads after authentication

**Get Public ALB DNS Name:**
```bash
# Get Public ALB DNS name from CloudFormation
PUBLIC_ALB_DNS=$(aws cloudformation describe-stacks \
  --stack-name Sentra-DEV-Compute-Stack \
  --query 'Stacks[0].Outputs[?OutputKey==`PublicAlbDnsName`].OutputValue' \
  --output text \
  --profile sentra)

echo "Dashboard URL: http://$PUBLIC_ALB_DNS"
```

**Note on Using Route53 Custom Domain:**

Currently, the MVP uses the **AWS-provided ALB DNS name** (e.g., `sentra-public-alb-123456.us-east-1.elb.amazonaws.com`).

**Why not use Route53 public domain now?**
- ❌ No public Route53 hosted zone configured (only private zone: `sentra.internal` for internal service discovery)
- ❌ No domain name registered (e.g., `sentra.ai`, `sentra-mvp.com`)
- ❌ No ACM certificate provisioned (required for HTTPS)
- ✅ ALB DNS works fine for dev/demo with Cognito authentication

**Future Enhancement (Phase 3):**
To use a custom domain like `dashboard.sentra.ai`:

1. **Register Domain** (one-time cost ~$12/year)
   ```bash
   # Register domain via Route53 or external registrar
   aws route53domains register-domain --domain-name sentra.ai
   ```

2. **Create Public Hosted Zone**
   ```python
   # In network_stack.py
   self.public_zone = route53.PublicHostedZone(
       self, "SentraPublicZone",
       zone_name="sentra.ai"
   )
   ```

3. **Request ACM Certificate**
   ```python
   # In compute_stack.py
   from aws_cdk import aws_certificatemanager as acm

   certificate = acm.Certificate(
       self, "DashboardCertificate",
       domain_name="dashboard.sentra.ai",
       validation=acm.CertificateValidation.from_dns(public_zone)
   )
   ```

4. **Add HTTPS Listener to Public ALB**
   ```python
   self.public_alb.add_listener(
       "PublicHttpsListener",
       port=443,
       protocol=elbv2.ApplicationProtocol.HTTPS,
       certificates=[certificate],
       default_action=...
   )
   ```

5. **Create DNS Record**
   ```python
   route53.ARecord(
       self, "DashboardDnsRecord",
       zone=public_zone,
       record_name="dashboard",
       target=route53.RecordTarget.from_alias(
           targets.LoadBalancerTarget(self.public_alb)
       )
   )
   ```

6. **Update Cognito Callback URLs**
   ```bash
   aws cognito-idp update-user-pool-client \
     --user-pool-id $USER_POOL_ID \
     --client-id $CLIENT_ID \
     --callback-urls "https://dashboard.sentra.ai/oauth2/idpresponse" \
     --logout-urls "https://dashboard.sentra.ai/"
   ```

**For Now (MVP):** Use the ALB DNS name - it works perfectly with Cognito auth.

---

**Test 1: Access Dashboard**
```bash
# Open Dashboard in browser
open "http://$PUBLIC_ALB_DNS"

# Expected: Redirect to Cognito login page
# URL should be: https://sentra-dashboard-mvp.auth.us-east-1.amazoncognito.com/login
```

**Test 2: Login**
- Enter email: `admin@sentra.com`
- Enter temporary password: `TempPassword123!` (or your custom password)
- Set new password (must meet requirements: 12+ chars, uppercase, lowercase, digits, symbols)
- Expected: Redirect back to Dashboard

**Test 3: Dashboard Loads**
- Verify Dashboard UI loads
- Verify no errors in browser console
- Verify session cookie set (AWSELBAuthSessionCookie)

**Test 4: Session Persistence**
```bash
# Refresh the page - should NOT redirect to login again
# Session should persist for 1 hour (token validity period)
```

**Acceptance Criteria:**
- ✅ Dashboard redirects to Cognito login
- ✅ Login successful with temporary password
- ✅ Password change flow works
- ✅ Dashboard loads after login
- ✅ Session persists across page refreshes
- ✅ Logout works
- ✅ Password change flow works
- ✅ Dashboard loads after login
- ✅ Session persists across page refreshes
- ✅ Logout works (optional test)

---

### Task 12: Test API Services ✅ COMPLETE

**Status**: ✅ Complete (November 23, 2025)

**Verification:**
- ✅ All ECS services running and healthy
- ✅ Target groups showing healthy targets
- ✅ Dashboard can reach Private ALB
- ✅ Inter-service communication working

**Test 1: Security Controller Health**
```bash
# From Dashboard container (internal)
# This should work because Dashboard can reach Private ALB

# Check ECS task logs
aws logs tail /ecs/sentra/dashboard --follow --profile sentra

# Look for successful API calls to Private ALB
```

**Test 2: Customer Query Agent**
```bash
# Test via Dashboard UI
# Click "Query Customers" tab
# Enter: "Show customers from California"
# Expected: Results displayed

# Check logs
aws logs tail /ecs/sentra/customer-query-agent --follow --profile sentra
```

**Test 3: Payment Agent**
```bash
# Test via Dashboard UI
# Click "Payment Agent" tab
# Enter: "Check refund status for order ord-12345"
# Expected: Refund status displayed

# Check logs
aws logs tail /ecs/sentra/payment-agent --follow --profile sentra
```

**Test 4: Verify APIs NOT Public**
```bash
# Try to access API from internet (should FAIL)
curl http://$PRIVATE_ALB_DNS/v1/health

# Expected: Connection timeout or refused
# This confirms APIs are private
```

**Acceptance Criteria:**
- ✅ Dashboard can call API services
- ✅ Customer Query Agent works
- ✅ Payment Agent works
- ✅ APIs NOT accessible from internet
- ✅ All health checks passing

---

## Milestone 5: Verification and Documentation (Day 6 - 0.5 day) ✅ COMPLETE

**Status**: ✅ Complete (November 23, 2025)

### Task 13: Verify All Services ✅ COMPLETE

**Status**: ✅ Complete (November 23, 2025)

**Verification Results:**
- ✅ All 6 stacks deployed successfully
- ✅ All ECS services healthy (4/4 running)
- ✅ All target groups healthy
- ✅ No errors in CloudWatch Logs
- ✅ OAuth authentication working
- ✅ Dashboard accessible via Public ALB
- ✅ API services accessible via Private ALB (internal only)

**Health Checks:**
```bash
# Check all ECS services
aws ecs describe-services \
  --cluster sentra-mvp-cluster \
  --services sentra-security-controller sentra-dashboard sentra-customer-query-agent sentra-payment-agent \
  --query 'services[*].[serviceName,status,runningCount,desiredCount]' \
  --output table \
  --profile sentra

# Check ALB target health
aws elbv2 describe-target-health \
  --target-group-arn $(aws elbv2 describe-target-groups \
    --names sentra-dashboard-tg \
    --query 'TargetGroups[0].TargetGroupArn' \
    --output text \
    --profile sentra) \
  --profile sentra

# Check CloudWatch Logs
aws logs tail /ecs/sentra/security-controller --since 10m --profile sentra
aws logs tail /ecs/sentra/dashboard --since 10m --profile sentra
aws logs tail /ecs/sentra/customer-query-agent --since 10m --profile sentra
aws logs tail /ecs/sentra/payment-agent --since 10m --profile sentra
```

**Acceptance Criteria:**
- ✅ All ECS services running
- ✅ All target groups healthy
- ✅ No errors in CloudWatch Logs
- ✅ Dashboard accessible
- ✅ APIs working

---

### Task 14: Update Documentation ✅ COMPLETE

**Status**: ✅ Complete (November 23, 2025)

**Documentation Updated:**
- ✅ LLD 08 updated to v2.0 with implementation details
- ✅ Custom Resource pattern documented (Section 5.1.4)
- ✅ Security group HTTPS egress documented (Section 5.4.1)
- ✅ Troubleshooting guide added (Section 12)
- ✅ Workstream 8 task file updated with completion status

**Update Files:**
1. `README.md` - Add new Dashboard URL and login instructions
2. `PHASE2_IMPLEMENTATION_PLAN.md` - Mark as complete
3. `tasks/workstream-8-authentication-alb-split.md` - Mark tasks complete

**Create User Guide:**
```markdown
# Sentra Dashboard Access

## URL
http://<PUBLIC_ALB_DNS>

## Login
- Email: admin@sentra.com
- Password: (set during first login)

## Features
- Customer Query Agent
- Payment Agent
- Security Monitoring

## API Access (Internal Only)
APIs are not publicly accessible. Use VPN or SSM for direct API testing.
```

**Acceptance Criteria:**
- ✅ Documentation updated
- ✅ User guide created
- ✅ New URLs documented
- ✅ Login instructions clear

---

## Milestone 6: OPTIONAL - Custom Domain & HTTPS (Day 6 - 0.5 day)

**Status**: Optional Enhancement (can be done now or later)

**Why Add This?**
- ✅ Security is handled (Cognito authentication on Public ALB)
- ✅ Significantly better UX: `https://dashboard.sentra-mvp.com` vs ugly ALB DNS
- ✅ Professional for demos and customer presentations
- ✅ Enables HTTPS with ACM certificate (better security)
- ✅ Would need to do eventually anyway

**Prerequisites:**
- Domain name available (either registered or ready to register)
- Budget for domain (~$12/year) and Route53 hosted zone ($0.50/month)

---

### Task 15: Register Domain (One-Time)

**Option 1: Register via Route53**
```bash
# Check if domain is available
aws route53domains check-domain-availability \
  --domain-name sentra-mvp.com \
  --profile sentra

# Register domain (if available)
aws route53domains register-domain \
  --domain-name sentra-mvp.com \
  --duration-in-years 1 \
  --admin-contact file://contact-info.json \
  --registrant-contact file://contact-info.json \
  --tech-contact file://contact-info.json \
  --profile sentra

# Cost: ~$12/year (varies by TLD)
```

**Option 2: Use Existing Domain from External Registrar**
- If you already have a domain (e.g., from GoDaddy, Namecheap)
- You'll need to update nameservers to point to Route53 (Task 16C)

**Contact Info Template** (`contact-info.json`):
```json
{
  "FirstName": "Admin",
  "LastName": "User",
  "ContactType": "COMPANY",
  "OrganizationName": "Sentra MVP",
  "AddressLine1": "123 Main St",
  "City": "Seattle",
  "State": "WA",
  "CountryCode": "US",
  "ZipCode": "98101",
  "PhoneNumber": "+1.2065551234",
  "Email": "admin@sentra.com"
}
```

**Acceptance Criteria:**
- ✅ Domain registered (or existing domain ready to use)
- ✅ Domain shows up in Route53 Registered Domains (if using Route53)

---

### Task 16: Create Public Hosted Zone and DNS Record

**Task 16A: Update Network Stack - Add Public Hosted Zone**

**File:** `cdk/stacks/network_stack.py`

**Add Import:**
```python
from aws_cdk import (
    # ... existing imports ...
    aws_route53 as route53,
)
```

**Add Public Hosted Zone** (after Private Hosted Zone section):
```python
# ============================================================
# Route53 Public Hosted Zone (Optional - Task 16A)
# ============================================================
# See LLD Section 2.2 for Route53 DNS design

public_domain = route53_config.get("public_domain")  # e.g., "sentra-mvp.com"

if public_domain:
    self.public_zone = route53.PublicHostedZone(
        self,
        "SentraPublicZone",
        zone_name=public_domain,
        comment="Public DNS for Sentra MVP Dashboard",
    )

    # CloudFormation Output
    CfnOutput(
        self,
        "PublicHostedZoneId",
        value=self.public_zone.hosted_zone_id,
        description="Route53 Public Hosted Zone ID",
        export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-public-zone-id",
    )

    CfnOutput(
        self,
        "PublicHostedZoneName",
        value=self.public_zone.zone_name,
        description="Route53 Public Hosted Zone name",
        export_name=f"{naming_config.get('prefix', 'sentra-mvp')}-public-zone-name",
    )

    # Output nameservers for domain configuration
    CfnOutput(
        self,
        "PublicHostedZoneNameServers",
        value=cdk.Fn.join(",", self.public_zone.hosted_zone_name_servers or []),
        description="Route53 Public Hosted Zone nameservers (configure at domain registrar)",
    )
else:
    self.public_zone = None
    log_info("Skipping public hosted zone - public_domain not configured")
```

**Task 16B: Update Configuration**

**File:** `cdk/config/dev.yaml`

Add:
```yaml
route53:
  private_zone_name: sentra.internal  # Existing
  public_domain: sentra-mvp.com  # NEW - your registered domain
```

**Task 16C: Update Nameservers (if using external registrar)**

```bash
# Deploy Network Stack to get nameservers
cdk deploy SentraNetworkStack --profile sentra

# Get nameservers
NAMESERVERS=$(aws cloudformation describe-stacks \
  --stack-name SentraNetworkStack \
  --query 'Stacks[0].Outputs[?OutputKey==`PublicHostedZoneNameServers`].OutputValue' \
  --output text \
  --profile sentra)

echo "Update your domain registrar with these nameservers:"
echo "$NAMESERVERS"

# If using Route53 for registration, this is automatic
# If using GoDaddy/Namecheap, update nameservers manually
```

**Acceptance Criteria:**
- ✅ Public hosted zone created
- ✅ Nameservers configured (if external registrar)
- ✅ DNS propagation verified (may take 24-48 hours)

---

### Task 17: Request ACM Certificate

**Task 17A: Update Compute Stack - Add ACM Certificate**

**File:** `cdk/stacks/compute_stack.py`

**Add Import:**
```python
from aws_cdk import (
    # ... existing imports ...
    aws_certificatemanager as acm,
)
```

**Add Certificate** (before creating Public ALB):
```python
# ============================================================
# ACM Certificate (Optional - Task 17A)
# ============================================================
# HTTPS certificate for Public ALB Dashboard access

if network_stack.public_zone:
    dashboard_domain = f"dashboard.{network_stack.public_zone.zone_name}"

    self.certificate = acm.Certificate(
        self,
        "DashboardCertificate",
        domain_name=dashboard_domain,
        validation=acm.CertificateValidation.from_dns(network_stack.public_zone),
        subject_alternative_names=[network_stack.public_zone.zone_name],  # Optional: apex domain
    )

    log_info(f"ACM certificate requested for: {dashboard_domain}")
else:
    self.certificate = None
    log_info("Skipping ACM certificate - no public hosted zone configured")
```

**Deploy and Wait for Certificate Validation:**
```bash
# Deploy Compute Stack
cdk deploy SentraComputeStack --profile sentra

# Certificate validation is automatic via DNS
# CDK will create validation CNAME records in Route53
# Wait 5-10 minutes for validation to complete

# Check certificate status
aws acm list-certificates \
  --certificate-statuses ISSUED \
  --profile sentra \
  --region us-east-1
```

**Acceptance Criteria:**
- ✅ ACM certificate created
- ✅ DNS validation records created automatically
- ✅ Certificate status = ISSUED (may take 5-10 minutes)

---

### Task 18: Add HTTPS Listener to Public ALB

**File:** `cdk/stacks/compute_stack.py`

**Update Public ALB Listener** (replace HTTP listener with HTTPS):

```python
# Public ALB Listener - HTTPS with Cognito Authentication
if self.certificate:
    # HTTPS Listener (port 443)
    self.public_https_listener = self.public_alb.add_listener(
        "PublicHttpsListener",
        port=443,
        protocol=elbv2.ApplicationProtocol.HTTPS,
        certificates=[self.certificate],
        default_action=elbv2.ListenerAction.authenticate_cognito(
            user_pool=cognito_stack.user_pool,
            user_pool_client=cognito_stack.user_pool_client,
            user_pool_domain=cognito_stack.user_pool_domain,
            next=elbv2.ListenerAction.forward(
                target_groups=[self.dashboard_tg]
            )
        )
    )

    # HTTP Listener (port 80) - Redirect to HTTPS
    self.public_http_listener = self.public_alb.add_listener(
        "PublicHttpListener",
        port=80,
        protocol=elbv2.ApplicationProtocol.HTTP,
        default_action=elbv2.ListenerAction.redirect(
            protocol="HTTPS",
            port="443",
            permanent=True
        )
    )

    log_info("Public ALB configured with HTTPS (port 443) and HTTP->HTTPS redirect")
else:
    # HTTP Listener only (existing code)
    self.public_http_listener = self.public_alb.add_listener(
        "PublicHttpListener",
        port=80,
        protocol=elbv2.ApplicationProtocol.HTTP,
        default_action=elbv2.ListenerAction.authenticate_cognito(
            user_pool=cognito_stack.user_pool,
            user_pool_client=cognito_stack.user_pool_client,
            user_pool_domain=cognito_stack.user_pool_domain,
            next=elbv2.ListenerAction.forward(
                target_groups=[self.dashboard_tg]
            )
        )
    )

    log_info("Public ALB configured with HTTP only (no certificate)")
```

**Acceptance Criteria:**
- ✅ HTTPS listener on port 443
- ✅ HTTP listener redirects to HTTPS
- ✅ Cognito authentication works on HTTPS

---

### Task 19: Create DNS A Record for Dashboard

**File:** `cdk/stacks/compute_stack.py`

**Add DNS Record** (after creating Public ALB):

```python
# ============================================================
# Route53 A Record for Dashboard (Optional - Task 19)
# ============================================================

if network_stack.public_zone:
    from aws_cdk.aws_route53_targets import LoadBalancerTarget

    dashboard_domain = f"dashboard.{network_stack.public_zone.zone_name}"

    self.dashboard_dns_record = route53.ARecord(
        self,
        "DashboardDnsRecord",
        zone=network_stack.public_zone,
        record_name="dashboard",  # Creates dashboard.sentra-mvp.com
        target=route53.RecordTarget.from_alias(
            LoadBalancerTarget(self.public_alb)
        ),
        comment="Dashboard access via custom domain",
    )

    # Output dashboard URL
    CfnOutput(
        self,
        "DashboardCustomUrl",
        value=f"https://{dashboard_domain}" if self.certificate else f"http://{dashboard_domain}",
        description="Dashboard URL (custom domain)",
        export_name=f"{prefix}-dashboard-custom-url",
    )
```

**Acceptance Criteria:**
- ✅ A record created: `dashboard.sentra-mvp.com` → Public ALB
- ✅ DNS resolves correctly
- ✅ Custom URL accessible

---

### Task 20: Update Cognito Callback URLs

```bash
# Get stack outputs
USER_POOL_ID=$(aws cloudformation describe-stacks \
  --stack-name Sentra-DEV-Cognito-Stack \
  --query 'Stacks[0].Outputs[?OutputKey==`UserPoolId`].OutputValue' \
  --output text \
  --profile sentra)

CLIENT_ID=$(aws cloudformation describe-stacks \
  --stack-name Sentra-DEV-Cognito-Stack \
  --query 'Stacks[0].Outputs[?OutputKey==`UserPoolClientId`].OutputValue' \
  --output text \
  --profile sentra)

CUSTOM_DOMAIN=$(aws cloudformation describe-stacks \
  --stack-name Sentra-DEV-Compute-Stack \
  --query 'Stacks[0].Outputs[?OutputKey==`DashboardCustomUrl`].OutputValue' \
  --output text \
  --profile sentra)

# Update callback URLs to use custom domain
aws cognito-idp update-user-pool-client \
  --user-pool-id $USER_POOL_ID \
  --client-id $CLIENT_ID \
  --callback-urls "${CUSTOM_DOMAIN}/oauth2/idpresponse" \
  --logout-urls "${CUSTOM_DOMAIN}/" \
  --profile sentra

echo "Cognito callback URLs updated to: $CUSTOM_DOMAIN"
```

**Acceptance Criteria:**
- ✅ Callback URLs use custom domain
- ✅ Login flow works with custom domain
- ✅ Logout redirects to custom domain

---

### Task 21: Test Custom Domain Access

**Test HTTPS Access:**
```bash
# Get custom URL
CUSTOM_URL=$(aws cloudformation describe-stacks \
  --stack-name Sentra-DEV-Compute-Stack \
  --query 'Stacks[0].Outputs[?OutputKey==`DashboardCustomUrl`].OutputValue' \
  --output text \
  --profile sentra)

echo "Dashboard Custom URL: $CUSTOM_URL"

# Open in browser
open "$CUSTOM_URL"

# Expected:
# 1. Redirect to Cognito login (HTTPS)
# 2. Login successful
# 3. Redirect back to dashboard (HTTPS)
# 4. Browser shows secure lock icon
```

**Test HTTP Redirect:**
```bash
# Test HTTP -> HTTPS redirect
curl -I http://dashboard.sentra-mvp.com

# Expected: 301 Moved Permanently
# Location: https://dashboard.sentra-mvp.com/
```

**Verify Certificate:**
```bash
# Check SSL certificate
openssl s_client -connect dashboard.sentra-mvp.com:443 -servername dashboard.sentra-mvp.com

# Expected:
# - Certificate valid
# - Issued by Amazon
# - Subject: CN=dashboard.sentra-mvp.com
```

**Acceptance Criteria:**
- ✅ `https://dashboard.sentra-mvp.com` accessible
- ✅ HTTP redirects to HTTPS
- ✅ SSL certificate valid
- ✅ Cognito login works
- ✅ Dashboard loads correctly
- ✅ Browser shows secure lock icon

---

### Task 22: Update Documentation

**Update User Guide:**

**File:** `README.md` or User Guide

**Before:**
```markdown
## Dashboard URL
http://sentra-public-alb-123456789.us-east-1.elb.amazonaws.com
```

**After:**
```markdown
## Dashboard URL
https://dashboard.sentra-mvp.com

(Fallback: http://sentra-public-alb-123456789.us-east-1.elb.amazonaws.com)
```

**Update Task 14 Documentation:**
- Change URL to custom domain
- Note HTTPS instead of HTTP
- Update login instructions if needed

**Acceptance Criteria:**
- ✅ Documentation reflects custom domain
- ✅ HTTPS mentioned
- ✅ Fallback ALB DNS documented

---

## Milestone 6 Summary

**Total Duration:** 0.5 day (if domain already available)

**Tasks:**
- Task 15: Register domain (one-time, may take 24-48 hours for DNS propagation)
- Task 16: Create public hosted zone and DNS records
- Task 17: Request ACM certificate
- Task 18: Add HTTPS listener to Public ALB
- Task 19: Create DNS A record
- Task 20: Update Cognito callback URLs
- Task 21: Test custom domain access
- Task 22: Update documentation

**Cost:**
- Domain registration: ~$12/year
- Route53 hosted zone: $0.50/month
- ACM certificate: FREE
- **Total: ~$18/year**

**Benefits:**
- ✅ Professional URL: `https://dashboard.sentra-mvp.com`
- ✅ HTTPS security (encrypted traffic)
- ✅ Better for demos and customer presentations
- ✅ Browser shows secure lock icon
- ✅ No ugly AWS ALB DNS

**Decision Point:**
- **Do it now** if you want professional demo URL
- **Skip for now** if time/cost is a concern (can add later without downtime)

---

## 🎉 Implementation Complete Summary

**Completion Date:** November 23, 2025
**Total Duration:** 3 days (ahead of 5.5 day estimate)
**Status:** ✅ **FULLY OPERATIONAL**

### What Was Delivered

**Infrastructure:**
- ✅ 6 CloudFormation stacks deployed successfully
  - Network Stack (VPC, Security Groups, Service Discovery)
  - Storage Stack (DynamoDB, S3, ECR - preserved from Phase 1)
  - Cognito Stack (User Pool with OAuth)
  - Compute Stack (Split ALBs, ECS Services)
  - API Stack (API Gateway with VPC Link)
  - Monitoring Stack (CloudWatch Dashboard & Alarms)

**Architecture:**
```
Internet → Public ALB (Cognito Auth) → Dashboard (Streamlit)
                                             ↓
                                      Private ALB → API Services
                                             ↓
                                      - Security Controller
                                      - Customer Query Agent
                                      - Payment Agent
```

### Key Achievements

**Security:**
- ✅ Dashboard protected with AWS Cognito authentication
- ✅ API services not internet-accessible (Private ALB)
- ✅ OAuth 2.0 flow working end-to-end
- ✅ No AppSec violations

**Scalability:**
- ✅ Fault isolation (Dashboard failures don't affect APIs)
- ✅ Production-ready split ALB architecture
- ✅ Follows AWS Well-Architected Framework

**Cost:**
- ✅ Additional cost: ~$16/month (second ALB)
- ✅ Cognito: Free for < 50K MAUs
- ✅ Total infrastructure: ~$32/month

### Critical Issues Resolved

**Issue #1: OAuth 500 Error**
- **Problem:** ALB returning 500 Internal Server Error during OAuth callback
- **Root Cause:** Missing HTTPS egress rule in Public ALB security group
- **Solution:** Added `ec2.Port.tcp(443)` egress to allow Cognito token exchange
- **Impact:** OAuth flow now works perfectly

**Issue #2: Circular Dependency**
- **Problem:** Cognito needs ALB DNS, ALB needs Cognito User Pool
- **Solution:** Custom Resource Lambda in Compute Stack updates callback URLs
- **Impact:** Clean stack separation, no circular dependencies

**Issue #3: Client Secret Confusion**
- **Problem:** Unclear AWS documentation on client secret requirement
- **Solution:** Confirmed ALB **REQUIRES** `generate_secret=True`
- **Impact:** Authentication working correctly

### URLs and Access

**Dashboard:**
```
URL: https://sentra-public-alb-1320390749.us-east-1.elb.amazonaws.com
Auth: Cognito (admin@sentra.com / demo@sentra.com)
```

**API Gateway:**
```
URL: https://xc3v42h40l.execute-api.us-east-1.amazonaws.com/prod/v1/
Access: Via VPC Link to Private ALB
```

**CloudWatch Dashboard:**
```
URL: https://console.aws.amazon.com/cloudwatch/home?region=us-east-1#dashboards:name=sentra-mvp-dashboard
```

### Documentation Delivered

**Low-Level Design:**
- ✅ LLD 08 updated to v2.0 (Implemented status)
- ✅ Custom Resource pattern documented
- ✅ Security group requirements documented
- ✅ Troubleshooting guide with all OAuth issues

**Task Tracking:**
- ✅ All 19 core tasks completed
- ✅ 5 milestones completed
- ✅ Implementation notes captured

### Lessons Learned

**What Worked Well:**
- Custom Resource pattern for callback URL updates
- Clean slate approach (delete/redeploy)
- Incremental deployment (Network → Cognito → Compute → API → Monitoring)

**Gotchas for Future Reference:**
1. ALB **MUST** have HTTPS egress for Cognito OAuth
2. ALB **REQUIRES** client secret (despite confusing AWS docs)
3. Session timeout must be string `"3600"` not integer `3600`
4. Public subnets need /24 or larger for ALB (not /28)

### Next Steps (Optional Enhancements)

**Phase 3 - Custom Domain (Milestone 6):**
- Register domain (e.g., sentra-mvp.com)
- Add ACM certificate
- Configure HTTPS listener
- Create Route53 A record
- **Benefit:** Professional URL instead of ALB DNS

**Future Enhancements:**
- MFA for Cognito users
- WAF integration for additional security
- API key authentication for programmatic access
- Multi-region deployment

---

## Post-Implementation Checklist

### Infrastructure
- ✅ Network Stack deployed
- ✅ Cognito Stack deployed
- ✅ Compute Stack deployed
- ✅ Public ALB created (internet-facing)
- ✅ Private ALB created (internal)
- ✅ Security groups configured correctly (including HTTPS egress for OAuth)
- ✅ Target groups healthy

### Authentication
- ✅ Cognito User Pool created
- ✅ Admin users created (admin@sentra.com, demo@sentra.com)
- ✅ Login works (OAuth flow end-to-end)
- ✅ Session management works
- ✅ Logout works

### Services
- ✅ Dashboard accessible via Public ALB
- ✅ Dashboard requires authentication (Cognito)
- ✅ Security Controller running
- ✅ Customer Query Agent running
- ✅ Payment Agent running
- ✅ All health checks passing

### Security
- ✅ Dashboard has Cognito authentication
- ✅ APIs NOT accessible from internet (verified)
- ✅ APIs accessible from Dashboard (via Private ALB)
- ✅ Security groups enforce least privilege
- ✅ No AppSec violations

### Testing
- ✅ Dashboard login tested
- ✅ Customer Query Agent tested
- ✅ Payment Agent tested
- ✅ Inter-service communication tested
- ✅ API privacy verified (not public)

### Documentation
- ✅ LLD 08 updated to v2.0
- ✅ Troubleshooting guide created
- ✅ New URLs documented
- ✅ Tasks marked complete
- ✅ Implementation summary added

---

## Rollback Procedure

### If Phase 2 Fails

**Option 1: Restore from Git Backup**
```bash
# Checkout backup branch
git checkout backup-pre-phase2

# Deploy old stacks
cdk deploy --all --profile sentra
```

**Option 2: Restore from Git Tag**
```bash
# Checkout tagged version
git checkout v1.0-pre-phase2

# Deploy old stacks
cdk deploy --all --profile sentra
```

**Option 3: Manual Rollback**
```bash
# Delete new stacks
cdk destroy SentraComputeStack --profile sentra --force
cdk destroy SentraCognitoStack --profile sentra --force
cdk destroy SentraNetworkStack --profile sentra --force

# Checkout old code
git checkout backup-pre-phase2

# Deploy old stacks
cdk deploy --all --profile sentra
```

---

## Timeline Summary

| Milestone | Duration | Cumulative | Tasks |
|-----------|----------|------------|-------|
| **Milestone 0: Preparation** | 0.5 day | Day 0.5 | Task 0 (Git backup + data verification) |
| **Milestone 1: Delete Stacks** | 1 day | Day 1.5 | Tasks 1A, 1B, 1C, 1D, 1E |
| **Milestone 2: Update Code** | 2 days | Day 3.5 | Tasks 4, 4B, 5, 6, 6C, 6D, 7, 8, 8B |
| **Milestone 3: Deploy** | 0.5 day | Day 4 | Task 9 |
| **Milestone 4: Test** | 1 day | Day 5 | Tasks 10-12 |
| **Milestone 5: Verify** | 0.5 day | Day 5.5 | Tasks 13-14 |
| **Total** | **5.5 days** | **Day 5.5** | **19 tasks total** |

**Stack Deletion Order** (Milestone 1):
1. **Task 1A**: Monitoring Stack (monitors other stacks)
2. **Task 1B**: API Stack (depends on Compute ALB)
3. **Task 1C**: Compute Stack (has resources in Network subnets)
4. **Task 1D**: Network Stack (subnet CIDR change required)
5. **Task 1E**: Verify Storage Stack (KEEP - no changes, has data)

**New Tasks Added:**
- **Task 1A**: Delete Monitoring Stack (NEW)
- **Task 1B**: Delete API Stack (NEW)
- **Task 4B**: Update Network Stack Public Subnet Size (/28 → /24 for ALB)
- **Task 6C**: Update app.py to Add CognitoStack
- **Task 6D**: Update app.py to Pass CognitoStack to ComputeStack
- **Task 8B**: Verify and Update Subnet Configuration

**Why the Timeline Changed:**
- Original estimate: 5 days
- Revised estimate: 5.5 days (+0.5 day)
- Changes:
  - Milestone 0: -0.5 day (removed unnecessary documentation of resources being deleted)
  - Milestone 1: +0.5 day (added Monitoring + API stack deletion)
  - Milestone 2: +0.5 day (added 4 critical code update tasks)
- Net change: +0.5 day

---

## Success Criteria

### Must Have ✅ **ALL ACHIEVED**
- ✅ Dashboard accessible with Cognito authentication → **WORKING**
- ✅ API services private (not internet-accessible) → **VERIFIED**
- ✅ Dashboard can call API services via Private ALB → **WORKING**
- ✅ No AppSec violations → **CLEAN**
- ✅ All services healthy → **4/4 RUNNING**
- ✅ No data loss → **DATA PRESERVED**

### Nice to Have 🎯
- 🎯 MFA enabled (optional) → Available in Cognito, not enabled
- 🎯 Custom domain (Milestone 6 - optional) → Instructions provided
- 🎯 HTTPS with ACM certificate (Milestone 6 - optional) → Instructions provided
- 🎯 WAF integration (future enhancement) → Not implemented

---

**Status**: ✅ **IMPLEMENTATION COMPLETE**
**Completion Date**: November 23, 2025
**Duration**: 3 days (2.5 days ahead of schedule)
**Next Steps**: Optional Milestone 6 (Custom Domain + HTTPS) or proceed to next workstream
