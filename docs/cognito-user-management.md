# Cognito User Management

## Overview

This document explains how to create and manage Cognito users for the Sentra Dashboard, and why user creation is **not** part of CDK infrastructure code.

---

## Why Users Are NOT Created in CDK

### 1. Security Best Practice ✅

**Problem**: User credentials (emails, passwords) should NEVER be in infrastructure-as-code.

**Why**:
- CDK code is checked into version control (git)
- Credentials would be exposed in commit history
- Violates "secrets don't belong in code" principle
- Creates security audit findings

**Example of what NOT to do**:
```python
# ❌ BAD - NEVER DO THIS
cognito.CfnUserPoolUser(
    self, "AdminUser",
    user_pool_id=user_pool.user_pool_id,
    username="admin@sentra.com",
    password="hardcoded-password-in-code",  # ❌ SECURITY VIOLATION!
)
```

### 2. Separation of Concerns

**Infrastructure (CDK)**: Creates the "container"
- User Pool
- User Pool Client
- User Pool Domain
- Policies and configuration

**Operational Data (Runtime)**: Creates the "data"
- Actual user accounts
- User attributes
- Group memberships

### 3. Compliance and Governance

- Security policies require separation between infrastructure and user management
- User creation may need approval workflows
- Different teams manage infrastructure vs. users
- Audit trails need to track who created which users

### 4. Lifecycle Mismatch

**Infrastructure (CDK)**:
- Changes infrequently
- Versioned and deployed as a unit
- Destroyed and recreated as a stack

**Users**:
- Created/deleted dynamically
- Added on-demand (new employees, contractors)
- Persist across infrastructure updates
- Should NOT be destroyed when stack is updated

---

## Recommended Approach: Automated Script ✅

### Option 1: Using Provided Script (Recommended for MVP)

**Location**: `scripts/create-cognito-users.sh`

**Usage**:

```bash
# Method 1: Environment variables (most secure)
export SENTRA_ADMIN_EMAIL="admin@sentra.com"
export SENTRA_ADMIN_TEMP_PASSWORD="TempPassword123!"
./scripts/create-cognito-users.sh dev

# Method 2: Config file (gitignored)
cp scripts/.cognito-users.conf.example scripts/.cognito-users.conf
# Edit .cognito-users.conf with your users
./scripts/create-cognito-users.sh dev

# Method 3: Default demo users (dev/demo only)
./scripts/create-cognito-users.sh dev
```

**Features**:
- ✅ Idempotent (safe to run multiple times)
- ✅ Automatically gets User Pool ID from CloudFormation
- ✅ Checks if users already exist
- ✅ Supports multiple credential sources
- ✅ Follows security best practices

**Security**:
- Credentials stored in environment variables or gitignored config file
- NOT checked into version control
- Can integrate with AWS Secrets Manager (future enhancement)

---

## Alternative Approaches

### Option 2: AWS Secrets Manager (Production Recommended)

For production environments, store user credentials in AWS Secrets Manager:

```bash
# Store credentials in Secrets Manager
aws secretsmanager create-secret \
    --name sentra/cognito/admin-user \
    --secret-string '{"email":"admin@sentra.com","temp_password":"SecurePassword123!"}' \
    --profile sentra

# Retrieve and create user
SECRET=$(aws secretsmanager get-secret-value \
    --secret-id sentra/cognito/admin-user \
    --query SecretString \
    --output text \
    --profile sentra)

EMAIL=$(echo $SECRET | jq -r '.email')
PASSWORD=$(echo $SECRET | jq -r '.temp_password')

aws cognito-idp admin-create-user \
    --user-pool-id $USER_POOL_ID \
    --username $EMAIL \
    --user-attributes Name=email,Value=$EMAIL \
    --temporary-password $PASSWORD \
    --message-action SUPPRESS \
    --profile sentra
```

**Pros**:
- ✅ Centralized secret management
- ✅ Audit trail for secret access
- ✅ Automatic rotation support
- ✅ Cross-account access control

**Cons**:
- ❌ Additional AWS service dependency
- ❌ Cost (~$0.40/month per secret)
- ❌ More complex setup

### Option 3: SSO/Federation (Enterprise Recommended)

For enterprises with existing identity providers:

```python
# CDK code to configure SAML/OIDC federation
user_pool.add_identity_provider(
    cognito.UserPoolIdentityProvider.from_metadata(
        self, "OktaSaml",
        metadata_content=saml_metadata,
        provider_name="Okta"
    )
)
```

**Pros**:
- ✅ No user creation needed
- ✅ Centralized user management
- ✅ Single sign-on (SSO)
- ✅ Works with Okta, Azure AD, Google Workspace, etc.

**Cons**:
- ❌ Requires enterprise IdP
- ❌ More complex setup
- ❌ Out of scope for MVP

