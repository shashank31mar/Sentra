"""Unit tests for CrossCloudScenarioRunner — Workstream 15 M5.

The runner is intentionally Streamlit-free, so these tests exercise it
directly with fake invokers. We cover:

  - Step routing (bedrock prompt / azure tool / azure prompt) picks the right invoker
  - Decision-vs-expectation classification (PASSED, FAILED, ERRORED)
  - expected_reason_contains matching (case-insensitive)
  - Session-id propagation across all steps (S3 critical path)
  - S2 policy-apply hook fires at the correct step and reverts at the end
  - Outcome aggregation (deny_count, allow_count, error_count, cloud_count, elapsed_ms)
  - Outcome template formatting with full + partial substitutions
  - Defensive handling of malformed scenarios (no cross_cloud block, unknown cloud, missing tool/prompt)

The runner imports CrossCloudStep/Scenario from the demo-orchestrator package;
we mount that on sys.path here too.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_DIR = REPO_ROOT / "src" / "dashboard"
DASHBOARD_COMPONENTS = DASHBOARD_DIR / "components"
RUNNER_PATH = DASHBOARD_COMPONENTS / "cross_cloud_scenarios.py"


def _load_runner():
    # Models live inline in cross_cloud_scenarios.py so we don't trigger
    # components/__init__.py (which eagerly imports streamlit-dependent
    # modules). Load the runner file standalone.
    spec = importlib.util.spec_from_file_location("ccs_under_test", RUNNER_PATH)
    module = importlib.util.module_from_spec(spec)
    # Python 3.12 dataclasses resolve forward-refs via sys.modules[cls.__module__]
    # — register the loaded module before executing so dataclass field types
    # resolve on first instantiation.
    sys.modules["ccs_under_test"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def runner_mod():
    return _load_runner()


@pytest.fixture
def CrossCloudStep(runner_mod):
    return runner_mod.CrossCloudStep


@pytest.fixture
def Scenario(runner_mod):
    return runner_mod.Scenario


def _scenario(Scenario, *, scenario_id="t1", steps=None, outcome_template=None):
    cc = {
        "story": "test",
        "outcome_template": outcome_template,
        "steps": steps or [],
    }
    return Scenario(
        scenario_id=scenario_id,
        name="t",
        description="",
        mode="manual",
        agents={"bedrock": ["b"], "azure_foundry": ["a"]},
        prompts=[],
        cross_cloud=cc,
    )


def _outcome_factory(runner_mod):
    return runner_mod._InvocationOutcome


# ---------------------------------------------------------------------------
# 1. step routing
# ---------------------------------------------------------------------------


def test_bedrock_prompt_step_uses_bedrock_invoker(runner_mod, Scenario):
    Out = _outcome_factory(runner_mod)
    calls = {"bedrock": 0, "azure_p": 0, "azure_t": 0}

    def bedrock(step, sid):
        calls["bedrock"] += 1
        return Out(decision="ALLOW", reason="ok", latency_ms=10, raw={})

    def azure_p(step, sid):
        calls["azure_p"] += 1
        return Out(decision="ALLOW", reason=None, latency_ms=10, raw={})

    def azure_t(step, sid):
        calls["azure_t"] += 1
        return Out(decision="ALLOW", reason=None, latency_ms=10, raw={})

    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=bedrock,
        azure_prompt_invoker=azure_p,
        azure_tool_invoker=azure_t,
    )
    scen = _scenario(Scenario, steps=[
        {"id": "s1", "cloud": "bedrock", "agent_id": "x", "prompt": "hi", "expected_decision": "ALLOW"},
    ])
    list(runner.run(scen, session_id="sess-1"))
    assert calls == {"bedrock": 1, "azure_p": 0, "azure_t": 0}


def test_azure_tool_step_uses_tool_invoker(runner_mod, Scenario):
    Out = _outcome_factory(runner_mod)
    calls = {"tool": 0, "prompt": 0}

    def azure_prompt(step, sid):
        calls["prompt"] += 1
        return Out(decision="ALLOW", reason=None, latency_ms=10, raw={})

    def azure_tool(step, sid):
        calls["tool"] += 1
        return Out(decision="ALLOW", reason=None, latency_ms=5, raw={})

    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=0, raw={}),
        azure_prompt_invoker=azure_prompt,
        azure_tool_invoker=azure_tool,
    )
    scen = _scenario(Scenario, steps=[
        {"id": "s1", "cloud": "azure_foundry", "agent_id": "a", "tool": "check_fraud_score",
         "tool_params": {"transaction_id": "tx-1"}, "expected_decision": "ALLOW"},
    ])
    list(runner.run(scen, session_id="sess-1"))
    assert calls == {"tool": 1, "prompt": 0}


def test_azure_prompt_step_uses_prompt_invoker(runner_mod, Scenario):
    Out = _outcome_factory(runner_mod)
    calls = {"tool": 0, "prompt": 0}

    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=0, raw={}),
        azure_prompt_invoker=lambda *a, **k: (calls.__setitem__("prompt", calls["prompt"] + 1), Out(decision="DENY", reason="x", latency_ms=2, raw={}))[1],
        azure_tool_invoker=lambda *a, **k: (calls.__setitem__("tool", calls["tool"] + 1), Out(decision="ALLOW", reason=None, latency_ms=2, raw={}))[1],
    )
    scen = _scenario(Scenario, steps=[
        {"id": "s1", "cloud": "azure_foundry", "agent_id": "a", "prompt": "hello", "expected_decision": "DENY"},
    ])
    list(runner.run(scen, session_id="sess-1"))
    assert calls == {"tool": 0, "prompt": 1}


# ---------------------------------------------------------------------------
# 2. classification
# ---------------------------------------------------------------------------


def test_passes_when_decision_matches_expectation(runner_mod, Scenario):
    Out = _outcome_factory(runner_mod)
    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=lambda s, sid: Out(decision="DENY", reason="blocked", latency_ms=5, raw={}),
        azure_prompt_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=5, raw={}),
        azure_tool_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=5, raw={}),
    )
    scen = _scenario(Scenario, steps=[
        {"id": "s1", "cloud": "bedrock", "agent_id": "x", "prompt": "atk", "expected_decision": "DENY"},
    ])
    results = list(runner.run(scen))
    assert results[0].status == runner_mod.StepStatus.PASSED
    assert results[0].actual_decision == "DENY"


def test_fails_when_decision_mismatches(runner_mod, Scenario):
    Out = _outcome_factory(runner_mod)
    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=lambda s, sid: Out(decision="ALLOW", reason="oops", latency_ms=5, raw={}),
        azure_prompt_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=5, raw={}),
        azure_tool_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=5, raw={}),
    )
    scen = _scenario(Scenario, steps=[
        {"id": "s1", "cloud": "bedrock", "agent_id": "x", "prompt": "atk", "expected_decision": "DENY"},
    ])
    results = list(runner.run(scen))
    assert results[0].status == runner_mod.StepStatus.FAILED


def test_fails_when_reason_substring_absent(runner_mod, Scenario):
    Out = _outcome_factory(runner_mod)
    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=lambda s, sid: Out(decision="DENY", reason="some other reason", latency_ms=5, raw={}),
        azure_prompt_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=5, raw={}),
        azure_tool_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=5, raw={}),
    )
    scen = _scenario(Scenario, steps=[
        {"id": "s1", "cloud": "bedrock", "agent_id": "x", "prompt": "atk",
         "expected_decision": "DENY", "expected_reason_contains": "sql_injection"},
    ])
    results = list(runner.run(scen))
    assert results[0].status == runner_mod.StepStatus.FAILED


def test_passes_with_case_insensitive_reason_match(runner_mod, Scenario):
    Out = _outcome_factory(runner_mod)
    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=lambda s, sid: Out(decision="DENY", reason="Blocked: SQL_Injection signature", latency_ms=5, raw={}),
        azure_prompt_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=5, raw={}),
        azure_tool_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=5, raw={}),
    )
    scen = _scenario(Scenario, steps=[
        {"id": "s1", "cloud": "bedrock", "agent_id": "x", "prompt": "atk",
         "expected_decision": "DENY", "expected_reason_contains": "sql_injection"},
    ])
    results = list(runner.run(scen))
    assert results[0].status == runner_mod.StepStatus.PASSED


def test_errored_status_when_invoker_returns_error(runner_mod, Scenario):
    Out = _outcome_factory(runner_mod)
    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=lambda s, sid: Out(decision="ERROR", reason="boom", latency_ms=0, raw={}, error="boom"),
        azure_prompt_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=5, raw={}),
        azure_tool_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=5, raw={}),
    )
    scen = _scenario(Scenario, steps=[
        {"id": "s1", "cloud": "bedrock", "agent_id": "x", "prompt": "atk", "expected_decision": "DENY"},
    ])
    results = list(runner.run(scen))
    assert results[0].status == runner_mod.StepStatus.ERRORED
    assert results[0].error == "boom"


def test_errored_status_when_invoker_raises(runner_mod, Scenario):
    Out = _outcome_factory(runner_mod)

    def kaboom(step, sid):
        raise RuntimeError("network exploded")

    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=kaboom,
        azure_prompt_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=5, raw={}),
        azure_tool_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=5, raw={}),
    )
    scen = _scenario(Scenario, steps=[
        {"id": "s1", "cloud": "bedrock", "agent_id": "x", "prompt": "atk", "expected_decision": "DENY"},
    ])
    results = list(runner.run(scen))
    assert results[0].status == runner_mod.StepStatus.ERRORED
    assert "network exploded" in results[0].error


# ---------------------------------------------------------------------------
# 3. session_id propagation (critical for S3)
# ---------------------------------------------------------------------------


def test_session_id_is_passed_to_every_invoker(runner_mod, Scenario):
    Out = _outcome_factory(runner_mod)
    seen = []

    def capture(step, sid):
        seen.append((step.id, sid))
        return Out(decision="ALLOW", reason=None, latency_ms=1, raw={})

    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=capture,
        azure_prompt_invoker=capture,
        azure_tool_invoker=capture,
    )
    scen = _scenario(Scenario, steps=[
        {"id": "azure_first", "cloud": "azure_foundry", "agent_id": "a",
         "tool": "verify_image_authenticity", "tool_params": {}, "expected_decision": "ALLOW"},
        {"id": "bedrock_next", "cloud": "bedrock", "agent_id": "b",
         "prompt": "refund", "expected_decision": "ALLOW"},
    ])
    list(runner.run(scen, session_id="s3-shared-sess"))
    assert seen == [
        ("azure_first", "s3-shared-sess"),
        ("bedrock_next", "s3-shared-sess"),
    ], "all steps must run under the same session_id (S3 cross-cloud precondition)"


def test_session_id_auto_generated_when_not_provided(runner_mod, Scenario):
    Out = _outcome_factory(runner_mod)
    seen = []

    def capture(step, sid):
        seen.append(sid)
        return Out(decision="ALLOW", reason=None, latency_ms=1, raw={})

    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=capture,
        azure_prompt_invoker=capture,
        azure_tool_invoker=capture,
    )
    scen = _scenario(Scenario, steps=[
        {"id": "x", "cloud": "bedrock", "agent_id": "b", "prompt": "p", "expected_decision": "ALLOW"},
        {"id": "y", "cloud": "bedrock", "agent_id": "b", "prompt": "p", "expected_decision": "ALLOW"},
    ])
    list(runner.run(scen))
    assert seen[0] == seen[1], "auto-generated session_id must be the same across steps"
    assert seen[0].startswith("xcloud-"), "auto session_id must use the xcloud- prefix"


# ---------------------------------------------------------------------------
# 4. S2 policy-apply hook
# ---------------------------------------------------------------------------


def test_policy_apply_fires_at_configured_step_and_reverts_at_end(runner_mod, Scenario):
    Out = _outcome_factory(runner_mod)
    events: list[tuple[str, ...]] = []

    def policy_apply(argv):
        # Capture --remove-tool vs --add-tool sequence.
        if "--remove-tool" in argv:
            events.append(("remove", argv[argv.index("--remove-tool") + 1]))
        elif "--add-tool" in argv:
            events.append(("add", argv[argv.index("--add-tool") + 1]))
        return {"version": "1.0.1"}

    def step_invoker(step, sid):
        events.append(("step", step.id))
        return Out(decision=step.expected_decision, reason=None, latency_ms=1, raw={})

    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=step_invoker,
        azure_prompt_invoker=step_invoker,
        azure_tool_invoker=step_invoker,
        policy_apply_fn=policy_apply,
        policy_propagation_step_ids=("after",),
        policy_remove_tool="query_customers",
        policy_agent_id="sentra-mvp-customer-service-agent",
    )
    scen = _scenario(Scenario, steps=[
        {"id": "before", "cloud": "bedrock", "agent_id": "b", "prompt": "q", "expected_decision": "ALLOW"},
        {"id": "after", "cloud": "bedrock", "agent_id": "b", "prompt": "q", "expected_decision": "DENY"},
    ])
    list(runner.run(scen))
    assert events == [
        ("step", "before"),
        ("remove", "query_customers"),
        ("step", "after"),
        ("add", "query_customers"),
    ]


def test_policy_apply_does_not_fire_when_hook_unconfigured(runner_mod, Scenario):
    Out = _outcome_factory(runner_mod)
    events: list[tuple[str, ...]] = []

    def policy_apply(argv):
        events.append(("policy", tuple(argv)))
        return {}

    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=lambda s, sid: Out(decision="ALLOW", reason=None, latency_ms=1, raw={}),
        azure_prompt_invoker=lambda s, sid: Out(decision="ALLOW", reason=None, latency_ms=1, raw={}),
        azure_tool_invoker=lambda s, sid: Out(decision="ALLOW", reason=None, latency_ms=1, raw={}),
        policy_apply_fn=policy_apply,
        # No matching step_ids — hook should never trigger.
        policy_propagation_step_ids=(),
    )
    scen = _scenario(Scenario, steps=[
        {"id": "after", "cloud": "bedrock", "agent_id": "b", "prompt": "q", "expected_decision": "ALLOW"},
    ])
    list(runner.run(scen))
    assert events == []


def test_policy_apply_failure_surfaces_synthetic_step(runner_mod, Scenario):
    Out = _outcome_factory(runner_mod)

    def policy_apply(argv):
        if "--remove-tool" in argv:
            raise RuntimeError("controller 502")
        return {}

    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=lambda s, sid: Out(decision="ALLOW", reason=None, latency_ms=1, raw={}),
        azure_prompt_invoker=lambda s, sid: Out(decision="ALLOW", reason=None, latency_ms=1, raw={}),
        azure_tool_invoker=lambda s, sid: Out(decision="ALLOW", reason=None, latency_ms=1, raw={}),
        policy_apply_fn=policy_apply,
        policy_propagation_step_ids=("after",),
        policy_remove_tool="t",
        policy_agent_id="a",
    )
    scen = _scenario(Scenario, steps=[
        {"id": "after", "cloud": "bedrock", "agent_id": "b", "prompt": "q", "expected_decision": "ALLOW"},
    ])
    results = list(runner.run(scen))
    # Synthetic step is named per agent so the UI surfaces which cloud the
    # propagation broke on (multi-agent hook 2026-05-26).
    assert results[0].step_id == "_policy_update__a"
    assert results[0].status == runner_mod.StepStatus.ERRORED
    assert "controller 502" in results[0].error


def test_policy_updates_list_fires_for_each_agent_and_reverts_in_reverse(runner_mod, Scenario):
    """Multi-agent S2: the hook must update every agent in policy_updates and
    teardown in reverse order so the runner can demo cross-cloud propagation
    (one control plane, N cloud-native agents)."""
    Out = _outcome_factory(runner_mod)
    events: list[tuple[str, ...]] = []

    def policy_apply(argv):
        op = "remove" if "--remove-tool" in argv else "add"
        agent_idx = argv.index("--agent-id") + 1
        tool_flag = "--remove-tool" if op == "remove" else "--add-tool"
        tool_idx = argv.index(tool_flag) + 1
        events.append((op, argv[agent_idx], argv[tool_idx]))
        return {"version": "1.0.1"}

    def step_invoker(step, sid):
        events.append(("step", step.id, ""))
        return Out(decision=step.expected_decision, reason=None, latency_ms=1, raw={})

    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=step_invoker,
        azure_prompt_invoker=step_invoker,
        azure_tool_invoker=step_invoker,
        policy_apply_fn=policy_apply,
        policy_propagation_step_ids=("after",),
        policy_updates=[
            {"agent_id": "agent-aws", "remove_tool": "tool_a"},
            {"agent_id": "agent-azure", "remove_tool": "tool_b"},
        ],
    )
    scen = _scenario(Scenario, steps=[
        {"id": "before", "cloud": "bedrock", "agent_id": "b", "prompt": "q", "expected_decision": "ALLOW"},
        {"id": "after", "cloud": "bedrock", "agent_id": "b", "prompt": "q", "expected_decision": "DENY"},
    ])
    list(runner.run(scen))
    assert events == [
        ("step", "before", ""),
        ("remove", "agent-aws", "tool_a"),
        ("remove", "agent-azure", "tool_b"),
        ("step", "after", ""),
        # Teardown runs in reverse order.
        ("add", "agent-azure", "tool_b"),
        ("add", "agent-aws", "tool_a"),
    ]


def test_policy_updates_partial_failure_continues_remaining_updates(runner_mod, Scenario):
    """If the first agent's policy update raises, the runner must still try
    the remaining agents and surface a synthetic step per failed agent."""
    Out = _outcome_factory(runner_mod)
    events: list[tuple[str, ...]] = []

    def policy_apply(argv):
        agent = argv[argv.index("--agent-id") + 1]
        if "--remove-tool" in argv and agent == "agent-aws":
            raise RuntimeError("controller 502 for aws")
        events.append((argv[1], agent))
        return {}

    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=lambda s, sid: Out(decision="ALLOW", reason=None, latency_ms=1, raw={}),
        azure_prompt_invoker=lambda s, sid: Out(decision="ALLOW", reason=None, latency_ms=1, raw={}),
        azure_tool_invoker=lambda s, sid: Out(decision="ALLOW", reason=None, latency_ms=1, raw={}),
        policy_apply_fn=policy_apply,
        policy_propagation_step_ids=("after",),
        policy_updates=[
            {"agent_id": "agent-aws", "remove_tool": "tool_a"},
            {"agent_id": "agent-azure", "remove_tool": "tool_b"},
        ],
    )
    scen = _scenario(Scenario, steps=[
        {"id": "after", "cloud": "bedrock", "agent_id": "b", "prompt": "q", "expected_decision": "ALLOW"},
    ])
    results = list(runner.run(scen))
    # First result is the synthetic failed step for agent-aws.
    assert results[0].step_id == "_policy_update__agent-aws"
    assert results[0].status == runner_mod.StepStatus.ERRORED
    # agent-azure's remove + teardown adds for both still ran.
    assert ("--agent-id", "agent-azure") in [(a, b) for a, b in events if a == "--agent-id"] or any(
        a == "agent-azure" for _, a in events
    )


# ---------------------------------------------------------------------------
# 5. outcome aggregation + templating
# ---------------------------------------------------------------------------


def test_summarize_aggregates_decisions_and_clouds(runner_mod, Scenario):
    started = runner_mod._now_iso()
    time.sleep(0.01)
    steps = [
        runner_mod.StepResult(
            step_id="a", cloud="bedrock", agent_id="x", description="", expected_decision="DENY",
            status=runner_mod.StepStatus.PASSED, actual_decision="DENY", reason="r", latency_ms=10,
            started_at=started, finished_at=runner_mod._now_iso(),
        ),
        runner_mod.StepResult(
            step_id="b", cloud="azure_foundry", agent_id="y", description="", expected_decision="ALLOW",
            status=runner_mod.StepStatus.PASSED, actual_decision="ALLOW", reason=None, latency_ms=5,
            started_at=started, finished_at=runner_mod._now_iso(),
        ),
    ]
    scen = _scenario(
        Scenario,
        scenario_id="t",
        outcome_template="{deny_count} blocked, {allow_count} allowed across {cloud_count} clouds in {elapsed_ms}ms (total {total})",
        steps=[],
    )
    outcome = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=lambda *a, **k: None,
        azure_prompt_invoker=lambda *a, **k: None,
        azure_tool_invoker=lambda *a, **k: None,
    ).summarize(scen, "sess-x", steps, started_at=started)
    assert outcome.total == 2
    assert outcome.deny_count == 1
    assert outcome.allow_count == 1
    assert outcome.cloud_count == 2
    assert outcome.passed is True
    assert "1 blocked, 1 allowed across 2 clouds in" in outcome.narrative


def test_outcome_template_missing_key_falls_back(runner_mod, Scenario):
    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=lambda *a, **k: None,
        azure_prompt_invoker=lambda *a, **k: None,
        azure_tool_invoker=lambda *a, **k: None,
    )
    scen = _scenario(Scenario, outcome_template="{undefined_key}")
    outcome = runner.summarize(
        scen, "sess", [], started_at=runner_mod._now_iso(),
    )
    # Narrative should NOT raise; fallback contains 'deny' wording.
    assert "deny" in outcome.narrative.lower()


def test_passed_false_when_any_step_failed(runner_mod, Scenario):
    started = runner_mod._now_iso()
    steps = [
        runner_mod.StepResult(
            step_id="a", cloud="bedrock", agent_id="x", description="", expected_decision="DENY",
            status=runner_mod.StepStatus.PASSED, actual_decision="DENY", reason=None, latency_ms=1,
            started_at=started, finished_at=runner_mod._now_iso(),
        ),
        runner_mod.StepResult(
            step_id="b", cloud="azure_foundry", agent_id="y", description="", expected_decision="ALLOW",
            status=runner_mod.StepStatus.FAILED, actual_decision="DENY", reason="oops", latency_ms=1,
            started_at=started, finished_at=runner_mod._now_iso(),
        ),
    ]
    scen = _scenario(Scenario)
    outcome = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=lambda *a, **k: None,
        azure_prompt_invoker=lambda *a, **k: None,
        azure_tool_invoker=lambda *a, **k: None,
    ).summarize(scen, "sess", steps, started_at=started)
    assert outcome.passed is False


# ---------------------------------------------------------------------------
# 6. audit-log decision override (critical: Bedrock guardrail-misses → Sentra DENY)
# ---------------------------------------------------------------------------


# NOTE: 2 legacy `audit_lookup_fn` tests were removed here in Workstream 18
# M3.6 (LLD 18 §9.3). The functional coverage moved to the decisions_lookup_fn
# tests below — same override semantics, DDB-backed rather than CloudWatch.


# ---------------------------------------------------------------------------
# Workstream 17 — decisions_lookup_fn (DDB-backed override path)
# ---------------------------------------------------------------------------


def test_decisions_lookup_overrides_invoker_with_combined_deny(runner_mod, Scenario):
    """Workstream 17 / LLD 17 §9.2 — invoker says ALLOW, controller's combined
    verdict from /v1/sessions/{id}/decisions says DENY → row shows DENY with
    winning_source mapped to the UI source taxonomy."""
    Out = _outcome_factory(runner_mod)
    lookup_calls: list[tuple[str, str]] = []

    def decisions_lookup(sid, rid):
        lookup_calls.append((sid, rid))
        return {
            "request_id": rid,
            "combined": {
                "decision": "DENY",
                "reason": "Threat detected: PII_EXPOSURE",
                "winning_source": "sentra.sigma",
            },
            "signals": [
                {"source": "sentra.sigma", "decision": "DENY", "reason": "PII_EXPOSURE"},
                {"source": "sentra.trust", "decision": "ALLOW"},
            ],
        }

    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=lambda s, sid: Out(decision="ALLOW", reason="No guardrail", latency_ms=5, raw={}),
        azure_prompt_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=5, raw={}),
        azure_tool_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=5, raw={}),
        decisions_lookup_fn=decisions_lookup,
    )
    scen = _scenario(Scenario, steps=[
        {"id": "atk", "cloud": "bedrock", "agent_id": "naive-agent",
         "prompt": "PII attack", "expected_decision": "DENY"},
    ])
    results = list(runner.run(scen, session_id="sess-w17"))
    # lookup called once with (session_id, request_id) — request_id is
    # runner-generated so we just verify shape
    assert len(lookup_calls) == 1
    sid, rid = lookup_calls[0]
    assert sid == "sess-w17"
    assert rid.startswith("xc-atk-"), f"runner-generated rid expected, got {rid}"
    # Decision and attribution
    assert results[0].actual_decision == "DENY"
    assert results[0].decision_source == "sentra"
    # Signals copied to StepResult for UI expander
    assert len(results[0].signals) == 2
    assert {s["source"] for s in results[0].signals} == {"sentra.sigma", "sentra.trust"}


def test_decisions_lookup_attributes_bedrock_guardrail_win(runner_mod, Scenario):
    """When the winning_source is bedrock_guardrail, UI source attribution
    must reflect that — investors see who actually blocked the request."""
    Out = _outcome_factory(runner_mod)

    def decisions_lookup(sid, rid):
        return {
            "request_id": rid,
            "combined": {
                "decision": "DENY",
                "reason": "Hate speech",
                "winning_source": "bedrock_guardrail",
            },
            "signals": [],
        }

    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=lambda s, sid: Out(decision="ALLOW", reason=None, latency_ms=5, raw={}),
        azure_prompt_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=5, raw={}),
        azure_tool_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=5, raw={}),
        decisions_lookup_fn=decisions_lookup,
    )
    scen = _scenario(Scenario, steps=[
        {"id": "s1", "cloud": "bedrock", "agent_id": "a", "prompt": "p", "expected_decision": "DENY"},
    ])
    results = list(runner.run(scen))
    assert results[0].decision_source == "bedrock_guardrail"


def test_decisions_lookup_missing_preserves_invoker_view(runner_mod, Scenario):
    """decisions_lookup returns None → invoker view stands. No exceptions."""
    Out = _outcome_factory(runner_mod)
    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=lambda s, sid: Out(decision="ALLOW", reason="ok", latency_ms=5, raw={}),
        azure_prompt_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=5, raw={}),
        azure_tool_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=5, raw={}),
        decisions_lookup_fn=lambda sid, rid: None,
    )
    scen = _scenario(Scenario, steps=[
        {"id": "s1", "cloud": "bedrock", "agent_id": "a", "prompt": "p", "expected_decision": "ALLOW"},
    ])
    results = list(runner.run(scen))
    assert results[0].actual_decision == "ALLOW"
    assert results[0].status == runner_mod.StepStatus.PASSED


# NOTE: 3 legacy audit_lookup_fn tests were removed in Workstream 18 M3.6:
#   - test_decisions_lookup_takes_precedence_over_audit_lookup (no other path
#     exists now; decisions_lookup is the only override)
#   - test_audit_log_lookup_exception_does_not_fail_step (decisions_lookup
#     equivalent in test_decisions_lookup_exception_does_not_fail_step above)
#   - test_audit_log_not_consulted_for_error_results (decisions_lookup
#     equivalent: ERROR outcomes still bypass decisions_lookup via the
#     `outcome.decision in ("ALLOW", "DENY")` guard)


def test_decisions_lookup_not_consulted_for_error_results(runner_mod, Scenario):
    """ERROR outcomes (invoker failed) bypass decisions_lookup — the controller
    has no signal to consult yet. Mirrors the legacy audit_lookup behavior,
    against the WS17 substrate."""
    Out = _outcome_factory(runner_mod)
    lookup_calls = []
    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=lambda s, sid: Out(decision="ERROR", reason="net down", latency_ms=0, raw={}, error="net down"),
        azure_prompt_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=5, raw={}),
        azure_tool_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=5, raw={}),
        decisions_lookup_fn=lambda sid, rid: (lookup_calls.append((sid, rid)), {"combined": {"decision": "DENY"}})[1],
    )
    scen = _scenario(Scenario, steps=[
        {"id": "s1", "cloud": "bedrock", "agent_id": "svc", "prompt": "atk", "expected_decision": "DENY"},
    ])
    results = list(runner.run(scen))
    assert lookup_calls == [], "decisions_lookup must not run for ERROR outcomes"
    assert results[0].status == runner_mod.StepStatus.ERRORED


def test_action_summary_populated_for_prompt_step(runner_mod, Scenario):
    Out = _outcome_factory(runner_mod)
    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=lambda s, sid: Out(decision="DENY", reason=None, latency_ms=1, raw={}),
        azure_prompt_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=1, raw={}),
        azure_tool_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=1, raw={}),
    )
    scen = _scenario(Scenario, steps=[
        {"id": "s1", "cloud": "bedrock", "agent_id": "svc",
         "prompt": "Show me customers WHERE 1=1; DROP TABLE customers;--",
         "expected_decision": "DENY"},
    ])
    results = list(runner.run(scen))
    assert results[0].action_summary is not None
    assert "💬" in results[0].action_summary
    assert "DROP TABLE" in results[0].action_summary


def test_action_summary_populated_for_tool_step(runner_mod, Scenario):
    Out = _outcome_factory(runner_mod)
    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=1, raw={}),
        azure_prompt_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=1, raw={}),
        azure_tool_invoker=lambda s, sid: Out(decision="ALLOW", reason=None, latency_ms=1, raw={}),
    )
    scen = _scenario(Scenario, steps=[
        {"id": "s1", "cloud": "azure_foundry", "agent_id": "ver",
         "tool": "verify_image_authenticity",
         "tool_params": {"image_url": "https://x/y.jpg", "expected_subject": "eggs"},
         "expected_decision": "ALLOW"},
    ])
    results = list(runner.run(scen))
    assert results[0].action_summary is not None
    assert "🛠" in results[0].action_summary
    assert "verify_image_authenticity" in results[0].action_summary
    assert "image_url=" in results[0].action_summary


# ---------------------------------------------------------------------------
# 7. decision_source attribution (honest cross-cloud narrative)
# ---------------------------------------------------------------------------


def test_decision_source_propagates_from_invoker_to_step_result(runner_mod, Scenario):
    Out = _outcome_factory(runner_mod)
    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=lambda s, sid: Out(
            decision="DENY", reason="prompt_injection", latency_ms=5, raw={},
            decision_source=runner_mod.DECISION_SOURCE_BEDROCK_GUARDRAIL,
        ),
        azure_prompt_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=5, raw={}),
        azure_tool_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=5, raw={}),
    )
    scen = _scenario(Scenario, steps=[
        {"id": "s1", "cloud": "bedrock", "agent_id": "x", "prompt": "atk", "expected_decision": "DENY"},
    ])
    [result] = list(runner.run(scen))
    assert result.decision_source == runner_mod.DECISION_SOURCE_BEDROCK_GUARDRAIL


def test_decisions_override_pins_decision_source_to_sentra(runner_mod, Scenario):
    """Whenever the controller's decisions endpoint catches a step's outcome,
    source must be 'sentra' by definition (decisions are written by
    /v1/validate). Workstream 18 M3.6 — replaces the legacy audit-lookup
    variant of this test, now testing the DDB-backed decisions_lookup path."""
    Out = _outcome_factory(runner_mod)
    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=lambda s, sid: Out(
            decision="ALLOW", reason="No guardrail intervention", latency_ms=5, raw={},
            decision_source=None,  # invoker doesn't know yet
        ),
        azure_prompt_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=5, raw={}),
        azure_tool_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=5, raw={}),
        decisions_lookup_fn=lambda sid, rid: {
            "request_id": rid,
            "combined": {
                "decision": "DENY",
                "reason": "sql_injection rule fired",
                "winning_source": "sentra.sigma",
            },
            "signals": [],
        },
    )
    scen = _scenario(Scenario, steps=[
        {"id": "s1", "cloud": "bedrock", "agent_id": "x", "prompt": "atk", "expected_decision": "DENY"},
    ])
    [result] = list(runner.run(scen))
    assert result.actual_decision == "DENY"
    assert result.decision_source == runner_mod.DECISION_SOURCE_SENTRA


def test_expected_source_mismatch_fails_step(runner_mod, Scenario):
    """A step that demanded a Sentra DENY but got an Azure-CF DENY must FAIL —
    the demo narrative would otherwise silently bend."""
    Out = _outcome_factory(runner_mod)
    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=lambda s, sid: Out(decision="ALLOW", reason=None, latency_ms=5, raw={}),
        azure_prompt_invoker=lambda s, sid: Out(
            decision="DENY", reason="azure_content_filter", latency_ms=5, raw={},
            decision_source=runner_mod.DECISION_SOURCE_AZURE_CONTENT_FILTER,
        ),
        azure_tool_invoker=lambda *a, **k: Out(decision="ALLOW", reason=None, latency_ms=5, raw={}),
    )
    scen = _scenario(Scenario, steps=[
        {"id": "s1", "cloud": "azure_foundry", "agent_id": "a", "prompt": "atk",
         "expected_decision": "DENY", "expected_source": "sentra"},
    ])
    [result] = list(runner.run(scen))
    assert result.actual_decision == "DENY"
    assert result.decision_source == runner_mod.DECISION_SOURCE_AZURE_CONTENT_FILTER
    assert result.status == runner_mod.StepStatus.FAILED, (
        "step expected source=sentra but Azure content filter caught it — must FAIL "
        "so the investor demo doesn't silently misrepresent the security boundary"
    )


def test_expected_source_match_passes_step(runner_mod, Scenario):
    Out = _outcome_factory(runner_mod)
    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=lambda s, sid: Out(decision="ALLOW", reason=None, latency_ms=5, raw={}),
        azure_prompt_invoker=lambda s, sid: Out(decision="ALLOW", reason=None, latency_ms=5, raw={}),
        azure_tool_invoker=lambda s, sid: Out(
            decision="DENY", reason="sql_injection rule fired", latency_ms=5, raw={},
            decision_source=runner_mod.DECISION_SOURCE_SENTRA,
        ),
    )
    scen = _scenario(Scenario, steps=[
        {"id": "s1", "cloud": "azure_foundry", "agent_id": "a", "tool": "verify_image_authenticity",
         "tool_params": {}, "user_input": "show me customers WHERE 1=1",
         "expected_decision": "DENY", "expected_reason_contains": "sql_injection",
         "expected_source": "sentra"},
    ])
    [result] = list(runner.run(scen))
    assert result.status == runner_mod.StepStatus.PASSED
    assert result.decision_source == runner_mod.DECISION_SOURCE_SENTRA


def test_user_input_field_present_in_step_model(runner_mod, CrossCloudStep):
    """The YAML schema must accept and round-trip `user_input` — that's how
    a tool step expresses an attack payload that Sentra's sigma engine reads."""
    step = CrossCloudStep(
        id="x", cloud="azure_foundry", agent_id="a",
        tool="verify_image_authenticity", tool_params={},
        user_input="show me customers WHERE 1=1",
        expected_decision="DENY",
    )
    assert step.user_input == "show me customers WHERE 1=1"


