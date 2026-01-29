# CDK Stack Naming Convention

## Overview

All Sentra CDK stacks follow a standardized naming convention for easy identification and management.

## Naming Pattern

```
Sentra-{ENVIRONMENT}-{Component}-Stack
```

### Components

| Component | Purpose | Stack Name |
|-----------|---------|------------|
| Network | VPC, Subnets, NAT Gateway, Route53, Security Groups, VPC Endpoints | `Sentra-DEV-Network-Stack` |
| Storage | CloudWatch Logs, DynamoDB Tables, S3 Buckets | `Sentra-DEV-Storage-Stack` |
| Compute | ECS Cluster, ECR, Task Definitions, Services, ALB | `Sentra-DEV-Compute-Stack` |
| API | API Gateway, VPC Link, Custom Domain | `Sentra-DEV-API-Stack` |
| Monitoring | CloudWatch Dashboard, Alarms, SNS Topics | `Sentra-DEV-Monitoring-Stack` |

### Environments

| Environment | Prefix | Example |
|-------------|--------|---------|
| Development | `DEV` | `Sentra-DEV-Network-Stack` |
| Staging | `STAGING` | `Sentra-STAGING-Network-Stack` |
| Production | `PROD` | `Sentra-PROD-Network-Stack` |

## Benefits

1. **Easy Identification**: Instantly recognize Sentra stacks in AWS Console
2. **Environment Isolation**: Clear separation between dev/staging/prod
3. **Component Grouping**: All related resources grouped by component
4. **Cost Tracking**: Easy to filter costs by environment or component
5. **Cleanup Simplicity**: Simple grep patterns for cleanup scripts

## Usage in Code

The stack naming is implemented in `app.py`:

```python
# Stack naming convention: Sentra-<Environment>-<Component>-Stack
environment = os.getenv("ENVIRONMENT", "dev")
stack_prefix = f"Sentra-{environment.upper()}"

# Create stacks with consistent naming
network_stack = NetworkStack(
    app,
    f"{stack_prefix}-Network-Stack",
    config=config,
    env=env,
)
```

## CloudFormation Stack Outputs

All stacks export outputs with the same naming pattern:

```
Sentra-{ENVIRONMENT}-{Component}-{Resource}

Examples:
- Sentra-DEV-Network-VpcId
- Sentra-DEV-Network-PrivateSubnetIds
- Sentra-DEV-Storage-AuditLogGroupName
- Sentra-DEV-Compute-ClusterArn
```

## Tags

All resources are tagged with:

```yaml
Project: Sentra
Environment: dev
ManagedBy: CDK
Owner: Sentra-Team
Component: Network  # varies by stack
```

## AWS Console Filtering

**Filter by Project:**
```
tag:Project = Sentra
```

**Filter by Environment:**
```
tag:Environment = dev
```

**Filter by Component:**
```
tag:Component = Network
```

## Cost Allocation Tags

Enable these tags in AWS Cost Allocation Tags:
- `Project`
- `Environment`
- `Component`
- `ManagedBy`

This allows cost reporting by:
- Total Sentra project costs
- Dev vs Prod environment costs
- Network vs Compute component costs

## Cleanup

The standardized naming makes cleanup scripts simple:

```bash
# Find all Sentra stacks
aws cloudformation list-stacks | grep Sentra

# Find all Sentra resources
aws ec2 describe-vpcs --filters "Name=tag:Project,Values=Sentra"

# Destroy all dev environment stacks
cdk destroy Sentra-DEV-*
```

## Migration from Old Names

If you deployed with old stack names (e.g., `SentraNetworkStack`), you need to:

1. **Destroy old stack:**
   ```bash
   cdk destroy SentraNetworkStack
   ```

2. **Deploy with new name:**
   ```bash
   cdk deploy Sentra-DEV-Network-Stack
   ```

**Note**: This will cause downtime. Plan accordingly.

## Reserved Stack Names

The following stack names are reserved by CDK:

- `CDKToolkit` - CDK bootstrap stack (do not modify)
- `CDKMetadata` - CDK metadata resources

## Best Practices

1. ✅ Always use the naming convention for new stacks
2. ✅ Include environment in stack name
3. ✅ Use descriptive component names
4. ✅ Apply consistent tags to all resources
5. ❌ Don't use generic names like "Stack1" or "MyStack"
6. ❌ Don't hardcode stack names in code
7. ❌ Don't change stack names in production (causes replacement)
