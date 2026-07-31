#!/usr/bin/env bash
#
# deploy_marketing_site.sh — build + deploy the AegionAI public marketing site
# to AWS (S3 + CloudFront) via the config-gated StaticSiteStack.
#
# Prereqs (one-time — see docs/static-site-cutover.md):
#   1. An ACM cert in us-east-1 covering aegionai.ai + www.aegionai.ai, validated.
#   2. cdk/config/dev.yaml -> static_site.enabled: true and certificate_arn set.
#   3. export AWS_PROFILE=sentra AWS_ACCOUNT_ID=531109575379 AWS_REGION=us-east-1
#
# Usage:
#   ./scripts/deploy_marketing_site.sh            # build frontend + cdk deploy
#   ./scripts/deploy_marketing_site.sh --no-build # deploy existing frontend/dist
#
# The CDK BucketDeployment syncs frontend/dist/ to S3 and invalidates the whole
# CloudFront cache on every deploy, so a plain `cdk deploy` is the full publish.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STACK="Sentra-${ENVIRONMENT:-DEV}-StaticSite-Stack"
# Normalize to the stack-prefix casing app.py uses (environment.upper()).
STACK="Sentra-$(printf '%s' "${ENVIRONMENT:-dev}" | tr '[:lower:]' '[:upper:]')-StaticSite-Stack"

DO_BUILD=1
[[ "${1:-}" == "--no-build" ]] && DO_BUILD=0

echo "==> AegionAI marketing-site deploy"
echo "    account=${AWS_ACCOUNT_ID:-<unset>} region=${AWS_REGION:-us-east-1} profile=${AWS_PROFILE:-<unset>}"
echo "    stack=${STACK}"

: "${AWS_ACCOUNT_ID:?set AWS_ACCOUNT_ID (e.g. 531109575379)}"

# 1) Build the Vite SPA -> frontend/dist/
if [[ "$DO_BUILD" == "1" ]]; then
  echo "==> building frontend (npm run build)"
  ( cd "$REPO_ROOT/frontend" && npm ci --silent && npm run build )
else
  echo "==> skipping build (--no-build); using existing frontend/dist/"
fi

if [[ ! -f "$REPO_ROOT/frontend/dist/index.html" ]]; then
  echo "!! frontend/dist/index.html missing — build first (drop --no-build)" >&2
  exit 1
fi

# 2) Guard: refuse to deploy if the stack isn't enabled in config (would be a no-op
#    that silently does nothing). Grep the active env config for enabled: true.
ENV_YAML="$REPO_ROOT/cdk/config/${ENVIRONMENT:-dev}.yaml"
if ! grep -qE '^\s*enabled:\s*true' <(awk '/^static_site:/{f=1} f' "$ENV_YAML"); then
  echo "!! static_site.enabled is not true in ${ENV_YAML}." >&2
  echo "   Flip it (and set certificate_arn) before deploying — see docs/static-site-cutover.md." >&2
  exit 1
fi

# 3) Deploy the stack (syncs dist/ to S3 + invalidates CloudFront).
echo "==> cdk deploy ${STACK}"
( cd "$REPO_ROOT/cdk" && cdk deploy "$STACK" --require-approval any-change )

echo "==> done. CloudFront domain + bucket are in the stack outputs above."
echo "    Point GoDaddy DNS at the DistributionDomainName (see runbook), or"
echo "    if using Route53, the alias records were created by the stack."