# ---------------------------------------------------------------------------
# 8. defensive
# ---------------------------------------------------------------------------


def test_run_without_cross_cloud_block_raises(runner_mod, Scenario):
    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=lambda *a, **k: None,
        azure_prompt_invoker=lambda *a, **k: None,
        azure_tool_invoker=lambda *a, **k: None,
    )
    scen = Scenario(
        scenario_id="empty", name="e", description="", mode="manual",
        agents={"bedrock": [], "azure_foundry": []}, prompts=[],
        cross_cloud=None,
    )
    with pytest.raises(ValueError, match="cross_cloud"):
        list(runner.run(scen))


def test_unknown_cloud_raises_value_error(runner_mod, CrossCloudStep, Scenario):
    Out = _outcome_factory(runner_mod)
    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=lambda s, sid: Out(decision="ALLOW", reason=None, latency_ms=1, raw={}),
        azure_prompt_invoker=lambda s, sid: Out(decision="ALLOW", reason=None, latency_ms=1, raw={}),
        azure_tool_invoker=lambda s, sid: Out(decision="ALLOW", reason=None, latency_ms=1, raw={}),
    )
    scen = _scenario(Scenario, steps=[
        {"id": "x", "cloud": "vertex_ai", "agent_id": "v", "prompt": "p", "expected_decision": "ALLOW"},
    ])
    # The unknown cloud raises inside _pick_invoker which is caught and turned
    # into an ERRORED step (per design — never crash mid-scenario).
    results = list(runner.run(scen))
    assert results[0].status == runner_mod.StepStatus.ERRORED
    assert "Unknown cloud" in results[0].error


