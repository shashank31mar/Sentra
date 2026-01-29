# Workstream 1: CDK Infrastructure & Networking

**Component**: AWS CDK Infrastructure (LLD 01)
**Timeline**: Week 1-2 (10-12 days)
**Owner**: Infrastructure Team

---

## AWS Configuration

**Critical**: All tasks must use these AWS settings:

- **AWS Account ID**: `531109575379`
- **AWS Profile**: `sentra` (credentials configured in `~/.aws/credentials`)
- **Region**: `us-east-1` (IAD - Northern Virginia)

**Environment Setup**:
```bash
# Verify AWS profile configuration
export AWS_PROFILE=sentra
aws sts get-caller-identity  # Should show account 531109575379

# Verify region
export AWS_REGION=us-east-1
aws configure get region --profile sentra  # Should return us-east-1

# Set CDK context
export CDK_DEFAULT_ACCOUNT=531109575379
export CDK_DEFAULT_REGION=us-east-1
```

**CDK Bootstrap** (run once before Task 1):
```bash
# Bootstrap CDK for this account/region
cdk bootstrap aws://531109575379/us-east-1 --profile sentra
```

---

## ⚠️ Critical Rule: NO Dangling Resources

**MANDATORY**: When tearing down any stack, ensure ALL resources are cleaned up completely.

### Resource Cleanup Policy

1. **Before Destroying Any Stack:**
   - List all resources that will be deleted
   - Verify no production data will be lost
   - Document any manual cleanup required

2. **Destruction Order (MUST follow this order):**
   ```bash
   # REVERSE order of creation
   cdk destroy Sentra-DEV-Monitoring-Stack     # Last deployed
   cdk destroy Sentra-DEV-API-Stack
   cdk destroy Sentra-DEV-Compute-Stack
   cdk destroy Sentra-DEV-Storage-Stack
   cdk destroy Sentra-DEV-Network-Stack        # First deployed
   ```

3. **Manual Cleanup Required After `cdk destroy`:**
   ```bash
   # VPC Flow Logs (if RETAIN policy was set)
   aws logs delete-log-group --log-group-name /aws/vpc/sentra-mvp

   # S3 Buckets (must be empty first)
   aws s3 rm s3://sentra-mvp-artifacts --recursive
   aws s3 rb s3://sentra-mvp-artifacts

   # ECR Repositories (if images exist)
   aws ecr delete-repository --repository-name sentra/security-controller --force
   aws ecr delete-repository --repository-name sentra/customer-query-agent --force
   aws ecr delete-repository --repository-name sentra/payment-agent --force
   aws ecr delete-repository --repository-name sentra/dashboard --force

   # CloudWatch Log Groups (if RETAIN policy)
   aws logs delete-log-group --log-group-name /sentra/audit-logs
   aws logs delete-log-group --log-group-name /ecs/sentra/security-controller
   aws logs delete-log-group --log-group-name /ecs/sentra/customer-query-agent
   aws logs delete-log-group --log-group-name /ecs/sentra/payment-agent
   aws logs delete-log-group --log-group-name /ecs/sentra/dashboard
   ```

4. **Verification After Cleanup:**
   ```bash
   # Verify no stacks remain
   aws cloudformation list-stacks --stack-status-filter CREATE_COMPLETE UPDATE_COMPLETE

   # Verify no VPCs remain
   aws ec2 describe-vpcs --filters "Name=tag:Project,Values=Sentra"

   # Verify no S3 buckets remain
   aws s3 ls | grep sentra

   # Verify no DynamoDB tables remain
   aws dynamodb list-tables | grep sentra

   # Verify no ECR repositories remain
   aws ecr describe-repositories | grep sentra

   # Verify no NAT Gateways remain (COST!)
   aws ec2 describe-nat-gateways --filter "Name=state,Values=available"

   # Verify no Elastic IPs remain (COST!)
   aws ec2 describe-addresses --query 'Addresses[?AssociationId==null]'
   ```

