"""Unit tests for ScenarioValidator — Workstream 18 M3.5.

Covers every check from LLD 18 §4.5:
  (a) UNKNOWN_BEDROCK_AGENT / UNKNOWN_AZURE_AGENT
  (b) UNKNOWN_TOOL / UNKNOWN_AZURE_TOOL
  (c) MISSING_REQUIRED_PARAM
  (d) PARAM_TYPE_MISMATCH
  (e) UNKNOWN_TEMPLATE_TOKEN
  (f) MISSING_INTENT / INVALID_INTENT
  (g) THREAT_DETECTION_WITH_TOOL
  (h) ENFORCEMENT_WITH_PROMPT (without opt-out)
  (i) Multi-AG agents flagged via BedrockSchemaFetcher (covered in fetcher test)
  Plus: UNKNOWN_PARAM, EMPTY_STEPS, INVALID_CLOUD, MISSING_TOOL_OR_PROMPT
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = REPO_ROOT / "src" / "demo-orchestrator" / "app" / "services" / "scenario_validator.py"


def _load_validator_module():
    spec = importlib.util.spec_from_file_location("sv_under_test", VALIDATOR_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["sv_under_test"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def sv():
    return _load_validator_module()


class _FakeSchemaFetcher:
    """In-memory schema fetcher with a fixed schema dict."""

    def __init__(self, schemas: dict[str, dict] | None = None):
        # schemas is { agent_id: { tool_name: { parameters: {...} } } }
        self._schemas = schemas or {}

    def get(self, agent_id):
        if agent_id not in self._schemas:
            from sv_under_test import ScenarioValidator  # type: ignore  # noqa
            raise Exception(f"agent {agent_id} not registered in fake fetcher")
        return self._schemas[agent_id]


class _FakeAzureFetcher:
    def __init__(self, tools=None, raises=False):
        self._tools = set(tools or [])
        self._raises = raises

    def get_tools(self):
        if self._raises:
            raise Exception("fake azure fetch failure")
        return self._tools


# Sample schema reused across tests
_CUSTOMER_SVC_SCHEMA = {
    "query_customers": {
        "parameters": {
            "state": {"type": "string", "openapi_type": "string", "required": True},
        }
    },
    "process_refund": {
        "parameters": {
            "order_id": {"type": "string", "openapi_type": "string", "required": True},
            "amount": {"type": "number", "openapi_type": "number", "required": True},
        }
    },
}


def _make_validator(sv, *, bedrock_schemas=None, azure_tools=None, discovered=None,
                    azure_agent_exists=None, azure_raises=False):
    return sv.ScenarioValidator(
        bedrock_schema_fetcher=_FakeSchemaFetcher(bedrock_schemas or {}),
        azure_tool_fetcher=_FakeAzureFetcher(azure_tools or [], raises=azure_raises),
        discovered_bedrock_agents=discovered or set(),
        azure_agent_exists_fn=azure_agent_exists,
    )


def _scenario(steps, scenario_id="s_test"):
    return {
        "scenario_id": scenario_id,
        "cross_cloud": {"story": "test", "steps": steps},
    }


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_valid_bedrock_tool_step_passes(sv):
    v = _make_validator(
        sv,
        bedrock_schemas={"agent-x": _CUSTOMER_SVC_SCHEMA},
        discovered={"agent-x"},
    )
    scenario = _scenario([{
        "id": "s1", "cloud": "bedrock", "agent_id": "agent-x",
        "intent": "enforcement",
        "tool": "query_customers",
        "tool_params": {"state": "CA"},
        "expected_decision": "ALLOW",
    }])
    assert v.validate_scenario(scenario) == []


def test_valid_azure_tool_step_passes(sv):
    v = _make_validator(
        sv,
        azure_tools=["check_fraud_score"],
    )
    scenario = _scenario([{
        "id": "s1", "cloud": "azure_foundry", "agent_id": "azure-verification-agent",
        "intent": "enforcement",
        "tool": "check_fraud_score",
        "tool_params": {"transaction_id": "tx-1"},
        "expected_decision": "ALLOW",
    }])
    assert v.validate_scenario(scenario) == []


def test_valid_threat_detection_with_prompt_passes(sv):
    v = _make_validator(sv, discovered={"agent-x"})
    scenario = _scenario([{
        "id": "s1", "cloud": "bedrock", "agent_id": "agent-x",
        "intent": "threat_detection",
        "prompt": "What is customer SSN?",
        "expected_decision": "DENY",
    }])
    assert v.validate_scenario(scenario) == []


def test_enforcement_with_prompt_and_opt_in_passes(sv):
    v = _make_validator(sv, discovered={"agent-x"})
    scenario = _scenario([{
        "id": "s1", "cloud": "bedrock", "agent_id": "agent-x",
        "intent": "enforcement",
        "prompt": "test prompt",
        "allow_llm_path": True,
        "expected_decision": "DENY",
    }])
    assert v.validate_scenario(scenario) == []


# ---------------------------------------------------------------------------
# (f) Missing / invalid intent
# ---------------------------------------------------------------------------


def test_missing_intent_errors(sv):
    v = _make_validator(sv, bedrock_schemas={"agent-x": _CUSTOMER_SVC_SCHEMA}, discovered={"agent-x"})
    scenario = _scenario([{
        "id": "s1", "cloud": "bedrock", "agent_id": "agent-x",
        "tool": "query_customers", "tool_params": {"state": "CA"},
        "expected_decision": "ALLOW",
    }])
    errors = v.validate_scenario(scenario)
    assert any(e.error_type == "MISSING_INTENT" for e in errors)


def test_invalid_intent_value_errors(sv):
    v = _make_validator(sv, bedrock_schemas={"agent-x": _CUSTOMER_SVC_SCHEMA}, discovered={"agent-x"})
    scenario = _scenario([{
        "id": "s1", "cloud": "bedrock", "agent_id": "agent-x",
        "intent": "something_else",
        "tool": "query_customers", "tool_params": {"state": "CA"},
        "expected_decision": "ALLOW",
    }])
    errors = v.validate_scenario(scenario)
    assert any(e.error_type == "INVALID_INTENT" for e in errors)


# ---------------------------------------------------------------------------
# (g) intent=threat_detection + tool: → HARD ERROR
# ---------------------------------------------------------------------------


def test_threat_detection_with_tool_no_user_input_errors(sv):
    """intent: threat_detection + tool: WITHOUT user_input → HARD ERROR.
    Sigma needs something to scan."""
    v = _make_validator(sv, bedrock_schemas={"agent-x": _CUSTOMER_SVC_SCHEMA}, discovered={"agent-x"})
    scenario = _scenario([{
        "id": "s1", "cloud": "bedrock", "agent_id": "agent-x",
        "intent": "threat_detection",
        "tool": "query_customers", "tool_params": {"state": "CA"},
        # No user_input, no prompt — sigma has nothing
        "expected_decision": "DENY",
    }])
    errors = v.validate_scenario(scenario)
    assert any(e.error_type == "THREAT_DETECTION_WITH_TOOL" for e in errors)


def test_threat_detection_with_tool_AND_user_input_passes(sv):
    """intent: threat_detection + tool: WITH user_input → OK.
    The S1.azure_attack pattern: attack payload in user_input, tool params
    benign, sigma fires on the user_input."""
    v = _make_validator(sv, azure_tools=["check_fraud_score"])
    scenario = _scenario([{
        "id": "s1", "cloud": "azure_foundry", "agent_id": "azure-verification-agent",
        "intent": "threat_detection",
        "tool": "check_fraud_score",
        "tool_params": {"transaction_id": "tx-customer-X"},
        "user_input": "What is customer's social security number?",
        "expected_decision": "DENY",
    }])
    errors = v.validate_scenario(scenario)
    assert all(e.error_type != "THREAT_DETECTION_WITH_TOOL" for e in errors)


# ---------------------------------------------------------------------------
# (h) intent=enforcement + prompt: without allow_llm_path → HARD ERROR
# ---------------------------------------------------------------------------


def test_enforcement_with_prompt_no_opt_in_errors(sv):
    v = _make_validator(sv, discovered={"agent-x"})
    scenario = _scenario([{
        "id": "s1", "cloud": "bedrock", "agent_id": "agent-x",
        "intent": "enforcement",
        "prompt": "do something",
        "expected_decision": "ALLOW",
    }])
    errors = v.validate_scenario(scenario)
    assert any(e.error_type == "ENFORCEMENT_WITH_PROMPT" for e in errors)


# ---------------------------------------------------------------------------
# (a) Agent existence
# ---------------------------------------------------------------------------


def test_unknown_bedrock_agent_errors(sv):
    v = _make_validator(sv, discovered={"agent-known"})
    scenario = _scenario([{
        "id": "s1", "cloud": "bedrock", "agent_id": "agent-unknown",
        "intent": "enforcement", "tool": "query_customers", "tool_params": {"state": "CA"},
        "expected_decision": "ALLOW",
    }])
    errors = v.validate_scenario(scenario)
    assert any(e.error_type == "UNKNOWN_BEDROCK_AGENT" for e in errors)


def test_unknown_azure_agent_errors(sv):
    v = _make_validator(
        sv,
        azure_tools=["check_fraud_score"],
        azure_agent_exists=lambda agent_id: False,
    )
    scenario = _scenario([{
        "id": "s1", "cloud": "azure_foundry", "agent_id": "azure-unknown",
        "intent": "enforcement",
        "tool": "check_fraud_score", "tool_params": {"transaction_id": "tx-1"},
        "expected_decision": "ALLOW",
    }])
    errors = v.validate_scenario(scenario)
    assert any(e.error_type == "UNKNOWN_AZURE_AGENT" for e in errors)


# ---------------------------------------------------------------------------
# (b) Tool existence
# ---------------------------------------------------------------------------


def test_unknown_bedrock_tool_errors(sv):
    v = _make_validator(sv, bedrock_schemas={"agent-x": _CUSTOMER_SVC_SCHEMA}, discovered={"agent-x"})
    scenario = _scenario([{
        "id": "s1", "cloud": "bedrock", "agent_id": "agent-x",
        "intent": "enforcement",
        "tool": "bogus_tool", "tool_params": {},
        "expected_decision": "ALLOW",
    }])
    errors = v.validate_scenario(scenario)
    assert any(e.error_type == "UNKNOWN_TOOL" for e in errors)


def test_unknown_azure_tool_errors(sv):
    v = _make_validator(sv, azure_tools=["check_fraud_score"])
    scenario = _scenario([{
        "id": "s1", "cloud": "azure_foundry", "agent_id": "azure-verification-agent",
        "intent": "enforcement",
        "tool": "bogus_azure_tool", "tool_params": {},
        "expected_decision": "ALLOW",
    }])
    errors = v.validate_scenario(scenario)
    assert any(e.error_type == "UNKNOWN_AZURE_TOOL" for e in errors)


# ---------------------------------------------------------------------------
# (c) Required params
# ---------------------------------------------------------------------------


def test_missing_required_param_errors(sv):
    v = _make_validator(sv, bedrock_schemas={"agent-x": _CUSTOMER_SVC_SCHEMA}, discovered={"agent-x"})
    scenario = _scenario([{
        "id": "s1", "cloud": "bedrock", "agent_id": "agent-x",
        "intent": "enforcement",
        "tool": "process_refund",
        "tool_params": {"order_id": "ORD-1"},  # missing 'amount'
        "expected_decision": "ALLOW",
    }])
    errors = v.validate_scenario(scenario)
    assert any(e.error_type == "MISSING_REQUIRED_PARAM" and "amount" in e.message for e in errors)


def test_unknown_param_errors(sv):
    v = _make_validator(sv, bedrock_schemas={"agent-x": _CUSTOMER_SVC_SCHEMA}, discovered={"agent-x"})
    scenario = _scenario([{
        "id": "s1", "cloud": "bedrock", "agent_id": "agent-x",
        "intent": "enforcement",
        "tool": "query_customers",
        "tool_params": {"state": "CA", "extra_typo": "boom"},
        "expected_decision": "ALLOW",
    }])
    errors = v.validate_scenario(scenario)
    assert any(e.error_type == "UNKNOWN_PARAM" for e in errors)


# ---------------------------------------------------------------------------
# (d) Param type mismatch
# ---------------------------------------------------------------------------


def test_int_param_supplied_as_non_numeric_string_errors(sv):
    v = _make_validator(sv, bedrock_schemas={"agent-x": _CUSTOMER_SVC_SCHEMA}, discovered={"agent-x"})
    scenario = _scenario([{
        "id": "s1", "cloud": "bedrock", "agent_id": "agent-x",
        "intent": "enforcement",
        "tool": "process_refund",
        "tool_params": {"order_id": "ORD-1", "amount": "not-a-number"},
        "expected_decision": "ALLOW",
    }])
    errors = v.validate_scenario(scenario)
    assert any(e.error_type == "PARAM_TYPE_MISMATCH" for e in errors)


def test_numeric_string_for_number_param_accepted(sv):
    v = _make_validator(sv, bedrock_schemas={"agent-x": _CUSTOMER_SVC_SCHEMA}, discovered={"agent-x"})
    scenario = _scenario([{
        "id": "s1", "cloud": "bedrock", "agent_id": "agent-x",
        "intent": "enforcement",
        "tool": "process_refund",
        "tool_params": {"order_id": "ORD-1", "amount": "50.0"},
        "expected_decision": "ALLOW",
    }])
    # "50.0" coerces fine; no PARAM_TYPE_MISMATCH
    errors = v.validate_scenario(scenario)
    assert all(e.error_type != "PARAM_TYPE_MISMATCH" for e in errors)


def test_template_token_in_typed_param_skips_runtime_typecheck(sv):
    """Templated string values like '{rand.uuid}' must defer typecheck to runtime."""
    v = _make_validator(sv, bedrock_schemas={"agent-x": _CUSTOMER_SVC_SCHEMA}, discovered={"agent-x"})
    scenario = _scenario([{
        "id": "s1", "cloud": "bedrock", "agent_id": "agent-x",
        "intent": "enforcement",
        "tool": "process_refund",
        "tool_params": {"order_id": "{rand.order_id}", "amount": "{rand.uuid}"},
        "expected_decision": "ALLOW",
    }])
    # No PARAM_TYPE_MISMATCH despite amount looking non-numeric — it's templated
    errors = v.validate_scenario(scenario)
    assert all(e.error_type != "PARAM_TYPE_MISMATCH" for e in errors)


# ---------------------------------------------------------------------------
# (e) Unknown template tokens
# ---------------------------------------------------------------------------


def test_unknown_template_token_errors(sv):
    v = _make_validator(sv, bedrock_schemas={"agent-x": _CUSTOMER_SVC_SCHEMA}, discovered={"agent-x"})
    scenario = _scenario([{
        "id": "s1", "cloud": "bedrock", "agent_id": "agent-x",
        "intent": "enforcement",
        "tool": "query_customers",
        "tool_params": {"state": "{rand.something_bogus}"},
        "expected_decision": "ALLOW",
    }])
    errors = v.validate_scenario(scenario)
    assert any(e.error_type == "UNKNOWN_TEMPLATE_TOKEN" for e in errors)


def test_known_template_token_passes(sv):
    v = _make_validator(sv, bedrock_schemas={"agent-x": _CUSTOMER_SVC_SCHEMA}, discovered={"agent-x"})
    scenario = _scenario([{
        "id": "s1", "cloud": "bedrock", "agent_id": "agent-x",
        "intent": "enforcement",
        "tool": "query_customers",
        "tool_params": {"state": "{rand.state}"},
        "user_input": "request {request_id}",
        "expected_decision": "ALLOW",
    }])
    errors = v.validate_scenario(scenario)
    assert all(e.error_type != "UNKNOWN_TEMPLATE_TOKEN" for e in errors)


# ---------------------------------------------------------------------------
# Shape checks
# ---------------------------------------------------------------------------


def test_invalid_cloud_errors(sv):
    v = _make_validator(sv)
    scenario = _scenario([{
        "id": "s1", "cloud": "gcp_vertex", "agent_id": "a",
        "intent": "enforcement", "tool": "x", "tool_params": {},
        "expected_decision": "ALLOW",
    }])
    errors = v.validate_scenario(scenario)
    assert any(e.error_type == "INVALID_CLOUD" for e in errors)


def test_missing_tool_or_prompt_errors(sv):
    v = _make_validator(sv, discovered={"agent-x"})
    scenario = _scenario([{
        "id": "s1", "cloud": "bedrock", "agent_id": "agent-x",
        "intent": "enforcement",
        "expected_decision": "ALLOW",
    }])
    errors = v.validate_scenario(scenario)
    assert any(e.error_type == "MISSING_TOOL_OR_PROMPT" for e in errors)


def test_empty_steps_errors(sv):
    v = _make_validator(sv)
    scenario = {"scenario_id": "s", "cross_cloud": {"story": "test", "steps": []}}
    errors = v.validate_scenario(scenario)
    assert any(e.error_type == "EMPTY_STEPS" for e in errors)


def test_no_cross_cloud_block_returns_clean(sv):
    """Scenarios without a cross_cloud block aren't WS18 scenarios; pass clean."""
    v = _make_validator(sv)
    scenario = {"scenario_id": "old_s", "prompts": [{"id": "p", "text": "x"}]}
    assert v.validate_scenario(scenario) == []