def test_bedrock_step_with_tool_but_no_tool_invoker_errors(runner_mod, Scenario):
    """Workstream 18: a `tool:` Bedrock step requires bedrock_tool_invoker
    to be injected. Without it, _pick_invoker raises with a clear pointer
    at the LLD §4.2 fix path."""
    Out = _outcome_factory(runner_mod)
    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=lambda s, sid: Out(decision="ALLOW", reason=None, latency_ms=1, raw={}),
        azure_prompt_invoker=lambda s, sid: Out(decision="ALLOW", reason=None, latency_ms=1, raw={}),
        azure_tool_invoker=lambda s, sid: Out(decision="ALLOW", reason=None, latency_ms=1, raw={}),
        # bedrock_tool_invoker NOT injected
    )
    scen = _scenario(Scenario, steps=[
        {"id": "x", "cloud": "bedrock", "agent_id": "b", "tool": "foo", "tool_params": {}, "expected_decision": "ALLOW"},
    ])
    results = list(runner.run(scen))
    assert results[0].status == runner_mod.StepStatus.ERRORED
    assert "bedrock_tool_invoker" in results[0].error


def test_bedrock_step_without_tool_or_prompt_errors(runner_mod, Scenario):
    Out = _outcome_factory(runner_mod)
    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=lambda s, sid: Out(decision="ALLOW", reason=None, latency_ms=1, raw={}),
        azure_prompt_invoker=lambda s, sid: Out(decision="ALLOW", reason=None, latency_ms=1, raw={}),
        azure_tool_invoker=lambda s, sid: Out(decision="ALLOW", reason=None, latency_ms=1, raw={}),
    )
    scen = _scenario(Scenario, steps=[
        {"id": "x", "cloud": "bedrock", "agent_id": "b", "expected_decision": "ALLOW"},
    ])
    results = list(runner.run(scen))
    assert results[0].status == runner_mod.StepStatus.ERRORED
    assert "tool" in results[0].error.lower() or "prompt" in results[0].error.lower()