5. **Cost Monitoring After Cleanup:**
   - Check AWS Cost Explorer for any ongoing charges
   - Verify NAT Gateway hours stopped accumulating
   - Confirm no hidden resources remain

### Removal Policies in Code

All CDK stacks MUST specify removal policies:

```python
# Example - different policies for different resource types

# Logs - DESTROY (can be recreated)
log_group = logs.LogGroup(
    self, "LogGroup",
    removal_policy=RemovalPolicy.DESTROY
)

# DynamoDB - DESTROY for dev/demo, RETAIN for prod
table = dynamodb.Table(
    self, "Table",
    removal_policy=RemovalPolicy.DESTROY  # For MVP/dev only
)

# S3 - RETAIN (must be manually emptied and deleted)
bucket = s3.Bucket(
    self, "Bucket",
    removal_policy=RemovalPolicy.RETAIN,
    auto_delete_objects=False  # Explicit manual deletion required
)
```

### Stack Naming Convention

All stacks MUST follow this naming pattern:
```
Sentra-{ENVIRONMENT}-{Component}-Stack

Examples:
- Sentra-DEV-Network-Stack
- Sentra-DEV-Storage-Stack
- Sentra-DEV-Compute-Stack
- Sentra-PROD-Network-Stack
```

This makes it easy to:
- Identify resources in AWS Console
- Filter by environment
- Understand resource purpose
- Track costs by stack

---

## Milestone 1: Network Foundation (Days 1-4)

### ✅ Task 1: CDK Project Setup and Basic VPC [COMPLETED]

- Initialize AWS CDK project structure with Python
- Create `cdk/` directory with proper structure: `app.py`, `stacks/`, `constructs/`
- Install dependencies: `aws-cdk-lib`, `constructs`, `boto3`
- Configure `cdk.json` with context: `account=531109575379`, `region=us-east-1`
- Configure `app.py` to use AWS profile `sentra` and account/region from context
- Implement `NetworkStack` class with basic VPC configuration
- Configure VPC with 10.0.0.0/16 CIDR, 2 AZs (us-east-1a, us-east-1b), 1 NAT Gateway
- Add subnet configuration: Private subnets (10.0.1.0/24, 10.0.2.0/24) and Isolated subnets (10.0.3.0/28, 10.0.4.0/28)
- Enable DNS hostnames and DNS support for ECS Service Discovery
- Add VPC Flow Logs to CloudWatch with 7-day retention
- Export VPC ID as CloudFormation output
- Test: `cdk synth --profile sentra` generates valid CloudFormation template
- Test: Verify template targets account 531109575379 and region us-east-1
- Test: `cdk deploy NetworkStack --profile sentra` successfully creates VPC
- Verify: VPC created in account 531109575379, region us-east-1
- Verify: VPC has 4 subnets (2 private in us-east-1a/1b, 2 isolated in us-east-1a/1b)
- _Requirements: LLD 01 Section 2.2, ADR-011_

**DEMO CHECKPOINT 1A**: VPC deployed with proper subnets visible in AWS Console

---

### ✅ Task 2: Security Groups Configuration [COMPLETED]

- Create 5 security groups in `NetworkStack`: `security-controller-sg`, `dashboard-sg`, `customer-query-agent-sg`, `payment-agent-sg`, `alb-sg`
- Configure ingress rules for Security Controller SG: TCP 8080 from dashboard, agents, and ALB security groups
- Configure ingress rules for Dashboard SG: TCP 8501 from ALB
- Configure ingress rules for Customer Query Agent SG: TCP 8080 from ALB
- Configure ingress rules for Payment Agent SG: TCP 8003 from ALB
- Configure ingress rules for ALB SG: TCP 443 from 0.0.0.0/0
- Configure egress rules: All outbound traffic for service SGs, specific ports for ALB SG
- Add descriptions for all security group rules (for audit trail)
- Export all 5 security group IDs as CloudFormation outputs
- Test: Deploy and verify security groups in AWS Console
- Verify: All ingress/egress rules match table in LLD Section 2.3
- _Requirements: LLD 01 Section 2.3, 2.4, ADR-015_

