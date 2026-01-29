# Sentra Scripts

Automation scripts for building, deploying, and managing Sentra MVP services.

---

## build_and_push_image.py

**Purpose**: Build and push Docker images to ECR with milestone-based versioning.

### Key Features

✅ **Milestone-Based Versioning**: Enforces immutable milestone numbers  
✅ **Automatic Validation**: Checks AWS credentials and prevents overwrites  
✅ **Dual Tagging**: Tags both `milestone-N` and `latest`  
✅ **Safety First**: Rejects duplicate milestones by default  
✅ **Local Testing**: Build without pushing for testing  

### Usage

```bash
# Build and push milestone 1
python scripts/build_and_push_image.py --service security-controller --milestone 1

# Build and push milestone 2
python scripts/build_and_push_image.py --service security-controller --milestone 2

# Build locally for testing (doesn't push)
python scripts/build_and_push_image.py --service security-controller --milestone 1 --no-push

# Force overwrite existing milestone (use with caution!)
python scripts/build_and_push_image.py --service security-controller --milestone 1 --force
```

### Best Practices

1. **Always use milestone numbers** - Never use arbitrary tags
2. **Milestones are immutable** - Each milestone can only be created once
3. **Test locally first** - Use `--no-push` to test before pushing
4. **Increment milestones** - Use milestone 1, 2, 3, etc. in order
5. **Use --force carefully** - Only for rollbacks or fixing mistakes

### How It Works

1. **Validates Prerequisites**
   - Checks AWS credentials are valid
   - Verifies Dockerfile exists
   - Checks if milestone already exists (unless --force)

2. **Builds Image**
   - Builds Docker image with `linux/amd64` platform (ECS requirement)
   - Tags locally as `sentra/SERVICE:milestone-N`

3. **Pushes to ECR**
   - Logs into ECR automatically
   - Pushes `milestone-N` tag
   - Also pushes `latest` tag (for ECS auto-deployment)

4. **Verifies Deployment**
   - Confirms images exist in ECR
   - Shows next steps for monitoring

### Milestone Immutability

**Why milestones are immutable**:
- Prevents accidental overwrites
- Ensures reproducible deployments
- Makes rollback reliable
- Provides clear version history

**Example**:
```bash
# First time - SUCCESS
$ python scripts/build_and_push_image.py --service security-controller --milestone 1
✓ Build completed successfully!

# Try again - REJECTED
$ python scripts/build_and_push_image.py --service security-controller --milestone 1
✗ Milestone 1 already exists in ECR!
  Options:
    1. Use a new milestone number: --milestone 2
    2. Force overwrite (not recommended): --force
    3. Build locally only: --no-push
```

### Rollback

To rollback to a previous milestone:

```bash
# Rollback to milestone 1 (updates :latest tag)
python scripts/build_and_push_image.py --service security-controller --milestone 1 --force
```

This re-pushes the milestone-1 image and updates the `:latest` tag, causing ECS to redeploy the previous version.

### Error Handling

The script validates everything before starting:
- ✅ AWS credentials valid
- ✅ Dockerfile exists
- ✅ Build context exists
- ✅ Milestone doesn't already exist (unless --force)
- ✅ ECR repository exists

If any check fails, the script exits with a clear error message.

### Environment Variables

The script uses these AWS settings (configured at top of script):
- `AWS_PROFILE`: sentra
- `AWS_REGION`: us-east-1
- `AWS_ACCOUNT_ID`: 531109575379

### Supported Services

- `security-controller`
- `dashboard`
- `customer-query-agent`
- `payment-agent`

---

## Future Scripts

Additional scripts will be added for:
- `seed_policies.py` - Load agent policies into DynamoDB
- `verify_deployment.py` - Verify all services are healthy
- `cleanup_old_images.py` - Remove old ECR images

---

**Last Updated**: November 18, 2025  
**Maintained By**: Sentra MVP Team