def test_azure_step_without_tool_or_prompt_errors(runner_mod, Scenario):
    Out = _outcome_factory(runner_mod)
    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=lambda s, sid: Out(decision="ALLOW", reason=None, latency_ms=1, raw={}),
        azure_prompt_invoker=lambda s, sid: Out(decision="ALLOW", reason=None, latency_ms=1, raw={}),
        azure_tool_invoker=lambda s, sid: Out(decision="ALLOW", reason=None, latency_ms=1, raw={}),
    )
    scen = _scenario(Scenario, steps=[
        {"id": "x", "cloud": "azure_foundry", "agent_id": "a", "expected_decision": "ALLOW"},
    ])
    results = list(runner.run(scen))
    assert results[0].status == runner_mod.StepStatus.ERRORED
    assert "tool" in results[0].error.lower()


# ---------------------------------------------------------------------------
# Workstream 18 — Bedrock direct-invoke (default_bedrock_tool_invoker)
# ---------------------------------------------------------------------------


def test_bedrock_tool_step_routes_to_bedrock_tool_invoker(runner_mod, Scenario):
    """T-RUN-02 — _pick_invoker routes Bedrock + tool: to the tool invoker."""
    Out = _outcome_factory(runner_mod)
    seen: list[str] = []

    def tool_invoker(step, sid):
        seen.append(f"tool:{step.id}")
        return Out(decision="ALLOW", reason=None, latency_ms=1, raw={})

    def prompt_invoker(step, sid):
        seen.append(f"prompt:{step.id}")
        return Out(decision="ALLOW", reason=None, latency_ms=1, raw={})

    runner = runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=prompt_invoker,
        bedrock_tool_invoker=tool_invoker,
        azure_prompt_invoker=lambda s, sid: Out(decision="ALLOW", reason=None, latency_ms=1, raw={}),
        azure_tool_invoker=lambda s, sid: Out(decision="ALLOW", reason=None, latency_ms=1, raw={}),
    )
    scen = _scenario(Scenario, steps=[
        {"id": "p", "cloud": "bedrock", "agent_id": "b", "prompt": "hi", "expected_decision": "ALLOW"},
        {"id": "t", "cloud": "bedrock", "agent_id": "b", "tool": "query_customers",
         "tool_params": {"state": "CA"}, "expected_decision": "ALLOW"},
    ])
    list(runner.run(scen))
    assert seen == ["prompt:p", "tool:t"]