---

### ✅ Task 3: Route53 Private Hosted Zone [COMPLETED]

- Create Route53 Private Hosted Zone `sentra.internal` in `NetworkStack`
- Associate private zone with VPC created in Task 1
- Configure zone for automatic ECS Service Discovery (namespace setup)
- Add comment: "Internal service discovery for Sentra MVP"
- Export Private Hosted Zone ID as CloudFormation output
- Test: Deploy and verify hosted zone created in Route53 console
- Test: Query zone from within VPC (using test EC2 instance)
- Verify: Zone is private and not accessible from public internet
- _Requirements: LLD 01 Section 2.3_

---

### ✅ Task 4: VPC Endpoints Setup [COMPLETED]

- Create 3 Interface Endpoints in Isolated subnets: ECR Docker, ECR API, CloudWatch Logs
- Create 2 Gateway Endpoints in Private subnets: S3, DynamoDB
- Configure security groups for interface endpoints (allow HTTPS from private subnets)
- Verify endpoint DNS names are resolvable within VPC
- Export endpoint IDs as CloudFormation outputs
- Test: Deploy all 5 VPC endpoints
- Test: From test EC2 in private subnet, verify S3 and DynamoDB access without NAT
- Verify: Interface endpoints show "available" status in AWS Console
- Verify: NAT Gateway shows reduced bandwidth usage (monitor for 1 hour)
- _Requirements: LLD 01 Section 2.5, ADR-014_

**DEMO CHECKPOINT 1**: Complete VPC infrastructure deployed - VPC, security groups, Route53 zone, and VPC endpoints all operational. Can deploy services privately with AWS service access.

---

## Milestone 2: Storage Layer (Days 5-7)

### ✅ Task 5: CloudWatch Log Group for Audit Trail [COMPLETED]

- Create new `StorageStack` class (depends on NetworkStack)
- Implement CloudWatch Log Group `/sentra/audit-logs` with 90-day retention
- Configure log group with `RemovalPolicy.RETAIN` (compliance requirement)
- Add optional KMS encryption for compliance (configurable via context variable)
- Create metric filter for high-severity threats (threat_severity = "HIGH")
- Configure metric to publish to `Sentra/Security` namespace
- Export Log Group name and ARN as CloudFormation outputs
- Test: Deploy StorageStack and verify log group created
- Test: Manually write test log event with JSON format from LLD Section 3.2
- Verify: Can query logs using CloudWatch Insights
- _Requirements: LLD 01 Section 3.2, ADR-013, ADR-017_

---

### ✅ Task 6: DynamoDB Tables - Session Context and Policies [COMPLETED]

- Implement DynamoDB table `sentra-session-context` with on-demand billing
- Configure partition key: `session_id` (STRING)
- Add GSI `agent-updated-index` (partition: agent_id, sort: last_activity)
- Enable TTL on `ttl` attribute (24-hour auto-expiration)
- Set `point_in_time_recovery=False` (ephemeral data)
- Implement DynamoDB table `sentra-policies` with on-demand billing
- Configure partition key: `policy_id` (STRING)
- Add GSI `agent-version-index` (partition: agent_id, sort: version)
- Enable DynamoDB Streams (NEW_AND_OLD_IMAGES) for audit
- Set `point_in_time_recovery=True` (critical config data)
- Export both table names and ARNs as CloudFormation outputs
- Test: Deploy both tables and verify in DynamoDB console
- Test: Write test item to session-context table and verify TTL behavior
- Test: Query GSI for both tables
- _Requirements: LLD 01 Section 3.3.1, 3.3.2, ADR-013_

---

### ✅ Task 7: DynamoDB Tables - Demo Data (Orders and Customers) [COMPLETED]

