# Cognito User Management - Script Updates

**Date**: November 23, 2025
**Updated By**: Claude Code
**Related Workstream**: Workstream 8 - Authentication and ALB Architecture

---

## Summary of Changes

This document summarizes the improvements made to Cognito user management based on user feedback.

### Issues Addressed

1. ✅ Manual user creation was error-prone and tedious
2. ✅ No way to delete users programmatically
3. ✅ No option to specify custom email/password via command line
4. ✅ Default users/passwords not clearly documented
5. ✅ Confusion about using Route53 custom domain vs ALB DNS

---

## Changes Made

### 1. Enhanced User Management Script

**File**: `scripts/create-cognito-users.sh`

**New Features**:
- ✅ **Delete functionality** - Can now delete users with `--delete` flag
- ✅ **Command line arguments** - Can specify `--email` and `--password` directly
- ✅ **Multiple credential sources** - Priority system for credential input
- ✅ **Better help documentation** - Added `--help` flag with examples
- ✅ **Default users clearly documented** - Falls back to default users if no credentials provided

**Usage Examples**:

```bash
# Create with defaults (admin@sentra.com, demo@sentra.com)
./scripts/create-cognito-users.sh dev

# Create specific user
./scripts/create-cognito-users.sh --email admin@sentra.com --password "MyPass123!" dev

# Create from environment variables
export SENTRA_ADMIN_EMAIL="admin@sentra.com"
export SENTRA_ADMIN_TEMP_PASSWORD="TempPassword123!"
./scripts/create-cognito-users.sh dev

# Delete user
./scripts/create-cognito-users.sh --delete --email admin@sentra.com dev

# Show help
./scripts/create-cognito-users.sh --help
```

**Credential Priority** (for CREATE mode):
1. Command line arguments (`--email`, `--password`)
2. Environment variables (`SENTRA_ADMIN_EMAIL`, `SENTRA_ADMIN_TEMP_PASSWORD`)
3. Config file (`scripts/.cognito-users.conf`)
4. **Default users** - `admin@sentra.com` / `TempPassword123!`, `demo@sentra.com` / `DemoPassword123!`

---

### 2. Updated Workstream Documentation

**File**: `tasks/workstream-8-authentication-alb-split.md`

#### Task 10 Updates (Create Cognito Admin User)

**Before**:
- Manual `aws cognito-idp admin-create-user` commands
- Required copying User Pool ID manually
- No delete functionality

**After**:
- Recommended automated script usage with 4 options
- Script automatically retrieves User Pool ID
- Includes delete examples
- Manual commands still provided as fallback

#### Task 11 Updates (Test Dashboard Access)

**Before**:
- Used `$PUBLIC_ALB_DNS` without explaining how to get it
- No explanation why Route53 custom domain not used

**After**:
- Added command to retrieve Public ALB DNS from CloudFormation
- **Detailed explanation** of why Route53 public domain is not used (Phase 3 enhancement)
- Complete roadmap for adding custom domain in future:
  1. Register domain
  2. Create public hosted zone
  3. Request ACM certificate
  4. Add HTTPS listener
  5. Create DNS record
  6. Update Cognito callback URLs
- Clarified that ALB DNS works fine for MVP with Cognito auth

---

### 3. New Documentation

**File**: `docs/cognito-user-management.md`

Comprehensive guide covering:
- Why users are NOT created in CDK (security, separation of concerns, lifecycle)
- Recommended approach (automated script)
- Alternative approaches (Secrets Manager, SSO/Federation)
- Production best practices
- Comparison table of different approaches
- FAQ section

---

### 4. Security Improvements

**File**: `.gitignore`

Added:
```gitignore
# Cognito user credentials (NEVER commit!)
scripts/.cognito-users.conf
```

**File**: `scripts/.cognito-users.conf.example`

Template for secure credential storage (not checked into git).

---

## Default Users (Dev/Demo Only)

When no credentials are provided, the script creates these default users:

| Email | Temporary Password | Notes |
|-------|-------------------|-------|
| `admin@sentra.com` | `TempPassword123!` | Admin user for testing |
| `demo@sentra.com` | `DemoPassword123!` | Demo user for testing |