# ---------------------------------------------------------------------------
# Fetcher failures (graceful)
# ---------------------------------------------------------------------------


def test_bedrock_schema_fetch_failure_surfaces_error(sv):
    """Schema fetcher exception → BEDROCK_SCHEMA_FETCH_FAILED, not a crash."""
    v = _make_validator(sv, discovered={"agent-not-fetched"})
    scenario = _scenario([{
        "id": "s1", "cloud": "bedrock", "agent_id": "agent-not-fetched",
        "intent": "enforcement",
        "tool": "query_customers", "tool_params": {"state": "CA"},
        "expected_decision": "ALLOW",
    }])
    errors = v.validate_scenario(scenario)
    assert any(e.error_type == "BEDROCK_SCHEMA_FETCH_FAILED" for e in errors)


def test_azure_tools_fetch_failure_surfaces_error(sv):
    v = _make_validator(sv, azure_raises=True)
    scenario = _scenario([{
        "id": "s1", "cloud": "azure_foundry", "agent_id": "azure-x",
        "intent": "enforcement",
        "tool": "check_fraud_score", "tool_params": {"transaction_id": "tx-1"},
        "expected_decision": "ALLOW",
    }])
    errors = v.validate_scenario(scenario)
    assert any(e.error_type == "AZURE_TOOLS_FETCH_FAILED" for e in errors)