- Implement DynamoDB table `sentra-demo-orders` with on-demand billing
- Configure partition key: `order_id` (STRING)
- Add GSI `customer-index` (partition: customer_id, sort: created_at)
- Implement DynamoDB table `sentra-demo-customers` with on-demand billing
- Configure partition key: `customer_id` (STRING)
- Add GSI `state-index` (partition: state, sort: created_at)
- Set `removal_policy=DESTROY` for both demo tables (can delete)
- Export all table names and ARNs as CloudFormation outputs
- Create Python seeding script `scripts/seed_demo_data.py` using Faker library
- Seed script: Generate 500 orders with realistic data (amounts $100-$50,000)
- Seed script: Generate 500 customers with fake SSNs and addresses
- Seed script: Distribution - 150 CA, 100 NY, 80 TX, 70 FL, 100 other states
- Test: Deploy both tables
- Test: Run seeding script and verify 1000 total items created
- Test: Query customers by state using GSI
- _Requirements: LLD 01 Section 3.3.3, 3.3.4_

---

### ✅ Task 8: S3 Bucket and Folder Structure [COMPLETED]

- Implement S3 bucket `sentra-mvp-artifacts` with S3-managed encryption
- Enable versioning for rollback capability
- Configure block public access (all 4 settings enabled)
- Create folder structure: `policies/`, `sigma_rules/llm/`, `sbom/`, `compliance_exports/`, `debug_logs/`
- Add lifecycle rule: Archive `compliance_exports/` to Glacier after 30 days
- Add lifecycle rule: Delete `debug_logs/` after 7 days
- Set `removal_policy=RETAIN` (keep artifacts on stack deletion)
- Create sample Sigma rule file `sigma_rules/llm/prompt_injection_basic.yaml` with 10 patterns
- Create sample policy file `policies/refund-limit-policy-v1.yaml` with 3 rules
- Export bucket name, ARN, and regional domain name as outputs
- Test: Deploy bucket and verify all settings
- Test: Upload sample Sigma rule and policy to S3
- Test: Verify lifecycle policies applied correctly
- Verify: Public access is completely blocked (test with presigned URL)
- _Requirements: LLD 01 Section 3.4_

**DEMO CHECKPOINT 2**: Complete storage layer deployed - CloudWatch Logs, 4 DynamoDB tables (2 seeded with 1000 demo records), and S3 bucket with sample artifacts. Can write audit logs, query session state, and load policies.

---

## Milestone 3: Compute Foundation (Days 8-10)

### ✅ Task 9: ECS Cluster and ECR Repositories [COMPLETED]

- Create new `ComputeStack` class (depends on NetworkStack and StorageStack)
- Implement ECS Cluster `sentra-mvp-cluster` with Container Insights enabled
- Associate cluster with VPC from NetworkStack
- Create 4 ECR repositories: `sentra/security-controller`, `sentra/dashboard`, `sentra/customer-query-agent`, `sentra/payment-agent`
- Enable image scanning on push for all repositories
- Add lifecycle rule: Keep last 10 images per repository
- Set tag mutability to MUTABLE (MVP only, change to IMMUTABLE for production)
- Set `removal_policy=DESTROY` for repositories
- Export cluster name, cluster ARN, and all 4 ECR repository URIs as outputs
- Test: Deploy ComputeStack and verify cluster created
- Test: Build and push dummy Docker image to one ECR repository
- Verify: Image scanning completes and shows vulnerability report
- Verify: Lifecycle rule removes old images after 11th push
- _Requirements: LLD 01 Section 4.2, 4.3, ADR-001_

---

### ✅ Task 10: IAM Roles for ECS Tasks [COMPLETED]

