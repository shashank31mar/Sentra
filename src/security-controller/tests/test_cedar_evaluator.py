"""Unit tests for the Cedar evaluator wrapper + schema (CT02/CT03).

Pure tests — no DynamoDB/S3, no pipeline. They exercise the bundled schema and
baseline policy set directly through `CedarEvaluator`, asserting the Cedar
semantics the whole migration depends on:
  * forbid wins over permit,
  * missing optional attributes are SAFE (has-guards: no eval error; dangerous
    tools fail SECURE via deny-on-missing rather than open),
  * the feature §6 YAML->Cedar mappings behave like the legacy engine,
  * determining-policy ids resolve to the stable `@id` rule names (for CT04).
"""
import json

import pytest

from app.validators.cedar.evaluator import (
    CedarEvaluator,
    entities_to_json,
    validate_policy_set,
)
from app.validators.cedar.schema import (
    CEDAR_SCHEMA_VERSION,
    get_baseline_policies,
    get_schema_dict,
)

PRINCIPAL = 'Agent::"tenant-a#agent-1"'


def _store(allowed_tools, allowed_agents, max_refund=None, tool_attrs=None):
    """Build the per-request entity store CT05b will synthesize: the principal
    Agent (merged identity+authz attrs) plus Tool/Agent resource entities."""
    agent_attrs = {
        "allowed_tools": [{"__entity": {"type": "Tool", "id": t}} for t in allowed_tools],
        "allowed_agents": [{"__entity": {"type": "Agent", "id": a}} for a in allowed_agents],
    }
    if max_refund is not None:
        agent_attrs["max_refund_amount"] = max_refund
    entities = [{"uid": {"type": "Agent", "id": "tenant-a#agent-1"}, "attrs": agent_attrs, "parents": []}]
    for name, attrs in (tool_attrs or {}).items():
        entities.append({"uid": {"type": "Tool", "id": name}, "attrs": attrs, "parents": []})
    for target in allowed_agents:
        entities.append(
            {"uid": {"type": "Agent", "id": target},
             "attrs": {"allowed_tools": [], "allowed_agents": []}, "parents": []}
        )
    return entities_to_json(entities)


@pytest.fixture
def evaluator():
    return CedarEvaluator(get_baseline_policies())


@pytest.fixture
def tools():
    return {
        "get_balance": {},
        "process_refund": {},
        "verify_identity": {},
        "invoke_agent": {},
        "sim_swap": {},
    }


# --- schema (CT02) ---------------------------------------------------------

def test_schema_version_matches_filename():
    assert CEDAR_SCHEMA_VERSION == "v1"


def test_baseline_policies_validate_against_schema():
    assert validate_policy_set(get_baseline_policies()) == []


def test_schema_typing_entity_sets_and_long():
    agent = get_schema_dict()[""]["entityTypes"]["Agent"]["shape"]["attributes"]
    assert agent["allowed_tools"]["element"] == {"type": "Entity", "name": "Tool"}
    assert agent["allowed_agents"]["element"] == {"type": "Entity", "name": "Agent"}
    assert agent["max_refund_amount"]["type"] == "Long"


def test_invalid_policy_reports_errors():
    bad = 'permit(principal, action == Action::"Nope", resource);'
    errors = validate_policy_set(bad)
    assert errors and any("Nope" in e for e in errors)


# --- tool allow-list -------------------------------------------------------

def test_allowed_tool_permitted(evaluator, tools):
    store = _store(["get_balance"], [], tool_attrs=tools)
    d = evaluator.is_authorized(
        principal=PRINCIPAL, action='Action::"UseTool"',
        resource='Tool::"get_balance"', context={}, entities=store)
    assert d.allow is True
    assert d.determining_policy_ids == ["permit_use_tool"]


def test_unauthorized_tool_denied(evaluator, tools):
    store = _store(["get_balance"], [], tool_attrs=tools)
    d = evaluator.is_authorized(
        principal=PRINCIPAL, action='Action::"UseTool"',
        resource='Tool::"secretsmanager.get"', context={}, entities=store)
    assert d.allow is False


# --- refund cap (Long cents, forbid wins, deny-on-missing) -----------------

def test_refund_within_cap_allowed(evaluator, tools):
    store = _store(["process_refund"], [], max_refund=500000, tool_attrs=tools)
    d = evaluator.is_authorized(
        principal=PRINCIPAL, action='Action::"UseTool"',
        resource='Tool::"process_refund"', context={"amount": 300000}, entities=store)
    assert d.allow is True


