#!/usr/bin/env python3
"""Deploy the AcmeBank Payments agent to AWS Bedrock (LLD 22 §5, §10.5).

Self-contained (separation, LLD 22 §3): this creates its OWN Lambda + IAM roles for the demo — it
does NOT touch core ``cdk/``. Steps:

  1. package the Lambda zip — vendoring ``aegion_guard`` (the SDK) + ``common/`` + the handler;
  2. ensure a Lambda execution role (basic logs + DynamoDB access to the demo tables);
  3. ensure a Bedrock agent service role (invoke nova-lite);
  4. create/update the Lambda (env: SENTRA_API_BASE/KEY, AEGION_DEMO_BACKEND=ddb, table names);
  5. allow Bedrock to invoke the Lambda;
  6. create the Bedrock agent — **`amazon.nova-lite-v1:0`, NO guardrail, permissive instructions**;
  7. attach the action group (OpenAPI schema + Lambda), prepare, and create a PROD alias.

Requires live AWS creds (``ada cred update --profile sentra``) and env:
    SENTRA_API_BASE   https://<id>.execute-api.us-east-1.amazonaws.com/prod
    SENTRA_API_KEY    usage-plan key (server-side; injected into the Lambda env)

    python aws-payments-agent/deploy/deploy_payments_agent.py --package-only   # build zip, no AWS
    python aws-payments-agent/deploy/deploy_payments_agent.py --create         # full deploy
"""
from __future__ import annotations

import argparse
import io
import json
import os
import pathlib
import sys
import time
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]          # aws-payments-agent/
DEMO = ROOT.parent                                          # demo-agents/
SDK_SRC = DEMO / "sdk" / "aegion-guard-python" / "src" / "aegion_guard"
HANDLER = ROOT / "tools" / "lambda_handler.py"
OPENAPI = ROOT / "agent_spec" / "action_group.openapi.json"
INSTRUCTIONS = ROOT / "agent_spec" / "instructions.md"

AGENT_NAME = "acme-payments-agent"
FOUNDATION_MODEL = "amazon.nova-lite-v1:0"                  # compliant + no guardrail (LLD 22 §5)
LAMBDA_NAME = "acme-payments-agent-tools"
LAMBDA_ROLE = "acme-payments-agent-lambda-role"
AGENT_ROLE = "acme-payments-agent-bedrock-role"
ALIAS = "PROD"
REGION = os.environ.get("AWS_REGION", "us-east-1")
PROFILE = os.environ.get("AWS_PROFILE", "sentra")


