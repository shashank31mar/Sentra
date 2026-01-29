# Sentra MVP - CDK Infrastructure

This directory contains the AWS CDK infrastructure code for the Sentra MVP.

## Project Structure

```
cdk/
├── app.py                     # CDK app entry point
├── cdk.json                   # CDK configuration
├── requirements.txt           # Python dependencies
├── config/
│   └── dev.yaml              # Environment-specific configuration
├── stacks/
│   ├── __init__.py
│   └── network_stack.py      # VPC, subnets, NAT gateway, VPC flow logs
└── README.md                  # This file
```

## Prerequisites

1. **AWS CLI** configured with `sentra` profile
2. **Node.js** (for AWS CDK CLI)
3. **Python 3.11+** with virtual environment
4. **AWS CDK CLI** installed globally

## Setup

### 1. Install Dependencies

Run the setup script from the project root:

```bash
./scripts/setup_cdk.sh
```

This will:
- Activate the virtual environment
- Install all Python dependencies
- Verify CDK CLI installation

### 2. Configure AWS Profile

```bash
export AWS_PROFILE=sentra
export AWS_REGION=us-east-1

# Verify configuration
aws sts get-caller-identity
```

Expected output should show account `531109575379`.

### 3. Bootstrap CDK (First Time Only)

```bash
cd cdk
cdk bootstrap aws://531109575379/us-east-1
```

## Usage

### Synthesize CloudFormation Templates

```bash
cd cdk
export AWS_PROFILE=sentra
cdk synth
```

This generates CloudFormation templates in `cdk.out/`.

### Deploy Stacks

**Deploy all stacks:**
```bash
cdk deploy --all
```

**Deploy specific stack:**
```bash
cdk deploy SentraNetworkStack
```

### View Differences

Before deploying, check what will change:

```bash
cdk diff SentraNetworkStack
```

### Destroy Stacks

⚠️ **IMPORTANT**: Always destroy stacks in REVERSE order and verify cleanup!

**Option 1: Automated Cleanup (Recommended)**
```bash
cd ../scripts
export AWS_PROFILE=sentra AWS_ACCOUNT_ID=531109575379 AWS_REGION=us-east-1
./cleanup_destroy.sh
```

**Option 2: Manual Cleanup**
```bash
# Destroy in REVERSE order (last created → first created)
cdk destroy Sentra-DEV-Monitoring-Stack
cdk destroy Sentra-DEV-API-Stack
cdk destroy Sentra-DEV-Compute-Stack
cdk destroy Sentra-DEV-Storage-Stack
cdk destroy Sentra-DEV-Network-Stack
```

**Verification After Cleanup**
```bash
# Run cleanup verification script
cd ../scripts
./cleanup_verify.sh
```

See [Workstream 1 - Cleanup Policy](../tasks/workstream-1-infrastructure.md#critical-rule-no-dangling-resources) for complete cleanup procedures.

## Configuration

Configuration is managed via YAML files in `config/`:

- `config/dev.yaml` - Development environment settings

### Key Configuration Parameters

| Parameter | Description | Default |
|-----------|-------------|---------|
| `aws.account_id` | AWS account ID | 531109575379 |
| `aws.region` | AWS region | us-east-1 |
| `aws.profile` | AWS CLI profile | sentra |
| `vpc.cidr` | VPC CIDR block | 10.0.0.0/16 |
| `vpc.max_azs` | Number of availability zones | 2 |
| `vpc.nat_gateways` | Number of NAT gateways | 1 |

## Stacks

### NetworkStack

**Purpose**: VPC infrastructure foundation

**Resources Created:**
- VPC (10.0.0.0/16)
- 2 Public subnets (/28) - NAT Gateway only
- 2 Private subnets (/24) - ECS services
- 2 Isolated subnets (/28) - VPC endpoints
- 1 NAT Gateway (us-east-1a)
- VPC Flow Logs (7-day retention)
- Internet Gateway
- Route Tables

**Cost**: ~$32/month (NAT Gateway)

**Reference**: LLD 01 Section 2, ADR-011

## Troubleshooting

### Issue: `No module named 'yaml'`

**Solution**: Ensure you're using the venv Python:
```bash
# cdk.json should have:
"app": "../venv/bin/python3 app.py"
```

### Issue: CDK bootstrap fails

**Solution**: Check AWS credentials:
```bash
aws sts get-caller-identity --profile sentra
```

### Issue: Node.js version warning

The warning about Node.js v23 is informational and doesn't affect CDK functionality.

## Best Practices

1. **No Hard-Coded Values**: All configuration in `config/*.yaml`
2. **Modular Stacks**: Each stack has single responsibility
3. **Reusable**: Configuration-driven, easy to replicate
4. **Cost-Optimized**: Single NAT gateway for MVP
5. **Secure**: Private subnets for all services

## Next Steps

After Task 1 completion:
- [ ] Task 2: Security Groups Configuration
- [ ] Task 3: Route53 Private Hosted Zone
- [ ] Task 4: VPC Endpoints Setup
- [ ] Task 5: Storage Stack (CloudWatch Logs)
- [ ] Task 6: DynamoDB Tables

## References

- [CDK Infrastructure LLD](/Sentra/lld/01-cdk-infrastructure.md)
- [Workstream 1 Tasks](/Sentra/tasks/workstream-1-infrastructure.md)
- [ADR-011: VPC Design](/Sentra/adr.md#adr-011)
