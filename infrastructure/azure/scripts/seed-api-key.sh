#!/usr/bin/env sh
# postProvision hook: seed the Sentra API key into Azure Key Vault from AWS
# Secrets Manager. Idempotent — safe to re-run.
#
# Invoked automatically by `azd up` after Bicep provisioning completes.
# Reads outputs from the deployment via env vars azd exports (AZURE_*, KEY_VAULT_NAME).

set -e

# Issue #4 (Kiro M4 review): pre-flight check on required env vars so we fail
# with a clear message instead of an opaque Azure-side error on the secret-set call.
: "${KEY_VAULT_NAME:?ERROR: KEY_VAULT_NAME must be set (azd should export this via Bicep outputs).}"

echo "[seed-api-key] Pulling Sentra API key from AWS Secrets Manager..."
# Note: with `set -e`, a non-zero from aws would already exit; the empty-string
# check below handles the corner case where the CLI returns 0 with empty output
# (rare but observed when a profile resolves to a stale empty cache).
KEY_JSON="$(aws secretsmanager get-secret-value \
    --secret-id sentra-api-key \
    --profile sentra \
    --region us-east-1 \
    --query SecretString \
    --output text 2>&1)"

if [ -z "$KEY_JSON" ]; then
    echo "[seed-api-key] ERROR: AWS returned an empty Sentra API key." >&2
    echo "[seed-api-key] Check: 'ada cred update --once --profile sentra' may be required." >&2
    exit 1
fi

# Secret value in AWS is JSON: {"key": "<40-char-value>"} — parse it.
API_KEY="$(echo "$KEY_JSON" | python3 -c "import sys, json; print(json.loads(sys.stdin.read())['key'])")"

if [ -z "$API_KEY" ]; then
    echo "[seed-api-key] ERROR: parsed API key is empty." >&2
    exit 1
fi

echo "[seed-api-key] Writing secret 'sentra-api-key' to Key Vault '$KEY_VAULT_NAME'..."
az keyvault secret set \
    --vault-name "$KEY_VAULT_NAME" \
    --name sentra-api-key \
    --value "$API_KEY" \
    --output none

echo "[seed-api-key] Done. Function App will pick up the secret on next restart."
