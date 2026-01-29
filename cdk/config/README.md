# CDK Configuration Files

## Security Notice ⚠️

**NEVER commit sensitive data to Git:**
- AWS Account IDs
- AWS Profiles with credentials
- API Keys
- Secrets or passwords

## Setup Instructions

### 1. Copy Example Configuration

```bash
cp dev.example.yaml dev.yaml
```

### 2. Set Environment Variables

```bash
# Required for deployment
export AWS_ACCOUNT_ID=531109575379
export AWS_PROFILE=sentra
export AWS_REGION=us-east-1
```

### 3. Verify Configuration

The CDK app will automatically use environment variables to override config values.

## Files

- `dev.example.yaml` - **Safe template** (committed to Git)
- `dev.yaml` - **Actual config** (gitignored, NOT committed)
- `prod.yaml` - **Production config** (gitignored, NOT committed)

## How It Works

The CDK app (`app.py`) loads configuration in this order:

1. Read `dev.yaml` (or `prod.yaml` based on `ENVIRONMENT` env var)
2. Override with environment variables if present:
   - `AWS_ACCOUNT_ID` → `aws.account_id`
   - `AWS_REGION` → `aws.region`
   - `AWS_PROFILE` → `aws.profile`

This ensures sensitive data comes from environment variables, not committed files.

## Best Practices

✅ **DO:**
- Use environment variables for account IDs and profiles
- Keep `dev.yaml` and `prod.yaml` in `.gitignore`
- Commit `*.example.yaml` files as templates
- Document required environment variables

❌ **DON'T:**
- Commit actual account IDs to Git
- Commit AWS credentials or API keys
- Share config files with sensitive data
- Hard-code secrets in code

## Example .env File (Local Development)

Create a `.env` file in your project root (gitignored):

```bash
# AWS Configuration
export AWS_ACCOUNT_ID=531109575379
export AWS_PROFILE=sentra
export AWS_REGION=us-east-1
export ENVIRONMENT=dev

# Load with: source .env
```
