#!/usr/bin/env python3
"""Deploy the traffic generator: a Lambda + an EventBridge schedule (LLD 22 §9, §10.5).

Self-contained (no core CDK). Creates a Lambda from ``lambda_handler.py`` + ``generator.py`` +
``attack_prompts/`` and an EventBridge rule (default every 3 min) that invokes it. Pauseable by
disabling the rule; tear down with the demo stack.

Requires the agents to be deployed first (their Lambda name + Function URLs):
    PAYMENTS_LAMBDA_NAME   (default acme-payments-agent-tools)
    IDENTITY_FUNC_URL      https://<identity-func>.azurewebsites.net/api/tool/{tool_name}
    TELECOM_FUNC_URL       https://<telecom-func>.azurewebsites.net/api/tool/{tool_name}

    python traffic/deploy_traffic.py --create [--rate "rate(3 minutes)"]
    python traffic/deploy_traffic.py --package-only
"""
from __future__ import annotations

import argparse
import io
import json
import os
import pathlib
import time
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent
LAMBDA_NAME = "acme-demo-traffic"
LAMBDA_ROLE = "acme-demo-traffic-role"
RULE_NAME = "acme-demo-traffic-schedule"
REGION = os.environ.get("AWS_REGION", "us-east-1")
PROFILE = os.environ.get("AWS_PROFILE", "sentra")
PAYMENTS_LAMBDA = os.environ.get("PAYMENTS_LAMBDA_NAME", "acme-payments-agent-tools")


def build_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(ROOT / "lambda_handler.py", "lambda_handler.py")
        z.write(ROOT / "generator.py", "generator.py")
        z.write(ROOT / "attack_prompts" / "injection.txt", "attack_prompts/injection.txt")
        z.write(ROOT / "attack_prompts" / "ml_injection.txt", "attack_prompts/ml_injection.txt")
    data = buf.getvalue()
    print(f"  ✓ packaged traffic Lambda ({len(data) // 1024} KB)")
    return data


def _session():
    import boto3

    return boto3.Session(profile_name=PROFILE, region_name=REGION)


def deploy(create: bool) -> int:
    zip_bytes = build_zip()
    if not create:
        pathlib.Path("/tmp/acme-demo-traffic.zip").write_bytes(zip_bytes)
        print("✅ package-only: /tmp/acme-demo-traffic.zip")
        return 0

    sess = _session()
    acct = sess.client("sts").get_caller_identity()["Account"]
    iam, lam, events = sess.client("iam"), sess.client("lambda"), sess.client("events")

    # Role: logs + invoke the payments Lambda.
    try:
        role_arn = iam.get_role(RoleName=LAMBDA_ROLE)["Role"]["Arn"]
    except iam.exceptions.NoSuchEntityException:
        role_arn = iam.create_role(
            RoleName=LAMBDA_ROLE,
            AssumeRolePolicyDocument=json.dumps({"Version": "2012-10-17", "Statement": [
                {"Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]}),
        )["Role"]["Arn"]
        time.sleep(10)
    iam.put_role_policy(RoleName=LAMBDA_ROLE, PolicyName="inline", PolicyDocument=json.dumps(
        {"Version": "2012-10-17", "Statement": [
            {"Effect": "Allow", "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
             "Resource": "arn:aws:logs:*:*:*"},
            {"Effect": "Allow", "Action": "lambda:InvokeFunction",
             "Resource": f"arn:aws:lambda:{REGION}:{acct}:function:{PAYMENTS_LAMBDA}"}]}))

    env = {"Variables": {
        "PAYMENTS_LAMBDA_NAME": PAYMENTS_LAMBDA,
        "IDENTITY_FUNC_URL": os.environ.get("IDENTITY_FUNC_URL", ""),
        "TELECOM_FUNC_URL": os.environ.get("TELECOM_FUNC_URL", ""),
    }}
    try:
        lam.get_function(FunctionName=LAMBDA_NAME)
        lam.update_function_code(FunctionName=LAMBDA_NAME, ZipFile=zip_bytes)
        lam.get_waiter("function_updated").wait(FunctionName=LAMBDA_NAME)
        lam.update_function_configuration(FunctionName=LAMBDA_NAME, Environment=env, Timeout=120)
    except lam.exceptions.ResourceNotFoundException:
        lam.create_function(FunctionName=LAMBDA_NAME, Runtime="python3.12", Role=role_arn,
                            Handler="lambda_handler.handler", Code={"ZipFile": zip_bytes},
                            Timeout=120, MemorySize=256, Environment=env,
                            Tags={"project": "sentra-demo-agents", "workstream": "WS-23"})
        lam.get_waiter("function_active_v2").wait(FunctionName=LAMBDA_NAME)
    fn_arn = lam.get_function(FunctionName=LAMBDA_NAME)["Configuration"]["FunctionArn"]

    # EventBridge schedule.
    rate = os.environ.get("TRAFFIC_RATE", "rate(3 minutes)")
    events.put_rule(Name=RULE_NAME, ScheduleExpression=rate, State="ENABLED",
                    Description="sentra demo traffic generator")
    try:
        lam.add_permission(FunctionName=LAMBDA_NAME, StatementId="eventbridge-invoke",
                           Action="lambda:InvokeFunction", Principal="events.amazonaws.com",
                           SourceArn=f"arn:aws:events:{REGION}:{acct}:rule/{RULE_NAME}")
    except lam.exceptions.ResourceConflictException:
        pass
    events.put_targets(Rule=RULE_NAME, Targets=[{"Id": "traffic", "Arn": fn_arn}])

    print(f"\n✅ traffic generator deployed ({rate}).")
    print(f"   Lambda={LAMBDA_NAME}  rule={RULE_NAME}")
    print("   Pause:  aws events disable-rule --name " + RULE_NAME)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Deploy the demo traffic generator")
    ap.add_argument("--create", action="store_true")
    ap.add_argument("--package-only", action="store_true")
    args = ap.parse_args()
    if not (args.create or args.package_only):
        ap.error("pass --create or --package-only")
    return deploy(create=args.create)


if __name__ == "__main__":
    raise SystemExit(main())