- Create IAM Task Role for Security Controller with name `sentra-security-controller-task-role`
- Grant permissions: DynamoDB read/write on `session-context`, read on `policies`
- Grant permissions: S3 read on `sigma_rules/*` and `policies/*`, write on `debug_logs/*`
- Grant permissions: CloudWatch Logs `PutLogEvents` on audit log group
- Grant permissions: CloudWatch `PutMetricData` for custom metrics
- Grant permissions: Bedrock `InvokeModel` on Claude models (optional for validation)
- Create IAM Task Role for Dashboard with name `sentra-dashboard-task-role`
- Grant permissions: CloudWatch Logs `StartQuery`, `GetQueryResults` on audit logs
- Grant permissions: DynamoDB read on `session-context` table
- Create IAM Task Role for Customer Query Agent with name `sentra-customer-query-agent-task-role`
- Grant permissions: DynamoDB read on `demo-customers`, `demo-orders`
- Grant permissions: Bedrock `InvokeModel` on Claude Sonnet
- Create IAM Task Role for Payment Agent with name `sentra-payment-agent-task-role`
- Grant permissions: DynamoDB read/write on `demo-orders`
- Grant permissions: Bedrock `InvokeModel` on Claude Sonnet
- Create IAM Task Execution Role (shared by all tasks) for ECR pull and CloudWatch logging
- Export all 5 role ARNs as CloudFormation outputs
- Test: Deploy roles and verify in IAM console
- Test: Verify each role has correct trust policy (ecs-tasks.amazonaws.com)
- Verify: Validate IAM policy simulator for critical permissions
- _Requirements: LLD 01 Section 4.3, 4.4_

---

### ✅ Task 11: Application Load Balancer and Target Groups [COMPLETED]

- Create Application Load Balancer `sentra-alb` in private subnets
- Set internet-facing to True (public ALB - ADR-003 v2)
- Associate with ALB security group from Task 2
- Create 4 target groups: `security-controller-tg` (port 8080), `dashboard-tg` (port 8501), `customer-query-agent-tg` (port 8080), `payment-agent-tg` (port 8080)
- Configure target type as IP (required for Fargate)
- Add health checks: Path `/v1/health`, interval 30s, timeout 5s, healthy threshold 2, unhealthy threshold 3
- Create HTTP listener on port 80 with default action (return 404)
- Add listener rules with path-based routing:
  - Priority 1: `/v1/validate`, `/v1/health`, `/v1/logs`, `/v1/rollback` → security-controller-tg
  - Priority 2: `/v1/agents/customer-query/*` → customer-query-agent-tg
  - Priority 3: `/v1/agents/payment/*` → payment-agent-tg
  - Priority 4: `/*` → dashboard-tg (default)
- Enable access logs to S3 bucket (optional for MVP)
- Export ALB DNS name, ALB ARN, and all target group ARNs as outputs
- Test: Deploy ALB and verify in EC2 console
- Test: Curl ALB DNS from within VPC (should return 404 until services deployed)
- Verify: All target groups show "unused" status (no targets yet)
- _Requirements: LLD 01 Section 4.5, ADR-012_

---

### ✅ Task 12: ECS Task Definitions and Services [COMPLETED]

- Create CloudWatch Log Groups for all 4 services: `/ecs/sentra/security-controller`, `/ecs/sentra/dashboard`, `/ecs/sentra/customer-query-agent`, `/ecs/sentra/payment-agent`
- Set retention to 7 days for all container log groups
- Create Fargate Task Definition for Security Controller: 2 vCPU (2048), 4 GB RAM (4096)
- Add container: Port 8080, image from ECR repo (placeholder tag `latest`)
- Configure 12 environment variables from LLD Section 4.4.1
- Add health check: `curl -f http://localhost:8080/v1/health`
- Associate with IAM task role from Task 10
- Configure logging to CloudWatch (`awslogs` driver)
- Create Fargate Task Definitions for Dashboard, Customer Query Agent, Payment Agent (similar configuration)
- Ports: Dashboard (8501), Customer Query Agent (8002), Payment Agent (8003)
- Create 4 ECS Services with desired count 1, associated with respective target groups
- Enable Service Discovery: Register each service in Route53 private zone from Task 3
- Configure services to use private subnets and respective security groups
- Set deployment configuration: Min healthy 0%, Max 200% (allow rolling updates)
- Export all 4 service names and service ARNs as outputs
- Test: Deploy task definitions and services (services will fail without container images - expected)
- Test: Verify Service Discovery creates DNS records in Route53 (e.g., `security-controller.sentra.internal`)
- Verify: Services show in ECS console (will be in deployment loop until images pushed)
- _Requirements: LLD 01 Section 4.3, 4.4, ADR-016_

