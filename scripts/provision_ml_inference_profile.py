#!/usr/bin/env python3
"""Recovery / out-of-band provisioning for the aegionai-ml-classifier
Application Inference Profile.

WS19 / LLD 19 §2.4. **NOTE**: under normal operation the profile is created
by CDK (`Sentra-DEV-Compute-Stack`, logical id `AegionAIMLClassifierProfile`).
This script is the recovery / dev-only path for situations where CDK can't
own the resource — e.g., a fresh dev environment where you need the profile
before standing up the stack, or a stack-corruption recovery scenario.

The CopyFrom MUST be a system inference profile ARN (`us.anthropic...`), not
the bare foundation-model ARN. Haiku 4.5 does not support on-demand
invocation; it is only invokable via cross-region inference-profile routing.
A foundation-model ARN returns `"The provided foundation model does not
support On Demand inference"` from both the bedrock API and the CFN
resource provider.

This script is **idempotent**: it lists profiles by name and only creates
when the named profile is missing. Safe to re-run.

Usage:
    AWS_PROFILE=sentra python scripts/provision_ml_inference_profile.py
    AWS_PROFILE=sentra python scripts/provision_ml_inference_profile.py --region us-east-1

After provisioning, update `cdk/stacks/compute_stack.py` —
`ml_classifier_inference_profile_arn` constant — with the printed ARN,
then `cdk deploy Sentra-DEV-Compute-Stack` so the controller's task
definition env block gets the new value.
"""

from __future__ import annotations

import argparse
import logging
import sys

import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("provision_ml_inference_profile")


PROFILE_NAME = "aegionai-ml-classifier"
# Source: a US cross-region system inference profile for Haiku 4.5.
# Foundation-model ARN does NOT work — Haiku 4.5 doesn't support on-demand
# invocation, only inference-profile routing.
SOURCE_TEMPLATE = (
    "arn:aws:bedrock:{region}:{account}:inference-profile/"
    "us.anthropic.claude-haiku-4-5-20251001-v1:0"
)

# Description regex: ([0-9a-zA-Z:.][ _-]?)+ — no parens, no em-dashes.
DESCRIPTION = "ML threat classifier LLD 19 workload isolated"

TAGS = [
    {"key": "Workload", "value": "ml-classifier"},
    {"key": "Component", "value": "security-controller"},
    {"key": "CostCenter", "value": "platform-security"},
    {"key": "Workstream", "value": "WS19"},
]


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    sts = boto3.client("sts", region_name=args.region)
    account = sts.get_caller_identity()["Account"]
    log.info("account=%s region=%s", account, args.region)

    bedrock = boto3.client("bedrock", region_name=args.region)

    # Idempotency check.
    log.info("listing application inference profiles…")
    paginator = bedrock.get_paginator("list_inference_profiles") if hasattr(bedrock, "get_paginator") else None
    existing_arn = None
    try:
        resp = bedrock.list_inference_profiles(typeEquals="APPLICATION")
        for prof in resp.get("inferenceProfileSummaries", []):
            if prof.get("inferenceProfileName") == PROFILE_NAME:
                existing_arn = prof.get("inferenceProfileArn")
                break
    except ClientError as exc:
        log.error("list_inference_profiles failed: %s", exc)
        return 2

    if existing_arn:
        log.info("profile already exists: %s", existing_arn)
        print(existing_arn)
        return 0

    if args.dry_run:
        log.info("[dry-run] would create profile %s in account %s", PROFILE_NAME, account)
        return 0

    source_arn = SOURCE_TEMPLATE.format(region=args.region, account=account)
    log.info("creating profile %s with copyFrom=%s", PROFILE_NAME, source_arn)
    try:
        resp = bedrock.create_inference_profile(
            inferenceProfileName=PROFILE_NAME,
            description=DESCRIPTION,
            modelSource={"copyFrom": source_arn},
            tags=TAGS,
        )
    except ClientError as exc:
        log.error("create_inference_profile failed: %s", exc)
        return 3

    arn = resp["inferenceProfileArn"]
    log.info("created profile: %s (status=%s)", arn, resp.get("status"))
    log.info("update compute_stack.py — ml_classifier_inference_profile_arn — with this ARN, then cdk deploy.")
    print(arn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