def _fake_lambda_client(payload_dict):
    """Build a mock boto3 lambda client whose invoke() returns the given payload."""
    import io
    import json as _json

    class _FakeResp:
        def __init__(self, body):
            self._body = body
            self._read = False

        def read(self):
            self._read = True
            return self._body

    class _FakeClient:
        def __init__(self):
            self.invoke_calls = []

        def invoke(self, **kwargs):
            self.invoke_calls.append(kwargs)
            return {"Payload": _FakeResp(_json.dumps(payload_dict).encode("utf-8"))}

    return _FakeClient()


class _FakeSchemaFetcher:
    """In-memory schema fetcher mirroring BedrockSchemaFetcher's interface."""

    def __init__(self, schema):
        self._schema = schema

    def get(self, agent_id):
        return self._schema

    @staticmethod
    def coerce_param(openapi_type, value):
        if openapi_type == "integer":
            return int(value)
        if openapi_type == "number":
            return float(value)
        if openapi_type == "boolean":
            return bool(value) if isinstance(value, bool) else str(value).lower() in ("true", "1")
        return str(value)


class _FakeSignalsClient:
    def __init__(self):
        self.posts = []

    def post_signal(self, **kwargs):
        self.posts.append(kwargs)
        return True


def test_T_RUN_08_bedrock_tool_invoker_uses_schema_aware_types(runner_mod, CrossCloudStep):
    """T-RUN-08 — schema-aware event builder emits integer for integer-declared params."""
    schema = {
        "process_refund": {
            "parameters": {
                "order_id": {"type": "string", "openapi_type": "string", "required": True},
                "amount": {"type": "number", "openapi_type": "number", "required": True},
            }
        }
    }
    fake_client = _fake_lambda_client({
        "response": {
            "httpStatusCode": 200,
            "responseBody": {"application/json": {"body": '{"success": true}'}},
        }
    })

    invoker = runner_mod.default_bedrock_tool_invoker(
        lambda_arn="arn:aws:lambda:us-east-1:000000000000:function:test",
        schema_fetcher=_FakeSchemaFetcher(schema),
        signals_client=_FakeSignalsClient(),
        boto3_client=fake_client,
    )

    step = CrossCloudStep(
        id="t1", cloud="bedrock", agent_id="agent-x",
        tool="process_refund",
        tool_params={"order_id": "ORD-1", "amount": "50.5"},  # amount supplied as string
        request_id="rid-1",
        expected_decision="ALLOW",
    )
    outcome = invoker(step, "sess-1")

    assert outcome.decision == "ALLOW"
    # Inspect the synthetic Bedrock event built by the invoker
    event = _load_json(fake_client.invoke_calls[0]["Payload"])
    properties = event["requestBody"]["content"]["application/json"]["properties"]
    by_name = {p["name"]: p for p in properties}
    assert by_name["order_id"] == {"name": "order_id", "type": "string", "value": "ORD-1"}
    # The critical assertion: amount declared as number, value coerced to float (NOT stringified)
    assert by_name["amount"]["type"] == "number"
    assert by_name["amount"]["value"] == 50.5