# --------------------------------------------------------------------------- packaging
def build_zip() -> bytes:
    """Bundle handler + SDK + common into a Lambda deployment zip (in memory).

    Also bundles the data-plane identity signing deps (``PyJWT[crypto]``) as
    **Linux/cp312 wheels** so the agent can mint ES256 tokens under a tenant in
    ``enforce`` (LLD-26 WS-A). Pure-.py vendoring is not enough: ``cryptography``
    /``cffi`` are compiled wheels and must match the Lambda runtime (Amazon Linux
    x86_64, python3.12). The lazy import in ``aegion_guard.identity`` means these
    are only loaded when identity env is configured — a non-signing deploy is
    unaffected if they're absent."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(HANDLER, "lambda_handler.py")
        for pkg_root, arc_root in ((SDK_SRC, "aegion_guard"), (DEMO / "common", "common")):
            for p in pkg_root.rglob("*.py"):
                if "__pycache__" in p.parts:
                    continue
                z.write(p, f"{arc_root}/{p.relative_to(pkg_root)}")
        _bundle_identity_deps(z)
    data = buf.getvalue()
    print(f"  ✓ packaged Lambda zip ({len(data) // 1024} KB)")
    return data


def _bundle_identity_deps(z: "zipfile.ZipFile") -> None:
    """pip-download PyJWT[crypto] as Linux/cp312 wheels and add them to the zip."""
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "--target", td,
                 "--only-binary=:all:", "--platform", "manylinux2014_x86_64",
                 "--implementation", "cp", "--python-version", "3.12",
                 "PyJWT[crypto]"],
                check=True, capture_output=True, text=True,
            )
        except subprocess.CalledProcessError as exc:  # pragma: no cover
            print("  ✗ failed to bundle identity deps:\n" + (exc.stderr or exc.stdout))
            raise
        root = pathlib.Path(td)
        for p in root.rglob("*"):
            if not p.is_file() or "__pycache__" in p.parts or p.suffix == ".pyc":
                continue
            if p.name.startswith(("PyJWT-", "cryptography-", "cffi-", "pycparser-")) and \
                    p.parent.name.endswith(".dist-info"):
                continue  # skip metadata noise; keep the importable packages
            z.write(p, str(p.relative_to(root)))
    print("  ✓ bundled identity signing deps (PyJWT[crypto], linux/cp312)")


# --------------------------------------------------------------------------- AWS helpers
def _session():
    import boto3

    return boto3.Session(profile_name=PROFILE, region_name=REGION)


def _account_id(sess) -> str:
    return sess.client("sts").get_caller_identity()["Account"]


def ensure_role(sess, name: str, trust: dict, inline: dict) -> str:
    iam = sess.client("iam")
    try:
        arn = iam.get_role(RoleName=name)["Role"]["Arn"]
        print(f"  • role {name} exists")
    except iam.exceptions.NoSuchEntityException:
        arn = iam.create_role(
            RoleName=name,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description="sentra demo-agents (WS-23)",
        )["Role"]["Arn"]
        print(f"  + created role {name}")
        time.sleep(10)  # IAM propagation
    iam.put_role_policy(RoleName=name, PolicyName=f"{name}-inline", PolicyDocument=json.dumps(inline))
    return arn


def deploy(create: bool) -> int:
    zip_bytes = build_zip()
    if not create:
        out = pathlib.Path("/tmp/acme-payments-agent.zip")
        out.write_bytes(zip_bytes)
        print(f"✅ package-only: wrote {out}")
        return 0

    api_base = os.environ.get("SENTRA_API_BASE")
    api_key = os.environ.get("SENTRA_API_KEY")
    if not api_base or not api_key:
        print("❌ SENTRA_API_BASE and SENTRA_API_KEY must be set for --create")
        return 1

    sess = _session()
    acct = _account_id(sess)
    lam = sess.client("lambda")

    # 2. Lambda execution role: logs + DynamoDB on the demo tables.
    lambda_role_arn = ensure_role(
        sess, LAMBDA_ROLE,
        trust={"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
               "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]},
        inline={"Version": "2012-10-17", "Statement": [
            {"Effect": "Allow", "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
             "Resource": "arn:aws:logs:*:*:*"},
            {"Effect": "Allow", "Action": ["dynamodb:GetItem", "dynamodb:Query", "dynamodb:UpdateItem",
                                            "dynamodb:PutItem", "dynamodb:BatchWriteItem"],
             "Resource": [f"arn:aws:dynamodb:{REGION}:{acct}:table/acme-*"]},
        ]})

    # 3. Bedrock agent service role: invoke nova-lite.
    agent_role_arn = ensure_role(
        sess, AGENT_ROLE,
        trust={"Version": "2012-10-17", "Statement": [{"Effect": "Allow",
               "Principal": {"Service": "bedrock.amazonaws.com"}, "Action": "sts:AssumeRole"}]},
        inline={"Version": "2012-10-17", "Statement": [
            {"Effect": "Allow", "Action": ["bedrock:InvokeModel"],
             "Resource": [f"arn:aws:bedrock:{REGION}::foundation-model/{FOUNDATION_MODEL}"]}]})

    env = {"Variables": {
        "SENTRA_API_BASE": api_base, "SENTRA_API_KEY": api_key,
        "AEGION_DEMO_BACKEND": "ddb",  # AWS_REGION is auto-populated by the Lambda runtime
    }}

    # WS-A data-plane identity (LLD-26): when the deployer's environment carries the
    # agent's tenant + kid + private key, pass them through so the agent SIGNS its
    # validate calls (ES256). The SDK lazy-loads PyJWT[crypto] (bundled by build_zip)
    # only when these are set, so a non-signing deploy is byte-identical to before.
    # Provision first to populate them, e.g.:
    #   python -m aegion_guard.provision --agent-id acme-payments-agent \
    #     --tenant-id acme --register --api-base "$SENTRA_API_BASE" \
    #     --header "x-amzn-oidc-data: <operator token>"
    #   export SENTRA_TENANT_ID=acme SENTRA_AGENT_KID=<kid> \
    #     SENTRA_AGENT_PRIVATE_KEY="$(cat acme-payments-agent.key)"
    _tid = os.environ.get("SENTRA_TENANT_ID")
    _kid = os.environ.get("SENTRA_AGENT_KID")
    _pk = os.environ.get("SENTRA_AGENT_PRIVATE_KEY")  # PEM literal (Lambda has no writable FS for a key file)
    if _tid and _kid and _pk:
        env["Variables"].update({
            "SENTRA_TENANT_ID": _tid,
            "SENTRA_AGENT_KID": _kid,
            "SENTRA_AGENT_PRIVATE_KEY": _pk,
        })
        print(f"  ✓ identity signing enabled (tenant={_tid}, kid={_kid[:8]}…)")
    else:
        print("  · identity signing NOT configured (set SENTRA_TENANT_ID/KID/PRIVATE_KEY to enable)")

    # 4. Create / update the Lambda.
    try:
        lam.get_function(FunctionName=LAMBDA_NAME)
        lam.update_function_code(FunctionName=LAMBDA_NAME, ZipFile=zip_bytes)
        lam.get_waiter("function_updated").wait(FunctionName=LAMBDA_NAME)
        lam.update_function_configuration(FunctionName=LAMBDA_NAME, Environment=env, Timeout=30)
        print(f"  ✓ updated Lambda {LAMBDA_NAME}")
    except lam.exceptions.ResourceNotFoundException:
        lam.create_function(
            FunctionName=LAMBDA_NAME, Runtime="python3.12", Role=lambda_role_arn,
            Handler="lambda_handler.handler", Code={"ZipFile": zip_bytes},
            Timeout=30, MemorySize=256, Environment=env,
            Tags={"project": "sentra-demo-agents", "workstream": "WS-23"},
        )
        lam.get_waiter("function_active_v2").wait(FunctionName=LAMBDA_NAME)
        print(f"  + created Lambda {LAMBDA_NAME}")
    lambda_arn = lam.get_function(FunctionName=LAMBDA_NAME)["Configuration"]["FunctionArn"]

    # 5. Allow Bedrock to invoke the Lambda.
    try:
        lam.add_permission(FunctionName=LAMBDA_NAME, StatementId="bedrock-invoke",
                           Action="lambda:InvokeFunction", Principal="bedrock.amazonaws.com",
                           SourceAccount=acct)
    except lam.exceptions.ResourceConflictException:
        pass

    # 6-7. Bedrock agent + action group + alias.
    agent_id = _create_agent(sess, agent_role_arn)
    _attach_action_group(sess, agent_id, lambda_arn)
    _prepare(sess, agent_id)
    alias_id = _create_alias(sess, agent_id)

    print("\n✅ Payments agent deployed.")
    print(f"   agentId={agent_id} aliasId={alias_id} model={FOUNDATION_MODEL} (no guardrail)")
    print("   Invoke with bedrock-agent-runtime InvokeAgent; tool calls route through Sentra.")
    return 0


def _create_agent(sess, role_arn: str) -> str:
    bedrock = sess.client("bedrock-agent")
    try:
        resp = bedrock.create_agent(
            agentName=AGENT_NAME, agentResourceRoleArn=role_arn,
            foundationModel=FOUNDATION_MODEL, instruction=INSTRUCTIONS.read_text(),
            description="AcmeBank payments agent (Sentra-validated, no guardrail).",
            idleSessionTTLInSeconds=600,
        )
        agent_id = resp["agent"]["agentId"]
        print(f"  + created agent {agent_id}")
    except bedrock.exceptions.ConflictException:
        agent_id = next(a["agentId"] for a in bedrock.list_agents()["agentSummaries"]
                        if a["agentName"] == AGENT_NAME)
        print(f"  • agent exists {agent_id}")
    # wait until not CREATING
    for _ in range(30):
        if bedrock.get_agent(agentId=agent_id)["agent"]["agentStatus"] in ("NOT_PREPARED", "PREPARED"):
            break
        time.sleep(2)
    return agent_id


def _attach_action_group(sess, agent_id: str, lambda_arn: str) -> None:
    bedrock = sess.client("bedrock-agent")
    schema = OPENAPI.read_text()
    kwargs = dict(agentId=agent_id, agentVersion="DRAFT", actionGroupName="payments_tools",
                  actionGroupExecutor={"lambda": lambda_arn},
                  apiSchema={"payload": schema}, actionGroupState="ENABLED")
    try:
        bedrock.create_agent_action_group(**kwargs)
        print("  + action group payments_tools")
    except bedrock.exceptions.ConflictException:
        ag_id = next(a["actionGroupId"] for a in
                     bedrock.list_agent_action_groups(agentId=agent_id, agentVersion="DRAFT")["actionGroupSummaries"]
                     if a["actionGroupName"] == "payments_tools")
        bedrock.update_agent_action_group(actionGroupId=ag_id, **kwargs)
        print("  • action group updated")


def _prepare(sess, agent_id: str) -> None:
    bedrock = sess.client("bedrock-agent")
    bedrock.prepare_agent(agentId=agent_id)
    for _ in range(30):
        if bedrock.get_agent(agentId=agent_id)["agent"]["agentStatus"] == "PREPARED":
            print("  ✓ agent PREPARED")
            return
        time.sleep(2)


def _create_alias(sess, agent_id: str) -> str:
    bedrock = sess.client("bedrock-agent")
    try:
        return bedrock.create_agent_alias(agentId=agent_id, agentAliasName=ALIAS)["agentAlias"]["agentAliasId"]
    except bedrock.exceptions.ConflictException:
        return next(a["agentAliasId"] for a in bedrock.list_agent_aliases(agentId=agent_id)["agentAliasSummaries"]
                    if a["agentAliasName"] == ALIAS)


def main() -> int:
    ap = argparse.ArgumentParser(description="Deploy the AcmeBank Payments Bedrock agent")
    ap.add_argument("--create", action="store_true", help="Full deploy to AWS")
    ap.add_argument("--package-only", action="store_true", help="Build the Lambda zip only (no AWS)")
    args = ap.parse_args()
    if not (args.create or args.package_only):
        ap.error("pass --create or --package-only")
    return deploy(create=args.create)


if __name__ == "__main__":
    raise SystemExit(main())
