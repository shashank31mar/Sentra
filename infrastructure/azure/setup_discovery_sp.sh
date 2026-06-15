#!/usr/bin/env bash
#
# Provision the read-only Azure service principal Aegion uses to DISCOVER agents
# (Multi-Cloud Agent Import — feature §7/§14). This is the Azure analog of the
# AWS cross-account discovery role: least-privilege, read-only, no data-plane
# write/invoke.
#
# What it creates (idempotent):
#   1. An AAD app registration + service principal "aegion-discovery-sp".
#   2. Role assignments on the target subscription:
#        - Reader                 → list Cognitive Services accounts + deployments
#                                   (the deployment-discovery surface)
#        - Cognitive Services User → data-plane token to LIST AI Foundry agents
#                                    (the Agent Service surface; read-only)
#   3. A fresh client-secret (printed once).
#   4. The AWS Secrets Manager command to store that secret as the connection's
#      vault reference (run after `ada cred update --profile sentra`, since the
#      control plane resolves the secret from Secrets Manager — feature §14).
#
# The console then takes: subscription_id, tenant_id, client_id (= appId) and the
# Secrets Manager secret name as `secret_ref`.
#
# Usage:
#   ./setup_discovery_sp.sh [--name aegion-discovery-sp] [--secret-name aegion/azure/discovery-sp]
#
set -euo pipefail

SP_NAME="aegion-discovery-sp"
SECRET_NAME="aegion/azure/discovery-sp"
AWS_PROFILE="${AWS_PROFILE:-sentra}"
AWS_REGION="${AWS_REGION:-us-east-1}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name) SP_NAME="$2"; shift 2 ;;
    --secret-name) SECRET_NAME="$2"; shift 2 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

command -v az >/dev/null || { echo "az CLI not found" >&2; exit 1; }

SUBSCRIPTION_ID="$(az account show --query id -o tsv)"
TENANT_ID="$(az account show --query tenantId -o tsv)"
SCOPE="/subscriptions/${SUBSCRIPTION_ID}"

echo "Subscription : ${SUBSCRIPTION_ID}"
echo "Tenant       : ${TENANT_ID}"
echo "SP name      : ${SP_NAME}"
echo

# 1+2+3) Create (or reset) the SP with Reader on the subscription. Re-running
# resets the password and is safe (the assignment is upserted below).
echo "Creating service principal with Reader on the subscription…"
CREATE_JSON="$(az ad sp create-for-rbac \
  --name "${SP_NAME}" \
  --role Reader \
  --scopes "${SCOPE}" \
  -o json)"

CLIENT_ID="$(echo "${CREATE_JSON}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["appId"])')"
CLIENT_SECRET="$(echo "${CREATE_JSON}" | python3 -c 'import sys,json;print(json.load(sys.stdin)["password"])')"

# 2b) Add Cognitive Services User for the AI Foundry data-plane agent list.
# Read-only data action; needed only for the Foundry Agent Service surface.
echo "Adding 'Cognitive Services User' for Foundry data-plane discovery…"
az role assignment create \
  --assignee "${CLIENT_ID}" \
  --role "Cognitive Services User" \
  --scope "${SCOPE}" >/dev/null 2>&1 || echo "  (role may already be assigned; continuing)"

cat <<EOF

────────────────────────────────────────────────────────────────────────────
Service principal ready. Console connection fields:

  subscription_id : ${SUBSCRIPTION_ID}
  tenant_id       : ${TENANT_ID}
  client_id       : ${CLIENT_ID}
  secret_ref      : ${SECRET_NAME}        (after storing the secret below)

Store the client-secret in AWS Secrets Manager (the platform keeps a REFERENCE
only — never the secret). Run after refreshing AWS creds (\`ada cred update --profile ${AWS_PROFILE}\`):

  aws secretsmanager create-secret \\
    --name "${SECRET_NAME}" \\
    --secret-string '{"client_secret":"${CLIENT_SECRET}"}' \\
    --profile ${AWS_PROFILE} --region ${AWS_REGION}

  # rotate later with: aws secretsmanager put-secret-value --secret-id "${SECRET_NAME}" ...
────────────────────────────────────────────────────────────────────────────
EOF
