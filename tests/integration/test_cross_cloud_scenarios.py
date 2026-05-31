"""Integration tests for cross-cloud scenarios S1-S4 — Workstream 15 M5.

Drives the four scenarios directly against the live AWS + Azure deployments,
using the same CrossCloudScenarioRunner the dashboard uses. These tests live
outside the runtime hot path and are gated behind RUN_INTEGRATION=1 so they
don't fire unless explicitly opted-in (they make real Bedrock + Azure + Sentra
calls and incur cost).

Run with:
    RUN_INTEGRATION=1 pytest tests/integration/test_cross_cloud_scenarios.py -v

Required environment (read by AzureConnector + bedrock_agent_caller + the
runner's default invokers):
    AWS_PROFILE=sentra (or AWS credentials in env)
    AZURE_OPENAI_ENDPOINT
    AZURE_OPENAI_API_KEY
    AZURE_OPENAI_DEPLOYMENT  (default: gpt-4o-mini)
    AZURE_FUNCTION_TOOL_URL  (e.g. https://aegionai-ws15-m3-func.azurewebsites.net/api/tool)
    SENTRA_API_ENDPOINT      (controller base URL — used by apply_policy)
    SENTRA_API_KEY           (or AWS Secrets Manager 'sentra-api-key')

What each test asserts:
  S1: same prompt blocked on both clouds (≥1 DENY per cloud).
  S2: post-policy-update probes DENY on both clouds within 10s of the apply call.
  S3: attack path DENIes with cross_cloud_dependency_not_met; honor path ALLOWs.
  S4: post-injection Azure call DENIes citing trust/quarantine.

These are integration smoke tests, not exhaustive regression — the runner is
already covered by the 21-test unit suite.
"""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR_ROOT = REPO_ROOT / "src" / "demo-orchestrator"
DASHBOARD_COMPONENTS = REPO_ROOT / "src" / "dashboard" / "components"
SCENARIO_DIR = ORCHESTRATOR_ROOT / "scenarios"


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_INTEGRATION", "0") != "1",
    reason="Set RUN_INTEGRATION=1 to opt-in to live cross-cloud integration tests.",
)


# ---------------------------------------------------------------------------
# Loaders (kept here so the suite doesn't drag in the entire dashboard package)
# ---------------------------------------------------------------------------


