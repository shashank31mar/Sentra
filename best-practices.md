# Best Practices - Sentra MVP

**Project**: Sentra MVP - AI Agent Security Platform  
**Version**: 2.1  
**Last Updated**: November 20, 2025

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