**DEMO CHECKPOINT 3**: Complete compute infrastructure ready - ECS cluster with 4 ECR repositories, IAM roles with proper permissions, ALB with path-based routing, and 4 ECS task definitions with service discovery. Infrastructure is ready to accept containerized services (pending Docker images).

---

## Milestone 4: API Gateway and Monitoring (Days 11-12)

### ✅ Task 13: API Gateway (Basic Setup) [COMPLETED - UPDATED TO REST API WITH PUBLIC ALB]

**ARCHITECTURE CHANGE**: Simplified to REST API with public ALB - NO VPC Link needed (ADR-003 v2, ADR-018)

**Key Change**: API Gateway directly integrates with internet-facing ALB using HTTP_PROXY integration. VPC Link is NOT required for this architecture.

- Create new `ApiStack` class (depends on ComputeStack for public ALB DNS)
- Implement REST API Gateway `sentra-mvp-api` with stage `prod`
- Create API Key `sentra-demo-key` with usage plan (100K req/month quota)
- Enable CloudWatch logging with access logs to `/aws/apigateway/sentra-mvp-access-logs`
- Configure HTTP_PROXY integration directly to public ALB DNS endpoint
  - Integration type: HTTP_PROXY
  - Integration URI: `http://{alb-dns-name}/{proxy}`
  - NO VPC Link connection required
  - Pass-through headers: X-Correlation-ID, X-API-Key-ID
- Add CORS configuration: Allow all origins (MVP only), methods, headers
- Configure global throttling: 100 req/sec rate limit, 200 burst limit
- Configure usage plan throttling and quota limits
- Set LogGroup RemovalPolicy to DESTROY for automatic cleanup
- Enable X-Ray tracing for API Gateway
- Export API Gateway URL, API Gateway ID, API Key ID, and ALB DNS as outputs
- Test: Deploy ApiStack
- Test: Call API Gateway URL with API key (should route to public ALB)
- Test: Verify 403 Forbidden without API key
- Verify: API Gateway access logs showing in CloudWatch
- Verify: ALB is internet-facing and publicly accessible
- Verify: No VPC Link resources created
- _Requirements: LLD 01 Section 5, LLD 02 (full details), ADR-003 v2, ADR-018_
- _Note: Public ALB simplifies MVP - no VPC Link, no NAT Gateway, $32/month cost savings_

---

### ✅ Task 14: Monitoring Stack - Dashboard and Alarms [COMPLETED]

- Create new `MonitoringStack` class (depends on all previous stacks)
- Implement CloudWatch Dashboard `sentra-mvp-dashboard`
- Add 12 widgets: ECS CPU/Memory (4 services), ALB requests, API Gateway 4XX/5XX errors, API Gateway latency, validation decisions, threat types, quarantined sessions, DynamoDB metrics
- Create SNS Topic `sentra-mvp-alerts` for email notifications
- Subscribe email (parameter: `alert_email`) to SNS topic
- Create 6 CloudWatch Alarms with SNS action:
  - `API-5XX-Errors`: API Gateway 5XX > 10 errors in 5 min
  - `API-High-Latency`: API Gateway p99 > 5 seconds in 5 min
  - `ECS-CPU-High`: ECS CPU > 80% in 5 min
  - `ECS-Memory-High`: ECS Memory > 80% in 5 min
  - `DynamoDB-Throttled`: Throttled requests > 5 in 1 min
  - `High-Severity-Threats`: Threat count > 10 in 5 min
- Export dashboard URL and SNS topic ARN as outputs
- Test: Deploy MonitoringStack
- Test: View dashboard in CloudWatch console (widgets will show empty until services running)
- Test: Trigger test alarm by temporarily lowering threshold
- Verify: Email notification received for test alarm
- _Requirements: LLD 01 Section 6, ADR-017_