### Option 4: Custom CDK Resource (NOT Recommended)

Technically possible using CDK Custom Resources:

```python
# ❌ NOT RECOMMENDED - For illustration only
from aws_cdk import custom_resources as cr

create_user = cr.AwsCustomResource(
    self, "CreateAdminUser",
    on_create=cr.AwsSdkCall(
        service="CognitoIdentityServiceProvider",
        action="adminCreateUser",
        parameters={
            "UserPoolId": user_pool.user_pool_id,
            "Username": "admin@sentra.com",
            # Where does password come from? ❌
        }
    )
)
```

**Why NOT Recommended**:
- ❌ Still doesn't solve credential storage problem
- ❌ Users tied to stack lifecycle (deleted on stack destroy)
- ❌ CDK state drift if users are modified outside CDK
- ❌ Violates separation of concerns
- ❌ More complex than simple script

---

## Production Best Practices

For production deployments, consider this workflow:

### 1. Infrastructure Team (CDK)
```bash
# Deploy Cognito infrastructure
cdk deploy SentraCognitoStack --profile sentra
```

### 2. Security Team (User Creation)
```bash
# Security team creates initial admin user
aws cognito-idp admin-create-user \
    --user-pool-id $USER_POOL_ID \
    --username security-admin@company.com \
    --user-attributes Name=email,Value=security-admin@company.com \
    --temporary-password "$(openssl rand -base64 32)" \
    --profile sentra

# Send temporary password via secure channel (not email)
```

### 3. Ongoing User Management

**Option A: Self-Service Portal**
- Admin users can create/manage other users via Dashboard
- Implement RBAC for user management

**Option B: IDP Integration**
- Federate with Okta/Azure AD
- No user creation needed

**Option C: Automated Onboarding**
- Integrate with HR systems
- Lambda function triggered on employee onboarding
- Automatically creates Cognito user

---

## Comparison Table

| Approach | Security | Ease of Use | Cost | Production Ready |
|----------|----------|-------------|------|------------------|
| **Script (Recommended)** | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | Free | ✅ Yes |
| AWS Secrets Manager | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ~$0.40/month | ✅ Yes |
| SSO/Federation | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | Varies | ✅ Yes |
| CDK Custom Resource | ⭐⭐ | ⭐⭐ | Free | ❌ No |
| Hardcoded in CDK | ❌ | ⭐⭐⭐⭐⭐ | Free | ❌ **NEVER** |

---

## Integration with Workstream 8

### Current Implementation (Milestone 4)

**Manual Command** (lines 1366-1377 in workstream doc):
```bash
aws cognito-idp admin-create-user \
  --user-pool-id $USER_POOL_ID \
  --username admin@sentra.com \
  --user-attributes Name=email,Value=admin@sentra.com \
  --temporary-password "TempPassword123!" \
  --message-action SUPPRESS \
  --profile sentra
```

**Improved Approach**:
```bash
# Use the provided script instead
./scripts/create-cognito-users.sh dev
```

### Updated Task 10 (Recommended)

Replace manual commands with script invocation:

```bash
# Create Cognito admin user using automated script
export SENTRA_ADMIN_EMAIL="admin@sentra.com"
export SENTRA_ADMIN_TEMP_PASSWORD="$(openssl rand -base64 16)"

./scripts/create-cognito-users.sh dev

# Securely share temporary password with admin
echo "Temporary password: $SENTRA_ADMIN_TEMP_PASSWORD"
# (In production, send via secure channel)
```

---

## FAQ

### Q: Why not just use `self_sign_up_enabled=True`?

**A**: Security risk. We want controlled user creation:
- Prevents random people from creating accounts
- Admin approval required
- Better for compliance

### Q: Can we automate password creation?

**A**: Yes! Use secure random passwords:
```bash
# Generate secure temporary password
TEMP_PASSWORD="$(openssl rand -base64 24 | tr -d /+=)"
```

### Q: What if we need to create 100+ users?

**A**: Options:
1. Bulk import via CSV (AWS Console or CLI)
2. Script with loop reading from CSV
3. Integrate with HR system
4. Use SSO/Federation instead

### Q: Can users change their email after creation?

**A**: Yes, if `mutable=True` in CDK config (current setup allows it).

---

## Summary

**✅ DO**:
- Use automated scripts for user creation
- Store credentials in environment variables or Secrets Manager
- Separate infrastructure from operational data
- Follow security best practices

**❌ DON'T**:
- Hardcode credentials in CDK code
- Check credentials into version control
- Use CDK Custom Resources for user creation
- Mix infrastructure and data lifecycle

**For MVP**: Use `scripts/create-cognito-users.sh`

**For Production**: Integrate with AWS Secrets Manager or enterprise SSO/IdP