# ---------------------------------------------------------------------------
# Multiple errors per step
# ---------------------------------------------------------------------------


def test_multiple_errors_collected_not_short_circuited(sv):
    """One bad step yields multiple errors — validator doesn't bail on first."""
    v = _make_validator(sv, bedrock_schemas={"agent-x": _CUSTOMER_SVC_SCHEMA}, discovered={"agent-x"})
    scenario = _scenario([{
        "id": "s1", "cloud": "bedrock", "agent_id": "agent-x",
        # Missing intent
        # Templated unknown token
        "tool": "query_customers", "tool_params": {"state": "{rand.bogus}"},
        "expected_decision": "ALLOW",
    }])
    errors = v.validate_scenario(scenario)
    error_types = {e.error_type for e in errors}
    assert "MISSING_INTENT" in error_types
    assert "UNKNOWN_TEMPLATE_TOKEN" in error_types


# ---------------------------------------------------------------------------
# is_strict_mode + report_and_maybe_exit
# ---------------------------------------------------------------------------


def test_strict_mode_default_true(sv, monkeypatch):
    monkeypatch.delenv("SCENARIO_VALIDATION_STRICT", raising=False)
    assert sv.is_strict_mode() is True


def test_strict_mode_explicit_false(sv, monkeypatch):
    monkeypatch.setenv("SCENARIO_VALIDATION_STRICT", "false")
    assert sv.is_strict_mode() is False


def test_strict_mode_explicit_true(sv, monkeypatch):
    monkeypatch.setenv("SCENARIO_VALIDATION_STRICT", "true")
    assert sv.is_strict_mode() is True


def test_report_and_maybe_exit_strict_raises(sv, monkeypatch):
    monkeypatch.setenv("SCENARIO_VALIDATION_STRICT", "true")
    errors = [sv.ValidationError(
        scenario_id="s", step_id="x", error_type="TEST",
        message="bad",
    )]
    with pytest.raises(SystemExit):
        sv.report_and_maybe_exit(errors)


def test_report_and_maybe_exit_permissive_does_not_raise(sv, monkeypatch):
    monkeypatch.setenv("SCENARIO_VALIDATION_STRICT", "false")
    errors = [sv.ValidationError(
        scenario_id="s", step_id="x", error_type="TEST",
        message="bad",
    )]
    sv.report_and_maybe_exit(errors)  # should not raise


def test_report_and_maybe_exit_no_errors_does_not_raise(sv, monkeypatch):
    monkeypatch.setenv("SCENARIO_VALIDATION_STRICT", "true")
    sv.report_and_maybe_exit([])  # should not raise — nothing to report