def test_T_RUN_09_bedrock_tool_invoker_emits_synthetic_guardrail_signal(runner_mod, CrossCloudStep):
    """T-RUN-09 — synthetic bedrock_guardrail signal posted with direct_invoke=true."""
    schema = {
        "query_customers": {
            "parameters": {"state": {"type": "string", "openapi_type": "string", "required": True}}
        }
    }
    fake_client = _fake_lambda_client({
        "response": {
            "httpStatusCode": 200,
            "responseBody": {"application/json": {"body": '{"success": true}'}},
        }
    })
    signals = _FakeSignalsClient()

    invoker = runner_mod.default_bedrock_tool_invoker(
        lambda_arn="arn:aws:lambda:us-east-1:000000000000:function:test",
        schema_fetcher=_FakeSchemaFetcher(schema),
        signals_client=signals,
        boto3_client=fake_client,
    )

    step = CrossCloudStep(
        id="t1", cloud="bedrock", agent_id="agent-x",
        tool="query_customers",
        tool_params={"state": "CA"},
        request_id="rid-abc",
        expected_decision="ALLOW",
    )
    invoker(step, "sess-xyz")

    assert len(signals.posts) == 1
    post = signals.posts[0]
    assert post["session_id"] == "sess-xyz"
    assert post["request_id"] == "rid-abc"
    assert post["source"] == "bedrock_guardrail"
    assert post["decision"] == "ALLOW"
    assert post["metadata"]["direct_invoke"] is True
    assert post["metadata"]["invoker"] == "default_bedrock_tool_invoker"