**SECURITY WARNING**: Default users should **ONLY** be used in dev/demo environments. For production, always use custom credentials via command line, environment variables, or config file.

---

## Route53 Custom Domain Clarification

### Current State (MVP)

- ✅ Private Route53 zone: `sentra.internal` (for internal service discovery)
- ❌ No public Route53 zone
- ❌ No custom domain registered
- ✅ Using AWS ALB DNS: `sentra-public-alb-*.us-east-1.elb.amazonaws.com`

### Why ALB DNS is Fine for Now

1. **Works with Cognito authentication** - ALB DNS fully supports Cognito OAuth callbacks
2. **No cost** - AWS-provided DNS is free
3. **No HTTPS required for dev** - Internal testing doesn't need SSL
4. **MVP focus** - Custom domain is a nice-to-have, not critical for MVP

### Future Enhancement (Phase 3)

To add custom domain like `dashboard.sentra.ai`:

1. Register domain (~$12/year)
2. Create public hosted zone
3. Request ACM certificate (free)
4. Add HTTPS listener to Public ALB
5. Create ALIAS record
6. Update Cognito callback URLs

**Estimated effort**: 1-2 hours
**Cost**: ~$12/year (domain) + $0.50/month (hosted zone)

---

## Testing Checklist

After implementing these changes, verify:

- [ ] Script creates users with default credentials
- [ ] Script creates users with command line arguments
- [ ] Script creates users from environment variables
- [ ] Script creates users from config file
- [ ] Script deletes users correctly
- [ ] Script shows helpful error messages
- [ ] Script is idempotent (safe to run multiple times)
- [ ] Gitignore prevents credential files from being committed
- [ ] Task 10 in workstream doc is clear and actionable
- [ ] Task 11 explains Route53 vs ALB DNS

---

## Migration Path

For existing deployments:

```bash
# 1. Test the new script (create default users)
./scripts/create-cognito-users.sh dev

# 2. Verify users created
aws cognito-idp list-users \
  --user-pool-id $USER_POOL_ID \
  --profile sentra

# 3. Test login via Dashboard
open "http://$PUBLIC_ALB_DNS"

# 4. If needed, delete and recreate with custom credentials
./scripts/create-cognito-users.sh --delete dev
./scripts/create-cognito-users.sh --email custom@sentra.com --password "Custom123!" dev
```

---

## Additional Resources

- **Script Documentation**: `scripts/create-cognito-users.sh --help`
- **Detailed Guide**: `docs/cognito-user-management.md`
- **Workstream Plan**: `tasks/workstream-8-authentication-alb-split.md`
- **Config Template**: `scripts/.cognito-users.conf.example`

---

## Questions & Answers

### Q1: Why do we have to create Cognito users manually?

**A**: Users should **never** be hardcoded in CDK infrastructure code because:
- Credentials would be exposed in version control
- Violates security best practices
- User lifecycle differs from infrastructure lifecycle
- Different teams manage infrastructure vs. users

See `docs/cognito-user-management.md` for detailed explanation.

### Q2: Can we automate user creation?

**A**: Yes! Use the provided script:
```bash
./scripts/create-cognito-users.sh dev
```

### Q3: Why can't we use Route53 custom domain instead of ALB DNS?

**A**: We can, but it's a **Phase 3 enhancement**. Current MVP doesn't have:
- Public Route53 hosted zone
- Registered domain name
- ACM certificate for HTTPS

ALB DNS works perfectly fine for MVP with Cognito auth. Custom domain adds cost (~$12/year) and complexity without significant benefit for dev/demo.

### Q4: What are the default users/passwords?

**A**: When no credentials provided:
- `admin@sentra.com` / `TempPassword123!`
- `demo@sentra.com` / `DemoPassword123!`

**WARNING**: Only use in dev/demo. Never in production!

---

## Next Steps

1. ✅ Script updated with delete functionality
2. ✅ Command line options added
3. ✅ Task 10 updated to recommend script
4. ✅ Task 11 updated with Route53 explanation
5. ⏭️ Test the script in your environment
6. ⏭️ Consider adding custom domain (Phase 3)
7. ⏭️ Consider SSO/Federation for production (Phase 4)
