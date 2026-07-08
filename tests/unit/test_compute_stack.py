"""WS-G G0.3 (D14 / ADR-039) — CDK synth assertions for the org-first entry
carve-out on the ComputeStack.

Asserts (from the synthesized CloudFormation, no deploy):
* the PUBLIC org listener rule is priority < 5 (evaluated before the priority-10
  authed page rule), carries a plain `forward` (NO authenticate-cognito), and its
  path condition is the exact org paths — never a `/assets/*` widen (shape (b)
  REJECTED);
* a PRIVATE-ALB forward rule for `/public/resolve-org` exists (the private ALB's
  default action is 404, so the internal hop needs an explicit forward).
"""
import os
from pathlib import Path

import aws_cdk as cdk
import yaml
from aws_cdk.assertions import Template
from stacks.compute_stack import ComputeStack
from stacks.network_stack import NetworkStack
from stacks.storage_stack import StorageStack
from stacks.cognito_stack import CognitoStack


def _config():
    repo_root = Path(__file__).resolve().parents[2]
    with open(repo_root / "cdk" / "config" / "dev.yaml") as f:
        config = yaml.safe_load(f)
    config.setdefault("aws", {})
    config["aws"]["account_id"] = os.environ.get("AWS_ACCOUNT_ID", "123456789012")
    config["aws"]["region"] = os.environ.get("AWS_REGION", "us-east-1")
    return config


def _compute_template():
    os.environ.setdefault("AWS_ACCOUNT_ID", "123456789012")
    os.environ.setdefault("AWS_REGION", "us-east-1")
    app = cdk.App()
    config = _config()
    env = cdk.Environment(account="123456789012", region="us-east-1")
    network = NetworkStack(app, "TestNet", config=config, env=env)
    storage = StorageStack(app, "TestStore", config=config, env=env)
    cognito = CognitoStack(app, "TestCognito", config=config, env=env)
    compute = ComputeStack(app, "TestCompute", config=config, network_stack=network,
                           storage_stack=storage, cognito_stack=cognito, env=env)
    return Template.from_stack(compute)


def _org_public_rule(template):
    """Find the public listener rule whose path condition includes /org.html."""
    rules = template.find_resources("AWS::ElasticLoadBalancingV2::ListenerRule")
    for _lid, res in rules.items():
        props = res.get("Properties", {})
        for cond in props.get("Conditions", []):
            cfg = cond.get("PathPatternConfig", {})
            values = cfg.get("Values", []) if isinstance(cfg, dict) else []
            if "/org.html" in values:
                return props
    return None


def test_resolve_org_public_rule_priority_below_5():
    template = _compute_template()
    props = _org_public_rule(template)
    assert props is not None, "no public listener rule carving out /org.html found"

    # Priority strictly below the priority-5 /v1 deny rule (and the priority-10 page rule).
    assert int(props["Priority"]) < 5, f"org rule priority must be < 5, got {props['Priority']}"

    # Path condition = exactly the org paths; NO /assets/* widen (shape (b) rejected).
    path_values = []
    for cond in props["Conditions"]:
        cfg = cond.get("PathPatternConfig")
        if isinstance(cfg, dict):
            path_values = cfg.get("Values", [])
    assert set(path_values) == {"/org.html", "/public/resolve-org"}, path_values
    assert not any("/assets" in v for v in path_values), "must NOT widen to /assets/* (shape (b) rejected)"

    # Plain forward — NO authenticate-cognito action on this public rule.
    action_types = {a.get("Type") for a in props.get("Actions", [])}
    assert "forward" in action_types
    assert "authenticate-cognito" not in action_types, "org entry must be public (no cognito action)"


def test_private_alb_resolve_org_forward_rule_present():
    template = _compute_template()
    rules = template.find_resources("AWS::ElasticLoadBalancingV2::ListenerRule")
    found = False
    for _lid, res in rules.items():
        props = res.get("Properties", {})
        for cond in props.get("Conditions", []):
            cfg = cond.get("PathPatternConfig", {})
            values = cfg.get("Values", []) if isinstance(cfg, dict) else []
            if "/public/resolve-org" in values:
                # A rule that forwards this path to a target group on the private ALB.
                action_types = {a.get("Type") for a in props.get("Actions", [])}
                if "forward" in action_types:
                    found = True
    assert found, "no ALB forward rule for /public/resolve-org (private hop would 404)"