**DEMO CHECKPOINT 4 (FINAL)**: Complete Sentra MVP infrastructure deployed end-to-end - 5 CloudFormation stacks with 50+ AWS resources. Ready for application code deployment. Verify:
- ✅ VPC with private networking and VPC endpoints operational
- ✅ Storage layer: CloudWatch Logs, 4 DynamoDB tables (seeded), S3 bucket with sample artifacts
- ✅ Compute layer: ECS cluster, ECR repos, IAM roles, ALB with routing, 4 task definitions with service discovery
- ✅ REST API Gateway with API keys directly integrated to public ALB
- ✅ Monitoring dashboard with 6 alarms configured

---

## Post-Deployment Verification Checklist

After Task 14, run these verification steps with the `sentra` profile:

```bash
# Set environment
export AWS_PROFILE=sentra
export AWS_REGION=us-east-1

# 1. Verify all stacks deployed in correct account/region
aws cloudformation list-stacks --stack-status-filter CREATE_COMPLETE --region us-east-1
aws sts get-caller-identity  # Confirm account 531109575379

# 2. Test VPC connectivity
aws ec2 describe-vpcs --filters "Name=tag:Name,Values=sentra-mvp-vpc" --region us-east-1

# 3. Verify DynamoDB tables
aws dynamodb list-tables --region us-east-1 | grep sentra

# 4. Check S3 bucket
aws s3 ls s3://sentra-mvp-artifacts/ --profile sentra

# 5. Verify ECS cluster
aws ecs list-services --cluster sentra-mvp-cluster --region us-east-1

# 6. Test API Gateway health endpoint
API_KEY=$(aws apigateway get-api-key --api-key <key-id> --include-value --query 'value' --output text --region us-east-1)
curl -H "X-API-Key: $API_KEY" https://<api-id>.execute-api.us-east-1.amazonaws.com/prod/v1/health

# 7. Check CloudWatch dashboard
aws cloudwatch get-dashboard --dashboard-name sentra-mvp-dashboard --region us-east-1
```

---

## Dependencies and Parallel Work

**Can Start Immediately**:
- Task 1 (no dependencies)

**Can Run in Parallel**:
- Tasks 5-8 (all within StorageStack, independent)
- Tasks 9-10 (different resources, can parallelize)

**Must Run Sequentially**:
- Tasks 1 → 2 → 3 → 4 (NetworkStack dependencies)
- Tasks 11 → 12 (ALB needed before ECS services)
- Task 12 → 13 (ALB DNS needed for VPC Link)
- Tasks 1-13 → 14 (MonitoringStack depends on all)

---

## Estimated Timeline

| Task | Duration | Cumulative |
|------|----------|------------|
| Task 1 | 1 day | Day 1 |
| Task 2 | 1 day | Day 2 |
| Task 3 | 0.5 day | Day 2.5 |
| Task 4 | 0.5 day | Day 3 |
| **Checkpoint 1** | 0.5 day | Day 3.5 |
| Task 5 | 0.5 day | Day 4 |
| Task 6 | 1 day | Day 5 |
| Task 7 | 1 day | Day 6 |
| Task 8 | 1 day | Day 7 |
| **Checkpoint 2** | 0.5 day | Day 7.5 |
| Task 9 | 1 day | Day 8.5 |
| Task 10 | 1 day | Day 9.5 |
| Task 11 | 1 day | Day 10.5 |
| Task 12 | 1.5 days | Day 12 |
| **Checkpoint 3** | 0.5 day | Day 12.5 |
| Task 13 | 1 day | Day 13.5 |
| Task 14 | 1 day | Day 14.5 |
| **Checkpoint 4** | 0.5 day | Day 15 |

**Total: ~15 days (3 weeks with buffer)**

---

**Next Workstream**: API Gateway Layer (LLD 02) - Start after Task 13 completion