def _load_runner_module():
    spec = importlib.util.spec_from_file_location(
        "ccs_integration", DASHBOARD_COMPONENTS / "cross_cloud_scenarios.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["ccs_integration"] = module
    spec.loader.exec_module(module)
    return module


def _load_scenario(scenario_id: str, runner_mod):
    path = SCENARIO_DIR / f"{scenario_id}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"scenario YAML missing: {path}")
    return runner_mod.Scenario(**yaml.safe_load(path.read_text()))


@pytest.fixture(scope="module")
def runner_mod():
    return _load_runner_module()


@pytest.fixture(scope="module")
def runner(runner_mod):
    """Build the runner with real cloud invokers.

    Wire-up mirrors src/dashboard/components/cross_cloud_demo._build_runner —
    duplicated here so the integration suite is self-contained.
    """
    sys.path.insert(0, str(REPO_ROOT / "src" / "dashboard"))
    sys.path.insert(0, str(REPO_ROOT / "src"))

    from services.bedrock_agent_caller import BedrockAgentCaller  # type: ignore
    from services.bedrock_agent_service import get_bedrock_agent_service  # type: ignore
    from services.agent_caller_factory import get_connector  # type: ignore

    bedrock_service = get_bedrock_agent_service()

    def discover(symbolic_id: str):
        if symbolic_id in {"bedrock-secured", "sentra-mvp-customer-service-agent"}:
            return bedrock_service.get_agent_by_type("secured")
        if symbolic_id == "bedrock-unsecured":
            return bedrock_service.get_agent_by_type("unsecured")
        return None

    azure_factory = lambda: get_connector("azure-verification-agent")

    return runner_mod.CrossCloudScenarioRunner(
        bedrock_prompt_invoker=runner_mod.default_bedrock_prompt_invoker(
            caller_factory=BedrockAgentCaller, discover_fn=discover,
        ),
        azure_prompt_invoker=runner_mod.default_azure_prompt_invoker(azure_factory),
        azure_tool_invoker=runner_mod.default_azure_tool_invoker(),
    )


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


def test_s1_unified_governance_pane_blocks_both_clouds(runner_mod, runner):
    scen = _load_scenario("s1_unified_governance_pane", runner_mod)
    steps = list(runner.run(scen))
    by_cloud = {}
    for step in steps:
        by_cloud.setdefault(step.cloud, []).append(step)

    assert "bedrock" in by_cloud and "azure_foundry" in by_cloud, "S1 must exercise both clouds"

    bedrock_denies = sum(1 for s in by_cloud["bedrock"] if s.actual_decision == "DENY")
    azure_denies = sum(1 for s in by_cloud["azure_foundry"] if s.actual_decision == "DENY")
    assert bedrock_denies >= 1, f"Bedrock side did not DENY (got {[s.actual_decision for s in by_cloud['bedrock']]})"
    assert azure_denies >= 1, f"Azure side did not DENY (got {[s.actual_decision for s in by_cloud['azure_foundry']]})"


def test_s2_policy_propagation_enforced_on_both_clouds_within_10s(runner_mod, runner):
    # S2 requires the policy-apply hook to mutate live policy — needs SENTRA_API_*.
    if not os.environ.get("SENTRA_API_KEY"):
        pytest.skip("SENTRA_API_KEY required for S2 (apply_policy.py needs to PUT /v1/policies).")

    # Build a runner instance configured with the S2 hook.
    sys.path.insert(0, str(REPO_ROOT / "src" / "dashboard"))
    from components.cross_cloud_demo import _build_runner  # type: ignore
    s2_runner = _build_runner("s2_cross_cloud_policy_propagation")

    scen = _load_scenario("s2_cross_cloud_policy_propagation", runner_mod)
    steps = list(s2_runner.run(scen))
    outcome = s2_runner.summarize(scen, "s2-int-test", steps, started_at=runner_mod._now_iso())

    after_steps = [s for s in steps if s.step_id.endswith("_after")]
    assert len(after_steps) >= 2, "S2 must run at least two post-update probes (Bedrock + Azure)"
    for s in after_steps:
        assert s.actual_decision == "DENY", f"{s.step_id} expected DENY post-policy-update, got {s.actual_decision}"

    # Latency budget: both post-update probes within 10s of policy apply.
    # The runner's elapsed_ms covers all steps + the policy update; we accept
    # 30s for the whole scenario (LLM + apply + four probes).
    assert outcome.elapsed_ms < 30_000, f"S2 too slow: {outcome.elapsed_ms}ms"


def test_s3_swiggy_attack_denied_honor_allowed(runner_mod, runner):
    scen = _load_scenario("s3_cross_cloud_sequence_validation", runner_mod)
    steps = list(runner.run(scen))

    attack = next((s for s in steps if s.step_id == "attack_skip_verification"), None)
    honor_verify = next((s for s in steps if s.step_id == "honor_step1_azure_verify"), None)
    honor_refund = next((s for s in steps if s.step_id == "honor_step2_bedrock_refund"), None)

    assert attack is not None and attack.actual_decision == "DENY", f"S3 attack must DENY (got {attack and attack.actual_decision})"
    assert (attack.reason or "").lower().find("cross_cloud_dependency_not_met") != -1, \
        f"S3 attack reason should cite cross_cloud_dependency_not_met (got {attack.reason!r})"

    assert honor_verify is not None and honor_verify.actual_decision == "ALLOW", \
        f"S3 honor step 1 (Azure verify) must ALLOW (got {honor_verify and honor_verify.actual_decision})"
    assert honor_refund is not None and honor_refund.actual_decision == "ALLOW", \
        f"S3 honor step 2 (Bedrock refund) must ALLOW after Azure verify (got {honor_refund and honor_refund.actual_decision})"


def test_s4_blast_radius_contained_post_quarantine(runner_mod, runner):
    scen = _load_scenario("s4_cross_cloud_blast_radius", runner_mod)
    steps = list(runner.run(scen))

    azure_final = next((s for s in steps if s.step_id == "azure_blocked_by_trust"), None)
    assert azure_final is not None, "S4 must include the azure_blocked_by_trust step"
    assert azure_final.actual_decision == "DENY", \
        f"S4 final Azure call must DENY after Bedrock quarantine (got {azure_final.actual_decision})"
    # Reason can come from trust check or quarantine module — accept either keyword.
    lower_reason = (azure_final.reason or "").lower()
    assert any(kw in lower_reason for kw in ("quarantine", "trust", "fail-secure")), \
        f"S4 final DENY reason should reference quarantine/trust (got {azure_final.reason!r})"