def test_refund_over_cap_denied_forbid_wins(evaluator, tools):
    store = _store(["process_refund"], [], max_refund=500000, tool_attrs=tools)
    d = evaluator.is_authorized(
        principal=PRINCIPAL, action='Action::"UseTool"',
        resource='Tool::"process_refund"', context={"amount": 900000}, entities=store)
    assert d.allow is False
    assert d.determining_policy_ids == ["forbid_refund_over_cap"]


def test_refund_missing_amount_fails_secure(evaluator, tools):
    store = _store(["process_refund"], [], max_refund=500000, tool_attrs=tools)
    d = evaluator.is_authorized(
        principal=PRINCIPAL, action='Action::"UseTool"',
        resource='Tool::"process_refund"', context={}, entities=store)
    assert d.allow is False  # deny-on-missing, NOT open
    assert d.errors == []  # has-guards held; no policy errored


def test_refund_missing_cap_attr_no_error(evaluator, tools):
    """Principal omitting max_refund_amount must not error the cap rule
    (principal has-guard) — it just can't enforce the cap."""
    store = _store(["process_refund"], [], max_refund=None, tool_attrs=tools)
    d = evaluator.is_authorized(
        principal=PRINCIPAL, action='Action::"UseTool"',
        resource='Tool::"process_refund"', context={"amount": 900000}, entities=store)
    assert d.errors == []


# --- high-fraud identity gate ----------------------------------------------

def test_high_fraud_denied(evaluator, tools):
    store = _store(["verify_identity"], [], tool_attrs=tools)
    d = evaluator.is_authorized(
        principal=PRINCIPAL, action='Action::"UseTool"',
        resource='Tool::"verify_identity"', context={"fraud_risk": "high"}, entities=store)
    assert d.allow is False


def test_fraud_absent_allows(evaluator, tools):
    store = _store(["verify_identity"], [], tool_attrs=tools)
    d = evaluator.is_authorized(
        principal=PRINCIPAL, action='Action::"UseTool"',
        resource='Tool::"verify_identity"', context={}, entities=store)
    assert d.allow is True
    assert d.errors == []


# --- agent-to-agent --------------------------------------------------------

def test_invoke_allowed_target(evaluator, tools):
    store = _store(["invoke_agent"], ["helper-agent"], tool_attrs=tools)
    d = evaluator.is_authorized(
        principal=PRINCIPAL, action='Action::"InvokeAgent"',
        resource='Agent::"helper-agent"', context={}, entities=store)
    assert d.allow is True


def test_invoke_disallowed_target(evaluator, tools):
    store = _store(["invoke_agent"], ["helper-agent"], tool_attrs=tools)
    d = evaluator.is_authorized(
        principal=PRINCIPAL, action='Action::"InvokeAgent"',
        resource='Agent::"evil-agent"', context={}, entities=store)
    assert d.allow is False


# --- cross-cloud is NOT enforced by Cedar (deferred — stays in context_validator) -
# A plain allowed tool with no special handling just ALLOWs; there is no
# requires_precondition attribute or cross-cloud forbid in the baseline anymore.

def test_plain_allowed_tool_allows(evaluator, tools):
    store = _store(["sim_swap"], [], max_refund=500000, tool_attrs=tools)
    d = evaluator.is_authorized(
        principal=PRINCIPAL, action='Action::"UseTool"',
        resource='Tool::"sim_swap"', context={}, entities=store)
    assert d.allow is True  # cross-cloud preconditions are context_validator's job


# --- evaluator fault handling ----------------------------------------------

def test_malformed_policy_set_denies_and_reports_errors():
    """A malformed compiled policy set is an operator bug. cedarpy does NOT
    raise — it returns Deny (fail-secure) with the parse error in `errors`.
    CT04 keys off non-empty `errors` to emit POLICY_ERROR rather than a normal
    agent-attributable DENY."""
    ev = CedarEvaluator("this is not cedar")
    d = ev.is_authorized(
        principal=PRINCIPAL, action='Action::"UseTool"',
        resource='Tool::"x"', context={}, entities="[]")
    assert d.allow is False
    assert d.errors  # non-empty: the parse error surfaced, not swallowed


def test_malformed_entities_deny_and_report_errors():
    """A malformed entity store is likewise reported via `errors` (not raised),
    and denies. CT04 treats either error source as POLICY_ERROR / fail-secure."""
    ev = CedarEvaluator(get_baseline_policies())
    d = ev.is_authorized(
        principal=PRINCIPAL, action='Action::"UseTool"',
        resource='Tool::"x"', context={}, entities="{not valid json")
    assert d.allow is False
    assert d.errors
