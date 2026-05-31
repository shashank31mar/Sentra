# Best Practices - Sentra MVP

**Project**: Sentra MVP - AI Agent Security Platform  
**Version**: 2.2  
**Last Updated**: 2026-05-20

---

## Table of Contents

1. [Code Organization](#1-code-organization)
2. [Configuration Management](#2-configuration-management)
3. [Code Reusability](#3-code-reusability)
4. [Dependency Management](#4-dependency-management)
5. [Deployment & Docker Versioning](#5-deployment--docker-versioning)
6. [Testing Standards](#6-testing-standards)
7. [Code Simplicity](#7-code-simplicity)
8. [Token Optimization](#8-token-optimization)
9. [File Size Management](#9-file-size-management)
10. [Documentation Standards](#10-documentation-standards)
11. [Cloud Account Reference](#11-cloud-account-reference)

---

## 1. Code Organization

### Principle

Keep code **modular**, **composable**, and **environment-aware**.

### Guidelines

- Each **CDK stack** in its own file:
  - `network_stack.py`, `storage_stack.py`, `compute_stack.py`, `api_stack.py`, `monitoring_stack.py`, etc.
- Create **reusable constructs** for common patterns:
  - `constructs/ecs_service_construct.py`
  - `constructs/vpc_endpoint_construct.py`
  - `constructs/security_group_construct.py`
- Separate concerns:
  - **Config** (YAML + loader)
  - **Infra** (CDK stacks & constructs)
  - **Business logic** (app code)
- Enforce **single responsibility** per class/function.

### Recommended Structure

```text
cdk/
├── app.py
├── stacks/
│   ├── network_stack.py
│   ├── storage_stack.py
│   ├── compute_stack.py
│   ├── api_stack.py
│   └── monitoring_stack.py
├── constructs/
│   ├── ecs_service_construct.py
│   ├── vpc_endpoint_construct.py
│   └── security_group_construct.py
└── config/
    ├── config.py
    └── environments/
        ├── dev.yaml
        ├── staging.yaml
        └── prod.yaml
```

**Benefits**

- Faster debugging and reviews
- Clear ownership per component
- Easy reuse across stacks and services

---

## 2. Configuration Management

### Principle

**No environment-specific values in code.** Everything configurable lives in config files.

### Never Hard Code

- AWS account IDs, regions, profiles  
- Resource names (buckets, tables, queues)  
- Policy names  
- Secrets / API keys  
- IP ranges / CIDRs  
- Environment names (`dev`, `staging`, `prod`)  
- Alert email addresses  
- Retention periods  
- Resource sizes (CPU, memory, instance types)

### Use Configuration Files

Example: `config/environments/dev.yaml`:

```yaml
environment: dev
aws:
  account_id: "531109575379"
  region: us-east-1
  profile: sentra

network:
  vpc_cidr: 10.0.0.0/16
  max_azs: 2
  nat_gateways: 1

storage:
  audit_log_retention_days: 90
  container_log_retention_days: 7
  s3_bucket_prefix: sentra-mvp

compute:
  ecs_task_cpu: 2048
  ecs_task_memory: 4096
  desired_count: 1

monitoring:
  alert_email: admin@example.com
  dashboard_name: sentra-mvp-dashboard

policies:
  session_ttl_hours: 24
  max_refund_amount: 5000
```

Example loader:

```python
# config/config.py
import os, yaml

class Config:
    def __init__(self, env: str = "dev"):
        path = os.path.join(os.path.dirname(__file__), "environments", f"{env}.yaml")
        with open(path, "r") as f:
            self._config = yaml.safe_load(f)

    @property
    def aws_account_id(self) -> str:
        return self._config["aws"]["account_id"]

    @property
    def aws_region(self) -> str:
        return self._config["aws"]["region"]

    @property
    def vpc_cidr(self) -> str:
        return self._config["network"]["vpc_cidr"]
```

**Benefits**

- Zero code changes for env switches
- Centralized, auditable configuration
- Easier compliance and rollout

---

## 3. Code Reusability

### Principle

Prefer **reuse and extension** over duplication.

### Guidelines

- Before adding new code, check existing:
  - constructs
  - helpers
  - utilities
- Extract common patterns into **constructs** or **utils**.
- Use **composition** / **inheritance** where it simplifies behavior, not where it adds complexity.
- Share common utilities across stacks (`utils/`, `cdk_constructs/`).

### Example: Reusable ECS Service Construct

```python
# constructs/ecs_service_construct.py
from aws_cdk import aws_ecs as ecs, aws_ec2 as ec2, aws_logs as logs
from constructs import Construct

class StandardEcsService(Construct):
    def __init__(
        self,
        scope: Construct,
        id: str,
        *,
        cluster: ecs.Cluster,
        vpc: ec2.Vpc,
        service_name: str,
        container_port: int,
        security_group: ec2.SecurityGroup,
        task_role,
        environment_vars: dict,
        cpu: int = 2048,
        memory: int = 4096,
        desired_count: int = 1,
    ):
        super().__init__(scope, id)

        log_group = logs.LogGroup(
            self, f"{service_name}LogGroup",
            log_group_name=f"/ecs/sentra/{service_name}",
        )

        task_def = ecs.FargateTaskDefinition(
            self, f"{service_name}TaskDef",
            cpu=cpu,
            memory_limit_mib=memory,
            task_role=task_role,
        )

        task_def.add_container(
            f"{service_name}Container",
            image=ecs.ContainerImage.from_registry("placeholder"),
            logging=ecs.LogDriver.aws_logs(stream_prefix=service_name, log_group=log_group),
            environment=environment_vars,
            port_mappings=[ecs.PortMapping(container_port=container_port)],
        )

        self.service = ecs.FargateService(
            self, f"{service_name}Service",
            cluster=cluster,
            task_definition=task_def,
            desired_count=desired_count,
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS),
            security_groups=[security_group],
        )
```

**Benefits**

- Consistent patterns across services
- One place to change shared behavior
- Less boilerplate per service

---

## 4. Dependency Management

### Principle

Dependencies must be **explicit**, **pinned**, and **per-component**.

### Guidelines

- Separate `requirements.txt` per component:
  - `cdk/requirements.txt`
  - `src/security-controller/requirements.txt`
  - `src/dashboard/requirements.txt`
  - `scripts/requirements.txt`
  - `tests/requirements.txt`
- Pin versions for production components.
- Use virtualenvs for local development.

Example structure:

```text
/Sentra/
├── cdk/
│   └── requirements.txt
├── src/
│   ├── security-controller/requirements.txt
│   ├── dashboard/requirements.txt
│   ├── customer-query-agent/requirements.txt
│   └── payment-agent/requirements.txt
├── scripts/requirements.txt
└── tests/requirements.txt
```

Example `cdk/requirements.txt`:

```txt
aws-cdk-lib==2.120.0
constructs>=10.0.0,<11.0.0
boto3==1.34.20
pyyaml==6.0.1
```

Example Dockerfile:

```dockerfile
FROM python:3.11-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
```

**Benefits**

- Reproducible builds
- No “works on my machine”
- Clean, minimal images

---

## 5. Deployment & Docker Versioning

### Principle

Deployments must be **automated**, **idempotent**, and **rollback-friendly**.  
Docker images must follow a **consistent tagging strategy**.

---

### 5.1 Automated Deployments

**DO**

- Use scripts for Docker build/tag/push and CDK deploy.
- Perform pre-flight checks:
  - AWS credentials
  - Required tools (CDK, Docker, etc.)
  - Config validation
- Make scripts idempotent and safe to re-run.

**DON’T**

- Rely on manual multi-step commands.
- Document complex one-off CLIs instead of scripting them.

Example (bad):

```bash
docker build -t sentra/security-controller:milestone-1 .
docker tag sentra/security-controller:milestone-1 123456789012.dkr.ecr.us-east-1.amazonaws.com/sentra/security-controller:milestone-1
aws ecr get-login-password | docker login --username AWS --password-stdin 123456789012.dkr.ecr.us-east-1.amazonaws.com
docker push 123456789012.dkr.ecr.us-east-1.amazonaws.com/sentra/security-controller:milestone-1
```

Example (good):

```bash
python scripts/build_and_push_image.py --service security-controller --milestone 1
```

---

### 5.2 Docker Image Versioning

**Use the script; don't tag manually.**

```bash
# Deploy milestone 1
python scripts/build_and_push_image.py --service security-controller --milestone 1

# Deploy milestone 2
python scripts/build_and_push_image.py --service security-controller --milestone 2

# Rollback to milestone 1
python scripts/build_and_push_image.py --service security-controller --milestone 1 --force
```

The script:

- Creates immutable tag: `sentra/<service>:milestone-N`
- Updates `:latest` for ECS
- Validates:
  - Milestone not duplicated (unless `--force`)
  - AWS credentials
  - Dockerfile presence
  - Push success

**Rules**

- ✅ Use monotonic milestones: `1, 2, 3, …`
- ✅ Use `--force` only for rollback
- ❌ Don’t manually tag or push images
- ❌ Don’t reuse milestone numbers casually
- ❌ Don’t invent ad-hoc tags

---

### 5.3 Rollback & Safety

- Use CDK `RemovalPolicy.RETAIN` for critical data (logs, prod tables).
- Use `RemovalPolicy.DESTROY` only for non-critical/demo resources.
- Keep rollback as simple as:
  - Re-tagging to previous milestone (`--force`)
  - Re-running deployment

**Benefits**

- Predictable version history
- One clear rollback path
- Less room for human error

---

## 6. Testing Standards

### Principle

Everything shippable must be **testable** and **tested**.

### Guidelines

- Add unit tests for:
  - CDK stacks (resource counts, critical properties)
  - Core application logic (policy engine, security logic, etc.)
- Aim for **>80% coverage** on core components.
- Use `pytest` + `pytest-cov` + `moto` for AWS mocking.

Example CDK test:

```python
from aws_cdk import App, Environment
from aws_cdk.assertions import Template
from stacks.network_stack import NetworkStack

def test_vpc_created():
    app = App()
    stack = NetworkStack(app, "TestNetworkStack", env=Environment(account="123", region="us-east-1"))
    template = Template.from_stack(stack)
    template.resource_count_is("AWS::EC2::VPC", 1)
```

Example app test:

```python
from src.security_controller.policy_engine import PolicyEngine

def test_refund_limit_policy():
    engine = PolicyEngine()
    result = engine.evaluate({"tool_name": "process_refund", "parameters": {"amount": 10000}})
    assert result.decision == "DENY"
```

**Benefits**

- Safe refactors
- Faster debugging
- Tests double as usage docs

---

## 7. Code Simplicity

### Principle

**Simple > clever.** Favor readability over “smart” one-liners.

### Guidelines

- Use descriptive names.
- Keep functions focused (ideally < 50 lines).
- Prefer early returns over deep nesting.
- Only comment where intent isn’t obvious; otherwise make the code self-expressive.

Example (bad):

```python
def process_request(r):
    return {"decision": "DENY" if any(
        p['condition'](r) and p['action'] == 'deny'
        for p in [eval(compile(open(f).read(), f, 'exec')) for f in glob('policies/*.py')]
    ) else "ALLOW"}
```

Example (good):

```python
def process_request(request: dict) -> dict:
    policies = load_policies_from_directory("policies/")
    for policy in policies:
        if policy.matches(request) and policy.action == "deny":
            return {
                "decision": "DENY",
                "reason": policy.reason,
                "matched_policy": policy.name,
            }
    return {"decision": "ALLOW", "reason": "No deny policies matched"}
```

**Benefits**

- Easier onboarding
- Faster reviews
- Fewer subtle bugs

---

## 8. Token Optimization

### Principle

Minimize token usage by **avoiding large inline outputs**. Use files instead.

### Permissions Context

Claude / Kiro has:

1. AWS CLI access (read/write)
2. Read/write `/tmp`
3. Command execution (bash, AWS CLI, CDK, etc.)
4. File operations under `/tmp` and `security-mvp` project folder

### Best Practices

- ✅ Redirect large outputs to files in `/tmp`
- ✅ Let the IDE show updated files instead of dumping contents
- ✅ Use `grep`, `head`, `tail` to show only relevant snippets
- ❌ Don’t print full `cdk synth`, `pytest -v`, or long logs into chat

Examples (bad):

```bash
cdk synth --profile sentra
pytest tests/ -v
aws logs tail /sentra/audit-logs --follow
```

Examples (good):

```bash
cdk synth --profile sentra > /tmp/cdk_synth_output.txt
grep -i "error" /tmp/cdk_synth_output.txt

pytest tests/ -v > /tmp/test_output.txt
grep -i "FAILED" /tmp/test_output.txt || echo "All tests passed"

aws logs tail /sentra/audit-logs --since 1h > /tmp/audit_logs.txt
grep "DENY" /tmp/audit_logs.txt | wc -l
```

**Benefits**

- Huge token savings on long operations
- Persistent logs for deeper debugging
- Cleaner, more focused chat

---

## 9. File Size Management

### Principle

Aim for **500–700 lines per file**. Larger files should be justified and well-structured.

### When to Split

Split when:

- A file has **multiple responsibilities**
- There is **duplicated logic** that could live in `utils/` or `constructs/`
- Helpers could be reused by other stacks/services
- The file is hard to navigate or review in one pass

How to split:

- Extract utilities to `utils/<domain>_helpers.py`
- Extract shared infra to `cdk_constructs/` or `constructs/`
- Split monolithic stacks into:
  - `api_gateway_stack.py`
  - `api_auth_stack.py`
  - `api_monitoring_stack.py`

**Acceptable big files**

- Single, well-structured CDK stack
- Comprehensive test files
- Generated code / schemas

**Benefits**

- Faster reviews and navigation
- Clear separation of concerns
- More reuse opportunities

---

## 10. Documentation Standards

### Principle

Use **existing docs as the source of truth**. Avoid file proliferation.

### Guidelines

- ❌ DON’T create:
  - `MILESTONE-X-COMPLETE.md`
  - `TASK-SUMMARY.md`
  - Per-task summary markdown files
- ✅ DO:
  - Update `workstream-X.md` with milestone/task status
  - Update existing `README.md` with new features/changes
  - Use chat for short completion summaries

Example – bad:

```bash
touch MILESTONE-3-COMPLETE.md
touch FEATURE-X-SUMMARY.md
touch DEPLOYMENT-NOTES.md
```

Example – good (`workstream-4-dashboard.md`):

```markdown
## 11. Cloud Account Reference

### Principle

Cloud account identifiers (AWS Account ID, Azure Subscription ID, GCP Project ID) are **not secrets** — they are identifiers, like email addresses. They are safe to commit to the repo. Credentials (access keys, service principal secrets, JSON keyfiles) **must never** be committed; those live in cloud-native secret stores (AWS Secrets Manager, Azure Key Vault, GCP Secret Manager) and are referenced by name only.

This section is the single source of truth for "which cloud account is which environment." Update here whenever a new account is provisioned.

### AWS

| Field | Value |
|---|---|
| Account ID | `531109575379` |
| Default Profile | `sentra` (configured in `~/.aws/credentials`) |
| Default Region | `us-east-1` (Northern Virginia) |
| Environment | Dev / Demo (production not yet provisioned) |
| IaC | AWS CDK — see [Sentra/cdk/](cdk/) |

```bash
# Standard env setup
export AWS_PROFILE=sentra
export AWS_REGION=us-east-1
export CDK_DEFAULT_ACCOUNT=531109575379
export CDK_DEFAULT_REGION=us-east-1
```

**Credential refresh** (Isengard / federated, short-lived session tokens):

```bash
# Refresh credentials for the sentra profile (run when aws sts fails with
# InvalidClientTokenId or TokenExpired). Uses Amazon-internal `ada` tool.
ada cred update --once --profile sentra

# Verify
aws sts get-caller-identity --profile sentra
```

Session tokens typically last ~12 hours. The `ASIA…` access-key prefix in `~/.aws/credentials` indicates a temporary session credential (not a long-lived access key). When any AWS CLI command returns `InvalidClientTokenId`, `ExpiredToken`, or `TokenExpired`, re-run the `ada` refresh above.

### Azure

| Field | Value |
|---|---|
| Subscription ID | `cb2512df-2001-45e1-aea6-88e80fc00299` |
| Subscription Type | Free Trial ($200 credit / 30 days from creation) |
| Default Region | `centralus` (switched 2026-05-23 from `eastus2`) — see [region history](#azure-region-history) below |
| Environment | Dev / Demo only — torn down post-recording per [Workstream 15 Task 6.4](tasks/workstream-15-cross-cloud-demo.md) |
| IaC | Bicep — see [Sentra/infrastructure/azure/bicep/](infrastructure/azure/bicep/) (to be created in Workstream 15 Milestone 3) |

```bash
# Standard env setup
az login
az account set --subscription "cb2512df-2001-45e1-aea6-88e80fc00299"

# DO NOT set a default RG via `az configure --defaults group=...` — multiple
# RGs exist (one per azd env: aegionai-ws15-m3-rg, future demo RGs) and stale
# defaults silently break unrelated `az` commands. Always pass `-g <rg>` explicitly.
# Default location is fine since it's just a UX shortcut for `--location`.
az configure --defaults location=centralus
```

### Azure region history

Two-step migration, captured here so the next person doesn't repeat the mistakes:

1. **2026-05-19 — picked `eastus2`**: gpt-4o-mini quota present (200 RPM on Free Trial); `eastus` had zero. Region pairing to AWS `us-east-1` gave ~10-20ms cross-cloud latency.
2. **2026-05-23 — moved to `centralus`**: even after upgrading Free Trial → PAYG, the App Service Plan Y1 (Linux Consumption) quota in eastus2 was still 0 — PAYG quota propagation for Y1 in eastus2 has documented lag (hours). centralus had the quota immediately. Cross-cloud latency to `us-east-1` is ~35ms — still well inside the LLD 15 §12 `p95 ≤120ms` budget. gpt-4o-mini is also available in centralus (verified via `az cognitiveservices model list -l centralus`).

If a future Azure rollout hits the same "Total VMs: 0" error in eastus2, the right move is to **switch region** (centralus, canadacentral, northcentralus all work), not wait for propagation — Microsoft does not commit a propagation SLA for this quota allocation.

### Azure Functions deploy hard-won rules (lessons learned WS15 M3, 2026-05-23)

These apply specifically to Python Function Apps on Linux App Service Plans, deployed via `azd`. Skip these and lose hours.

**1. Use B1 Basic, not Y1 Consumption, on new PAYG subscriptions.** Y1 in `eastus2` had 0 worker quota (PAYG propagation lag). Y1 in `centralus` had a different bug: workers never scaled past 0 even with traffic (scale-controller deadlock; only diagnosable via Portal "Diagnose and solve problems" → "Function App Down" → "Functions that are not triggering" detector). **B1 Basic Linux (~$13/mo flat, always-on) just works**, and `azd down` between demos still zeros the bill.

**2. Storage account must have `allowSharedKeyAccess: true`.** Microsoft defaulted it to false in late 2024. Function host uses shared-key auth for `AzureWebJobsStorage` → silently rejected if false → host can't start → 503 with zero App Insights traces. Set explicitly in storage Bicep:
```bicep
properties: {
  allowSharedKeyAccess: true
}
```

**3. Python v2 model needs `AzureWebJobsFeatureFlags=EnableWorkerIndexing`.** Without it, host indexes 0 functions, every route returns 404. Set in Function App `appSettings`.

**4. `azd deploy` does NOT trigger Oryx Remote Build on B1 Linux**, even with `SCM_DO_BUILD_DURING_DEPLOYMENT=1` and `ENABLE_ORYX_BUILD=true`. azd uses OneDeploy which bypasses Oryx. This means **`pip install` of `requirements.txt` does not run server-side**. Two workarounds:
   - ✅ **Preferred for this project**: use Python stdlib (`urllib.request` instead of `requests`, etc.) so `requirements.txt` only needs `azure-functions` (which is built into the runtime).
   - 🔲 **If you must use external deps**: add a `prepackage` hook in `azure.yaml` to pre-install before zip:
     ```yaml
     services:
       <service-name>:
         hooks:
           prepackage:
             shell: sh
             run: pip install --target=.python_packages/lib/site-packages -r requirements.txt
     ```

**5. `Microsoft.CognitiveServices` regional SKUs vary.** `gpt-4o-mini 2024-07-18` does NOT support `Standard` SKU in `centralus`; use `GlobalStandard` (same pricing, cross-region pool). Source of truth: `az cognitiveservices model list -l <region>` filtered by `model.name=='gpt-4o-mini'`.

**6. Don't set `az configure --defaults group=...`** to a specific RG. Multiple RGs may exist (per azd env), and a stale default silently breaks unrelated `az` commands. Always pass `-g <rg>` explicitly.

### Azure production-hardening backlog (deferred — demo-and-tear-down is fine; revisit before any customer pilot)

These are knowingly accepted trade-offs for the seed-raise demo. Promote each to a P0 before a real customer deploys against this stack.

1. **Function App storage auth — move to Managed Identity (keyless).** Today `function_app.bicep` injects `storageAccount.listKeys()` directly into `AzureWebJobsStorage`, which means the storage key shows up in plaintext in the Function App's Configuration blade. The Linux-Functions recommended pattern is `AzureWebJobsStorage__accountName` + Managed Identity (no key in env at all). Will let us drop `allowSharedKeyAccess: true` on the storage account as well. (Kiro M4 review Issue #2)
2. **Sentra API key rotation must restart the Function App.** `_sentra_api_key` is captured at module import, so rotating the Key Vault secret without a restart leaves the Function using the old value. When we switch to `@Microsoft.KeyVault(...)` connectionString references (recommended alongside #1 above), the Function App auto-restarts on secret-version change. Today's plaintext-in-appSettings doesn't. (Kiro M4 review Issue #8)
3. **Function App `x-functions-key` or MI inbound auth.** Today `/api/tool/*` is `AuthLevel.ANONYMOUS`. Acceptable behind the demo's API-Gateway + Usage-Plan boundary, but a real customer deployment must gate the Function so no internet caller can burn budget or pollute the audit log. (Tracked in `azure_connector.py` Issue #17 TODO.)

**Operational notes:**

- ~~Free Trial credit expires 30 days after subscription creation. After expiry, subscription becomes inactive unless explicitly upgraded to Pay-As-You-Go.~~ Resolved 2026-05-23: subscription upgraded to PAYG (MicrosoftCustomerAgreement). The original Free Trial credit carries over until depleted; subsequent usage bills monthly to the PAYG account. Budget alert set at $50/month via Azure Portal.
- Strategy is **demo-and-tear-down**: provision resources via Bicep + `azd up` / `azd down`, record investor demo, then tear down. Bicep IaC in git is the durable provisioning source.
- **IaC tooling**: prefer **`azd` (Azure Developer CLI)** over a custom bash deploy script. `azd up` provisions, `azd down` tears down, `azd env new <name>` supports multiple environments. Install via `brew install azd`. Built on Bicep so our IaC stays declarative.
- Required resource providers must be registered (one-time setup per subscription). **Missing any of these causes confusing failures** — e.g., `Microsoft.Compute` not registered makes `az vm list-usage` return zero entries, which looks like "Free Trial has zero VM quota" but is actually "the provider is just not registered" (lesson learned 2026-05-23):
  ```bash
  az provider register --namespace Microsoft.CognitiveServices --wait
  az provider register --namespace Microsoft.MachineLearningServices --wait
  az provider register --namespace Microsoft.Web --wait
  az provider register --namespace Microsoft.KeyVault --wait
  az provider register --namespace Microsoft.Storage --wait
  az provider register --namespace Microsoft.Compute --wait    # required for Function App Y1 plan (App Service Plan consumes VM quota)
  az provider register --namespace Microsoft.Insights --wait   # required for Application Insights
  az provider register --namespace Microsoft.OperationalInsights --wait  # required by Application Insights backend (Log Analytics)
  ```
  Verify all are `Registered` before any `azd up`:
  ```bash
  for ns in Microsoft.CognitiveServices Microsoft.MachineLearningServices Microsoft.Web Microsoft.KeyVault Microsoft.Storage Microsoft.Compute Microsoft.Insights Microsoft.OperationalInsights; do
    echo "$ns: $(az provider show --namespace $ns --query 'registrationState' -o tsv)"
  done
  ```

### GCP

| Field | Value |
|---|---|
| Project ID | _To be provisioned in Workstream 15 Phase 2 (Vertex AI fast-follow)_ |
| Region | TBD (likely `us-central1`) |
| IaC | Terraform (no GCP-native CDK/Bicep equivalent) |

---

## 12. Validation Signal Store (Workstream 17 / LLD 17)

### Principle

Per-validator decisions go to **DynamoDB** for fast read; CloudWatch Logs remains the **compliance archive**. Reads inside the 90-day retention window come from DDB (single-digit-ms p95). Reads outside that window — or any cross-cutting compliance query — come from CloudWatch via `/v1/logs`.

### Resources

| Field | Value |
|---|---|
| DDB table | `sentra-validation-signals` |
| PK | `session_id` (S) |
| SK | `request_id#timestamp_ms#source` (S) |
| GSI 1 | `agent-timestamp-index` — PK=`agent_id` (S), SK=`timestamp_ms` (N) |
| GSI 2 | `decision-date-timestamp-index` — PK=`decision_date` (S, `YYYY-MM-DD`), SK=`timestamp_ms` (N). `decision_date` is a real stored attribute, writer-populated. |
| TTL attribute | `expires_at` (epoch seconds, 90 days from write) |
| Removal policy | `RETAIN` |
| Region | `us-east-1` |

CDK construct: `cdk/cdk_constructs/signal_store_table_construct.py`. Instantiated inline in `storage_stack.py` (search for `ValidationSignalStore`). IAM grants on the controller task role live in `compute_stack.py`.

### When to use which read path

| Use case | Path |
|---|---|
| Dashboard's per-step "By" column / signal expander (recent — within minutes) | `GET /v1/sessions/{id}/decisions` (DDB) |
| Per-session timeline within 90 days | `GET /v1/sessions/{id}/decisions` or `/signals` (DDB) |
| Cross-session paginated scan (last 24h, last week) | `GET /v1/decisions` (DDB GSI 2) |
| Compliance audit ("all DENYs in May 2026") | `GET /v1/logs` (CloudWatch Insights) — slow, but the source of truth |
| Session older than 90 days (past DDB TTL) | `GET /v1/logs` (CloudWatch) — the only place that still has it |

The 60s+ CloudWatch Insights indexing lag (LLD 17 §2) is why the dashboard's runner uses `/v1/sessions/{id}/decisions`, NOT `/v1/logs`. Any new dashboard panel showing audit data within 5 minutes of a validation MUST use the DDB endpoint or it'll race the indexing pipeline.

### DDB-vs-CloudWatch reconciliation rule

Within 5 min of the validation: trust DDB. Beyond 5 min but ≤ 90 days: DDB and CloudWatch must agree; if they don't, log a discrepancy (`controller.discrepancy` group) and investigate. Beyond 90 days: CloudWatch is the only record.

If a regulator query hits a window where DDB shows data but CloudWatch doesn't (rare — "DDB succeeded, CloudWatch failed"), CloudWatch is canonical for compliance — escalate.

### Cost model

DDB on-demand at ~1000 validations/day × 6 signals × 90 days ≈ 540k items + 2 GSIs. Monthly cost ≈ $1.16. Even at 10× MVP traffic the line item is rounding error. The case for DDB over CloudWatch Insights isn't cost — it's read latency.

### Operational gotchas

1. **Timestamp format is locked**: `YYYY-MM-DDTHH:MM:SS.sssZ` (ISO 8601 with milliseconds, always Z). The writer asserts canonical format; any drift breaks SK lexical sort. Use `_isoformat_ms_z()` helper in `signal_store_writer.py` for any new writer.
2. **`decision_date` is stored, not derived**: GSI 2 projects from a real attribute. The writer computes `timestamp_iso[:10]` at write time — missing it silently drops the row from the GSI.
3. **request_id correlation**: connectors generate it, thread it through (Bedrock `sessionAttributes`, Azure HTTP body), Lambda + Function App echo it into `/v1/validate`. Any new connector must follow the same pattern or its edge signals won't group with Sentra's signals on read.
4. **200ms write timeout**: budgeted to protect `/v1/validate` tail latency. From inside AWS the warm path is ~5-15ms; the timeout is a safety net for DDB regional issues.
5. **CloudWatch dual-write is NOT optional**: removing it would break compliance audits and the >90d query path. The `cloudwatch_dual_write: true` config is meant for tests only.

### Don't

- Don't query `/v1/logs` for the dashboard's hot path. It's slow (CloudWatch Insights) and may not return fresh writes for 60s.
- Don't write to DDB directly from outside the controller — go through `POST /v1/sessions/{id}/signals` so the taxonomy validation and shared-attr propagation are applied uniformly.
- Don't add new validators without stamping a `Source.*` taxonomy entry and a default priority. See LLD 17 §4 + `app/combiners/sources.py`.

---

## Milestone 3: Overview Tab API Integration ✅ COMPLETE
**Status:** ✅ Complete (November 20, 2025)

### Tasks
- [x] 3.1 Create Security Controller client
- [x] 3.2 Create CloudWatch Logs client
...
```

**Chat summary format** (3–5 sentences max):

- What was accomplished
- Files created/modified
- Key behaviors implemented
- Next steps (if any)

---

## Summary Checklist

Before committing:

- [ ] **Modularity** – Focused stacks/constructs/utils
- [ ] **No hard-coded env values** – All in config
- [ ] **Reuse** – Constructs/utils used where applicable
- [ ] **Dependencies** – Added to correct `requirements.txt`
- [ ] **Deployment** – Scripted, safe, rollback-ready
- [ ] **Tests** – Added and passing (>80% where required)
- [ ] **Simplicity** – Clear, readable code
- [ ] **Token usage** – Large outputs redirected to files
- [ ] **File size** – Reasonable; split if too large
- [ ] **Docs** – Updated existing files; no extra summary files

**Status**: Active – Reference during development  
**Next Review**: After Milestone 1 completion


### 8.1 Token Optimization While Actively Working on Tasks

When collaborating with the AI during development, follow these rules to minimize token usage, keep interactions efficient, and avoid unnecessary context bloating.

#### Core Principles
- **DO NOT** paste full file contents unless explicitly needed.
- **DO** request *diff-based edits*.
- **DO** let the assistant open/read files instead of pasting them.
- **DO** use `/tmp` or project files for large outputs.
- **DON’T** ask: “Show me the full updated file.”
- **DO** keep the conversation scoped to the active task.
- **DO** minimize re-sending large specifications; place them in project files.

#### Examples of Token-Efficient Development Workflows

##### Good: diff-based editing
"Open api_stack.py and add a new POST /validate endpoint under the v1 resource. Show only the added code block."

##### Good: referencing existing context
"Use the same pattern as the refund policy but create a new profile_update policy. Only show the new class."

##### Good: using /tmp for long outputs
pytest tests/unit/ -v > /tmp/test_output.txt  
"Search for failures in /tmp/test_output.txt and summarize only the failing tests."

##### Good: scoped requests
"In network_stack.py, only show me the IAM role section."

##### Bad: asking for the full file
"Show me the full compute_stack.py"

##### Good: compressed summaries
"Summarize what changed in api_stack.py after the last modification in 5 sentences."

##### Good: incremental context
"We finished step 2; proceed to step 3 without restating earlier steps."

##### Good: checkpoint summaries
"Summarize key decisions in 5 bullet points."

#### General Rule
The assistant should operate like a developer with repo access — keep interactions minimal, scoped, and diff-focused.



### 8.2 Prefer IDE Diff View Instead of Terminal Output

When modifying code, always prefer using the IDE’s built-in **diff viewer** rather than showing full diffs or file contents in the terminal/chat.

#### Why This Matters
- Terminal diffs are often 50–500+ lines → **large token usage**.
- IDE diff view shows context-rich changes without sending text to the model.
- Reduces noise in the chat thread.
- Keeps the assistant focused on logic instead of reprocessing large pasted diffs.

#### Best Practices
- ❌ DON’T: Print long `git diff` outputs in chat.
- ❌ DON’T: Paste “before vs after” file contents.
- ❌ DON’T: Ask the assistant to regenerate entire files just to see the diff.

- ✅ DO: Ask the assistant to modify the file internally and use the Kiro IDE’s diff UI.
- ✅ DO: Request *only the changed block* if you must see it in chat.
- ✅ DO: Keep edits small, incremental, and diff-based.

#### Examples

##### ❌ Bad (token-heavy)
```
Show me the full diff of compute_stack.py after your changes.
```

##### ✔ Good (token-efficient)
```
Apply the update to compute_stack.py.
Show only the 10–15 line diff or the exact code block you changed.
```

##### ✔ Best
```
Apply the update.
I'll review the diff in the IDE — no need to show it here.
```

#### Result
Using the IDE diff view instead of dumping full diffs into the chat typically saves:

- **500–4000 tokens per edit** for CDK stack files
- **200–800 tokens per edit** for Python modules
- **1,000–10,000 tokens** per session on multi-step tasks

---

## 14. ML Threat Classifier (Workstream 19 / LLD 19)

### Principle

The ML threat classifier is **layered defense, not replacement**. Sigma and the policy engine remain the deterministic backstop; ML adds semantic-threat detection on top. When in doubt about an operational change, default to *flag off* — sigma + policy alone are the v0.1 contract.

### Resources

| Field | Value |
|---|---|
| Validator class | `MLClassifierValidator` in [src/security-controller/app/validators/ml_classifier.py](src/security-controller/app/validators/ml_classifier.py) |
| Pipeline slot | STEP 3.5 (after sigma, before context) in [validation_service.py](src/security-controller/app/services/validation_service.py) |
| Source taxonomy | `Source.SENTRA_ML_CLASSIFIER = "sentra.ml_classifier"` (LLD 17 §4, priority 70) |
| Inference profile | `aegionai-ml-classifier` Application Inference Profile (LLD 19 §2.4); ARN piped via `ML_CLASSIFIER_INFERENCE_PROFILE_ARN` env var |
| Hot model | Haiku 4.5 (`anthropic.claude-haiku-4-5-20251001-v1:0`) |
| Escalation model | Sonnet 4.6 (`anthropic.claude-sonnet-4-6-v1:0`) — borderline confidence band only |
| Tests | `tests/test_ml_classifier.py` (unit, mocked Bedrock), `tests/test_ml_classifier_bedrock.py` (integration, gated on `RUN_INTEGRATION=1`) |
| User docs | [docs/sentra-ml-classifier.md](docs/sentra-ml-classifier.md) |

### Operational gotchas

1. **`ML_CLASSIFIER_INFERENCE_PROFILE_ARN` MUST point at the dedicated profile** (default in `compute_stack.py` does this correctly). Routing the validator through any other profile or directly at a foundation model defeats the workload-isolation lever from LLD 19 §2.4 and merges its quota / cost / CloudWatch metrics with whatever other workload shares that target.

2. **Haiku 4.5, not Haiku 3.5.** The codebase's fallback LLM response generator ([src/common/llm_response_generator.py](src/common/llm_response_generator.py)) uses Haiku 3.5. The ML classifier must NOT share that quota bucket; IAM in `compute_stack.py` explicitly scopes the validator to haiku-4-5 ARNs only. If a future change broadens that grant, the isolation guarantee weakens.

3. **Sequential pipeline, NOT parallel.** LLD 19 v0.3 §3.2 corrected the earlier parallel-gather claim. The validator runs sequentially after sigma; sigma DENYs short-circuit before ML pays its ~600ms Bedrock RTT. A true parallel-gather refactor is tracked as a separate cross-cutting workstream; do NOT add `asyncio.gather` to `_run_validation_pipeline` in a WS19 PR.

4. **ABSTAIN ≠ ALLOW.** `ValidationResult.abstain(reason)` returns `decision=None`. `_capture` filters None signals out of the audit log (LLD 17 §4 absence semantics). Any new validator emitting ABSTAIN MUST also set `should_deny=False` and let `to_signal()` return None — never raise.

5. **Shadow mode is a separate flag.** `ML_CLASSIFIER_ENABLED=true` runs the validator and lets it influence the verdict. `ML_CLASSIFIER_ENABLED=true + ML_CLASSIFIER_SHADOW_MODE=true` runs it and records the signal but DOES NOT short-circuit on its DENY. Always pass through shadow mode for ≥50 novel inputs before flipping shadow off.

6. **`asyncio.to_thread` is required for the Bedrock call.** The validator's `_invoke` wraps the sync boto3 client in `asyncio.to_thread` so the ~600ms RTT doesn't block the event loop. Without it, the controller can only run one validation in flight at a time. The threads themselves are not interruptible — the `botocore.Config(read_timeout=...)` is what actually aborts the HTTP socket when `asyncio.wait_for` cancels.

7. **`CfnApplicationInferenceProfile` is NOT in aws-cdk-lib 2.114.1.** The pinned CDK version predates the typed Bedrock construct. `compute_stack.py` uses the `CfnResource` escape hatch with `type="AWS::Bedrock::ApplicationInferenceProfile"`. When aws-cdk-lib is upgraded (>=2.150), this can become the typed construct; the synthesized CloudFormation is identical.

8. **`ModelSource.CopyFrom` MUST be a system inference profile ARN, not a foundation-model ARN.** Haiku 4.5 does not support on-demand invocation. If `CopyFrom` is `arn:aws:bedrock:REGION::foundation-model/anthropic.claude-haiku-4-5-...`, both the direct Bedrock API and the CFN resource provider return `"The provided foundation model does not support On Demand inference"`. CDK surfaces this as a generic `AWS::EarlyValidation::PropertyValidation` failure that points at the AIP resource without naming the underlying cause. Use `arn:aws:bedrock:REGION:ACCOUNT:inference-profile/us.anthropic.claude-haiku-4-5-...` (the cross-region system profile ARN).

9. **CFN `PropertyValidation` failures don't tell you which property is wrong.** When `cdk deploy` returns `The following hook(s)/validation failed: [AWS::EarlyValidation::PropertyValidation]`, the message is generic. To isolate: extract the offending resource from the synthesized template, create a minimal standalone CFN stack with just that resource, and `aws cloudformation create-stack` it. The standalone stack's events will surface the real error. This is faster than guessing.

### Eval harness + CI gate

[scripts/eval_ml_classifier.py](scripts/eval_ml_classifier.py) runs a labeled dataset through the validator and reports precision / recall / F1 / latency / cost. Thresholds in [scripts/eval_thresholds.yaml](scripts/eval_thresholds.yaml). The GitHub workflow [.github/workflows/eval-ml-classifier.yml](.github/workflows/eval-ml-classifier.yml) runs the eval on every PR that touches `ml_classifier.py` / `ml_classifier_prompts.py` / `ml_classifier_schema.py` and blocks merge if thresholds fail.

Dataset construction is in two scripts:

- [scripts/extract_ml_eval_dataset.py](scripts/extract_ml_eval_dataset.py) — labels from the audit log (sigma DENY → positive with that `threat_type`; trusted ALLOW → negative). Held-out split by `session_id`, NOT by row.
- [scripts/generate_adversarial_dataset.py](scripts/generate_adversarial_dataset.py) — synthetic adversarial examples generated by Opus, ~60 per category. Output includes a `*.review.csv` the founder fills before the dataset becomes ground truth — model-generated labels are NOT trustworthy on their own.

### Don't

- Don't enable `ML_CLASSIFIER_ENABLED=true` in customer prod without first passing through shadow mode + observing ≥50 novel inputs (per [compare_shadow_verdicts.py](scripts/compare_shadow_verdicts.py)'s M3 exit gate).
- Don't reuse Haiku 3.5 as the hot model. The isolation contract relies on the version split.
- Don't add a Bedrock Guardrail to the validator's inference profile. The validator IS the threat detector; wrapping it in a guardrail is circular and adds 50-100ms.
- Don't tune `ML_CONFIDENCE_*` thresholds without re-running the eval harness — those defaults are intuitive, not measured.
- Don't bypass `_capture` when adding a new validator that can ABSTAIN — that's where `is_abstain` filtering happens, and a None signal in the audit log will choke `BatchWriteItem` downstream.