def test_bedrock_tool_invoker_parses_403_as_deny(runner_mod, CrossCloudStep):
    """Direct-invoke returns DENY with the Sentra reason on Lambda 403."""
    schema = {"query_customers": {"parameters": {"state": {"type": "string", "openapi_type": "string", "required": True}}}}
    deny_body = (
        '{"success": false, "decision": "DENY", '
        '"error": "Tool \\u0027query_customers\\u0027 not authorized for agent-x", '
        '"request_id": "rid-1"}'
    )
    fake_client = _fake_lambda_client({
        "response": {
            "httpStatusCode": 403,
            "responseBody": {"application/json": {"body": deny_body}},
        }
    })
    invoker = runner_mod.default_bedrock_tool_invoker(
        lambda_arn="arn:aws:lambda:us-east-1:000000000000:function:test",
        schema_fetcher=_FakeSchemaFetcher(schema),
        signals_client=_FakeSignalsClient(),
        boto3_client=fake_client,
    )
    step = CrossCloudStep(
        id="t1", cloud="bedrock", agent_id="agent-x",
        tool="query_customers", tool_params={"state": "CA"},
        request_id="rid-1", expected_decision="DENY",
    )
    outcome = invoker(step, "sess-1")
    assert outcome.decision == "DENY"
    assert "not authorized" in (outcome.reason or "")


def test_bedrock_tool_invoker_returns_error_when_schema_unavailable(runner_mod, CrossCloudStep):
    class _Boom:
        def get(self, agent_id):
            raise RuntimeError("no schema")

        @staticmethod
        def coerce_param(t, v):
            return v

    invoker = runner_mod.default_bedrock_tool_invoker(
        lambda_arn="arn:aws:lambda:us-east-1:000000000000:function:test",
        schema_fetcher=_Boom(),
        signals_client=_FakeSignalsClient(),
        boto3_client=_fake_lambda_client({}),
    )
    step = CrossCloudStep(
        id="t1", cloud="bedrock", agent_id="agent-x",
        tool="query_customers", tool_params={"state": "CA"},
        request_id="rid-1", expected_decision="ALLOW",
    )
    outcome = invoker(step, "sess-1")
    assert outcome.decision == "ERROR"
    assert "schema" in (outcome.reason or "").lower()


def _load_json(blob):
    import json as _json
    return _json.loads(blob.decode("utf-8"))
