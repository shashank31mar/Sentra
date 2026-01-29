# Sentra MVP - Bug Tracking

This directory contains bug reports, fixes, and deployment records for the Sentra MVP project.

---

## Active Bugs

### Bug #001: Multi-Agent Status Propagation Issue ✅ FIXED

**Status:** ✅ Deployed (Milestone 2)
**Severity:** High
**Priority:** P0
**Discovered:** 2025-01-18
**Fixed:** 2025-01-18
**Deployed:** 2025-12-24

**Summary:**
Multi-agent requests incorrectly showed ✅ ALLOWED when child agents denied operations (HTTP 403), creating confusing UX where status badge contradicted the message content.

**Root Cause:**
`call_payment_agent` tool returned error dictionaries instead of raising exceptions, preventing parent agent from detecting child denials.

**Fix:**
- Created `ToolDeniedError` exception class
- Updated `call_payment_agent` to raise exceptions on child HTTP != 200
- Updated Customer Query Agent routes to catch and propagate child status codes

**Files:**
- [bug-001-multi-agent-status-propagation.md](./bug-001-multi-agent-status-propagation.md) - Full bug report
- [bug-001-implementation-summary.md](./bug-001-implementation-summary.md) - Implementation details
- [bug-001-deployment-complete.md](./bug-001-deployment-complete.md) - Deployment record
- [bug-001-test-script.sh](./bug-001-test-script.sh) - Automated test script

**Testing Required:**
⏳ Manual testing via Cognito-authenticated session pending

---

## Bug Report Template

When documenting new bugs, use this structure:

```markdown
# Bug #XXX: [Title]

**Bug ID:** BUG-XXX
**Severity:** Low | Medium | High | Critical
**Priority:** P0 | P1 | P2 | P3
**Discovered:** YYYY-MM-DD
**Status:** Identified | In Progress | Fixed | Deployed | Verified

## Summary
[Brief description]

## Reproduction Steps
1. Step 1
2. Step 2
3. Expected vs Actual

## Root Cause Analysis
[Technical explanation]

## Proposed Solution
[Fix approach]

## Implementation Plan
[Tasks and phases]

## Testing Strategy
[Test cases]

## Rollout Plan
[Deployment steps]
```

---

## Bug Workflow

### 1. Discovery
- User reports issue or developer identifies bug
- Create bug report: `bugs/bug-XXX-[short-name].md`
- Assign severity and priority

### 2. Analysis
- Root cause investigation
- Impact assessment
- Solution design

### 3. Implementation
- Code changes
- Unit tests
- Documentation updates

### 4. Deployment
- Build Docker image with milestone number
- Deploy to dev environment
- Run smoke tests
- Monitor logs

### 5. Verification
- Manual testing
- Monitor for 24 hours
- Mark as verified

### 6. Closure
- Update bug report status
- Archive deployment records
- Update CHANGELOG

---

## Severity Definitions

| Severity | Definition | SLA |
|----------|------------|-----|
| **Critical** | Service down, data loss, security breach | Fix immediately |
| **High** | Major feature broken, significant UX issue | Fix within 24 hours |
| **Medium** | Minor feature broken, workaround exists | Fix within 1 week |
| **Low** | Cosmetic issue, minor inconvenience | Fix in next sprint |

---

## Priority Definitions

| Priority | Definition |
|----------|------------|
| **P0** | Must fix before next release |
| **P1** | Should fix in current sprint |
| **P2** | Nice to have in current sprint |
| **P3** | Can wait for future sprint |

---

## Files in This Directory

| File | Purpose |
|------|---------|
| `README.md` | This file - bug tracking overview |
| `bug-XXX-[name].md` | Full bug report and LLD |
| `bug-XXX-implementation-summary.md` | Code changes and deployment guide |
| `bug-XXX-deployment-complete.md` | Deployment record and verification |
| `bug-XXX-test-script.sh` | Automated test scripts |

---

## Quick Reference

### Build and Deploy Fix

```bash
# 1. Make code changes
# 2. Build and push image
python scripts/build_and_push_image.py --service [service-name] --milestone [N]

# 3. Update ECS service
AWS_PROFILE=sentra AWS_REGION=us-east-1 aws ecs update-service \
  --cluster sentra-mvp-cluster \
  --service [service-name] \
  --force-new-deployment

# 4. Monitor deployment
AWS_PROFILE=sentra AWS_REGION=us-east-1 aws ecs describe-services \
  --cluster sentra-mvp-cluster \
  --services [service-name]

# 5. Check logs
AWS_PROFILE=sentra AWS_REGION=us-east-1 aws logs tail \
  /ecs/sentra/[service-name] --follow
```

### Rollback

```bash
# Rollback to previous milestone
python scripts/build_and_push_image.py \
  --service [service-name] \
  --milestone [PREVIOUS_N] \
  --force
```

---

## Related Documentation

- [Best Practices](../best-practices.md) - Coding and deployment standards
- [Workstream 12](../tasks/workstream-12-multi-agent-workflow.md) - Multi-agent workflow tasks
- [LLD 12](../lld/12-multi-agent-workflow.md) - Multi-agent architecture

---

**Last Updated:** 2025-12-24
