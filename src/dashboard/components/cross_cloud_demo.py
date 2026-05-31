"""Cross-Cloud Demo section for the Demo Scenarios tab — Workstream 15 M5.

Renders the four cross-cloud scenarios (S1-S4) as story-mode cards.
Each card:
  1. Shows the investor story + step plan
  2. "Fire scenario" button
  3. On fire: drives the CrossCloudScenarioRunner, streams StepResult updates
     into a live table, then shows an outcome badge
  4. Links to the Cross-Cloud Activity Timeline (Overview tab) with the
     session_id pre-populated for after-the-fact audit verification

All side effects flow through cross_cloud_scenarios.CrossCloudScenarioRunner
which is fully Streamlit-free and unit-tested (43 tests).
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Iterable, List, Optional

import streamlit as st

from components.cross_cloud_scenarios import (
    CrossCloudScenarioRunner,
    SCENARIO_HOOKS,
    ScenarioOutcome,
    StepResult,
    StepStatus,
    default_azure_prompt_invoker,
    default_azure_tool_invoker,
    default_bedrock_prompt_invoker,
    default_bedrock_tool_invoker,
    _now_iso,
)
from utils.cloud_badges import badge_for

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def render_cross_cloud_demo_section(scenarios: list[dict]):
    """Render the '🌐 Cross-Cloud Demos (S1–S4)' section header + cards.

    `scenarios` is the raw list from /demo/scenarios — only those with a
    `cross_cloud` block are shown here.
    """
    st.subheader("🌐 Cross-Cloud Demos (S1–S4)")
    st.caption(
        "Investor-grade scenarios that exercise Sentra's governance plane across "
        "AWS Bedrock and Azure Foundry. Click Fire to run end-to-end; live events "
        "appear below as decisions hit the controller."
    )

    if not scenarios:
        st.info("No cross-cloud scenarios loaded from the orchestrator.")
        return

    ordered = sorted(scenarios, key=lambda s: s.get("scenario_id", ""))
    for scenario in ordered:
        _render_scenario_card(scenario)


# ---------------------------------------------------------------------------
# Single card
# ---------------------------------------------------------------------------


def _render_scenario_card(scenario: dict):
    """One investor-facing card per scenario."""
    sid = scenario["scenario_id"]
    cc = scenario.get("cross_cloud") or {}
    story = cc.get("story", scenario.get("description", ""))
    steps = cc.get("steps", [])

    # Per-card state stash so we can re-render the last outcome between Streamlit
    # script runs without re-firing the scenario.
    state_key = f"xcloud_demo__{sid}"
    state = st.session_state.setdefault(state_key, {"running": False, "outcome": None, "events": []})

    with st.container():
        head_l, head_r = st.columns([5, 2])
        with head_l:
            st.markdown(f"### {scenario.get('name', sid)}")
            st.caption(story)
        with head_r:
            fire_disabled = state["running"]
            if st.button(
                "🚀 Fire scenario" if not state["running"] else "Running…",
                key=f"xcloud_fire_{sid}",
                disabled=fire_disabled,
                use_container_width=True,
            ):
                _execute_and_stash(sid, scenario, state)

        # Step plan (always visible)
        with st.expander("📋 Step plan", expanded=False):
            for idx, step in enumerate(steps, start=1):
                cloud_badge = badge_for(step.get("cloud"))
                target = step.get("tool") or "prompt"
                st.markdown(
                    f"**{idx}. `{step.get('id')}`** · {cloud_badge} · `{step.get('agent_id')}` · `{target}` → expects **{step.get('expected_decision')}**"
                )
                if step.get("description"):
                    st.caption(step["description"])

        # Live / last events
        if state["events"]:
            _render_events_table(state["events"])

        # Outcome badge (if last run completed)
        if state["outcome"] is not None and not state["running"]:
            _render_outcome_badge(state["outcome"])

        st.markdown("---")


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------


def _execute_and_stash(scenario_id: str, scenario: dict, state: dict):
    """Build the runner, stream events into the live table, store final outcome."""
    state["running"] = True
    state["events"] = []
    state["outcome"] = None

    placeholder = st.empty()
    started = _now_iso()
    session_id = f"xcloud-{scenario_id}-{int(time.time())}-{uuid.uuid4().hex[:6]}"

    try:
        runner = _build_runner(scenario_id)
    except Exception as exc:
        logger.error("Failed to build runner for %s: %s", scenario_id, exc, exc_info=True)
        placeholder.error(f"Could not initialize scenario runner: {exc}")
        state["running"] = False
        return

    # Coerce dict scenario -> Pydantic Scenario for the runner.
    try:
        from components.cross_cloud_scenarios import Scenario  # local mirror
        scen_obj = Scenario(**scenario)
    except Exception as exc:
        placeholder.error(f"Scenario {scenario_id} failed validation: {exc}")
        state["running"] = False
        return

    events: list[StepResult] = []
    try:
        for result in runner.run(scen_obj, session_id=session_id):
            events.append(result)
            state["events"] = events
            with placeholder.container():
                _render_events_table(events)
    except Exception as exc:
        logger.error("Runner crashed mid-scenario %s: %s", scenario_id, exc, exc_info=True)
        placeholder.error(f"Scenario runner crashed: {exc}")
        state["running"] = False
        return

    outcome = runner.summarize(scen_obj, session_id, events, started_at=started)
    state["outcome"] = outcome
    state["running"] = False

    with placeholder.container():
        _render_events_table(events)
    _render_post_run_actions(scenario_id, session_id)


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


_STATUS_ICONS = {
    StepStatus.PENDING: "⚪",
    StepStatus.RUNNING: "⏳",
    StepStatus.PASSED: "✅",
    StepStatus.FAILED: "❌",
    StepStatus.ERRORED: "⚠️",
}


# Honest labeling of which layer made the call. Keys mirror DECISION_SOURCE_*
# from cross_cloud_scenarios. Used by the events table + outcome footer so the
# investor demo doesn't claim Sentra blocked something that Azure's content
# filter actually caught before Sentra was consulted.
_SOURCE_BADGES = {
    # Runner-side aggregated label (back-compat with existing rows).
    "sentra": "🛡 Sentra",
    # Workstream 17 / LLD 17 §4 — granular Sentra sub-validator sources.
    "sentra.trust": "🛡 Sentra trust",
    "sentra.policy": "🛡 Sentra policy",
    "sentra.sigma": "🛡 Sentra sigma",
    "sentra.ml_classifier": "🛡 Sentra ML",
    "sentra.context": "🛡 Sentra context",
    "sentra.abuse": "🛡 Sentra abuse",
    "sentra.cross_agent": "🛡 Sentra cross-agent",
    "sentra.combined": "🛡 Sentra combined",
    # Edge / cloud-native sources.
    "azure_content_filter": "🟦 Azure Content Filter",
    "bedrock_guardrail": "🟧 Bedrock Guardrail",
    # Runner-internal labels.
    "agent_self_refusal": "🤖 Agent self-refusal",
    "runner_local": "↪ Runner (no cloud)",
    "invoker_error": "⚠️ Invoker error",
}


def _source_label(source: Optional[str]) -> str:
    if not source:
        return "—"
    return _SOURCE_BADGES.get(source, source)


def _render_events_table(events: Iterable[StepResult]):
    events_list = list(events)
    rows = []
    for ev in events_list:
        rows.append({
            "": _STATUS_ICONS.get(ev.status, "•"),
            "Step": ev.step_id,
            "Cloud": badge_for(ev.cloud) if ev.cloud != "control_plane" else "🛠 Control plane",
            "Agent": ev.agent_id,
            # Action: shows the prompt text or tool+params so investors see
            # which attack corresponded to each row.
            "Action": ev.action_summary or "—",
            "Expected": ev.expected_decision,
            "Actual": ev.actual_decision or "—",
            # By: honest attribution of who actually made the decision. Lets
            # the demo distinguish "Sentra blocked it" from "Azure's content
            # filter caught it before Sentra was consulted".
            "By": _source_label(ev.decision_source),
            "Latency (ms)": ev.latency_ms if ev.latency_ms is not None else "—",
            "Reason": (ev.reason or ev.error or "")[:120],
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)

    # Workstream 17 / LLD 17 §9.4 — per-step signal breakdown expander.
    # Renders only for events that came back with signals (i.e. the runner's
    # decisions_lookup hit). Lets investors see every contributor (sentra.sigma
    # DENY, bedrock_guardrail ALLOW, etc.) behind the "By" column.
    for ev in events_list:
        if not getattr(ev, "signals", None):
            continue
        with st.expander(f"🔍 Signals for step `{ev.step_id}` ({len(ev.signals)})", expanded=False):
            _render_signals_table(ev.signals)


def _render_signals_table(signals):
    """Format the per-step signal contributors as a Streamlit dataframe.

    Each row is one validator/edge producer's verdict. Reads from the dict
    shape returned by GET /v1/sessions/{id}/decisions (LLD 17 §8.2).
    """
    rows = []
    for s in signals:
        decision = s.get("decision") or "—"
        # Show DENY in red via a leading icon; ALLOW gets a check.
        icon = "🛑" if decision == "DENY" else "✅"
        # WS19 / LLD 19 §6.2 — OTHER suppression: don't surface the literal
        # "OTHER" string as a threat_type since it's uninformative; show "—"
        # and let the Reason column carry the explanation.
        threat_type_raw = s.get("threat_type")
        threat_type = "—" if (not threat_type_raw or threat_type_raw == "OTHER") else threat_type_raw
        # WS19 / LLD 19 §6.2 — ML classifier metadata: surface which tier
        # (hot vs escalated vs hot_only_budget_exhausted) produced the verdict.
        # Lets investors see "Sentra ML escalated to Sonnet for this borderline
        # input" rather than treating all ML signals as opaque.
        metadata = s.get("metadata") or {}
        model_used = metadata.get("model_used") or "—"
        rows.append({
            "": icon,
            "Source": _source_label(s.get("source")),
            "Decision": decision,
            "Priority": s.get("priority", 0),
            "Confidence": (
                f"{s['confidence']:.2f}" if s.get("confidence") is not None else "—"
            ),
            "Reason": (s.get("reason") or "")[:160],
            "Threat type": threat_type,
            "Rule": s.get("matched_rule") or "—",
            "ML tier": model_used if s.get("source") == "sentra.ml_classifier" else "—",
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_outcome_badge(outcome: ScenarioOutcome):
    cols = st.columns([2, 2, 2, 4])
    cols[0].metric("Result", "PASS ✅" if outcome.passed else "FAIL ❌")
    cols[1].metric("DENY", outcome.deny_count)
    cols[2].metric("ALLOW", outcome.allow_count)
    cols[3].metric("Clouds × Time", f"{outcome.cloud_count} clouds · {outcome.elapsed_ms} ms")
    if outcome.passed:
        st.success(f"🎯 {outcome.narrative}")
    else:
        st.error(f"⚠️ {outcome.narrative}")

    # Source attribution footer — counts of DENYs by decision_source so the
    # investor can see how many were *Sentra-attributed* vs caught upstream
    # by a cloud-native filter. Critical for the cross-cloud-governance
    # narrative: a scenario that "passed" entirely via Azure content filter
    # doesn't prove Sentra is working.
    deny_sources = _count_deny_sources(outcome.steps)
    if deny_sources:
        chip_strs = ", ".join(f"{_source_label(src)}={count}" for src, count in deny_sources.items())
        st.caption(f"DENY attribution: {chip_strs}")

    st.caption(f"Session: `{outcome.session_id}` · Started {outcome.started_at} · Finished {outcome.finished_at}")


def _count_deny_sources(steps: List[StepResult]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for s in steps:
        if s.actual_decision == "DENY" and s.decision_source:
            counts[s.decision_source] = counts.get(s.decision_source, 0) + 1
    return counts


def _render_post_run_actions(scenario_id: str, session_id: str):
    st.caption(
        f"➡️ Switch to the **Overview** tab → **🌐 Cross-Cloud Activity Timeline** "
        f"and paste session `{session_id}` to inspect the per-event audit trail."
    )


# ---------------------------------------------------------------------------
# Runner construction
# ---------------------------------------------------------------------------


def _build_runner(scenario_id: str) -> CrossCloudScenarioRunner:
    """Wire the runner with real Bedrock + Azure invokers and the policy CLI."""
    from services.bedrock_agent_caller import BedrockAgentCaller
    from services.bedrock_agent_service import get_bedrock_agent_service
    from services.agent_caller_factory import get_connector
    from services.security_controller_client import security_controller_client

    bedrock_service = get_bedrock_agent_service()

    def discover(symbolic_id: str) -> Optional[dict]:
        """Map the YAML-declared agent_id to a discovered Bedrock {id, alias_id}.

        Accepts three symbolic shortcuts and the full agent names:
          - bedrock-secured / sentra-mvp-customer-service-agent          (Claude + guardrail + Sentra)
          - bedrock-unsecured / sentra-mvp-customer-service-agent-unsecured (Nova Lite, NO Sentra)
          - bedrock-naive / sentra-mvp-customer-service-agent-naive      (Nova Lite + Sentra-calling Lambda — WS15 M5 demo target)
        """
        if symbolic_id in {"bedrock-secured", "sentra-mvp-customer-service-agent"}:
            return bedrock_service.get_agent_by_type("secured")
        if symbolic_id in {"bedrock-unsecured", "sentra-mvp-customer-service-agent-unsecured"}:
            return bedrock_service.get_agent_by_type("unsecured")
        if symbolic_id in {"bedrock-naive", "sentra-mvp-customer-service-agent-naive"}:
            return bedrock_service.get_agent_by_type("naive")
        # Last-ditch: try literal match against discovered agents.
        for a in bedrock_service.discover_agents():
            if a.get("raw_name") == symbolic_id or a.get("id") == symbolic_id:
                return a
        return None

    azure_connector_factory = lambda: get_connector("azure-verification-agent")

    bedrock_invoker = default_bedrock_prompt_invoker(
        caller_factory=BedrockAgentCaller,
        discover_fn=discover,
    )
    azure_prompt_invoker = default_azure_prompt_invoker(azure_connector_factory)
    azure_tool_invoker = default_azure_tool_invoker()

    # Workstream 18 / LLD 18 §4.2 — direct-invoke Bedrock for deterministic
    # enforcement-claim scenarios. The schema fetcher reuses the discover_fn
    # so the (symbolic_id → real bedrock_id) translation happens in one place.
    bedrock_tool_invoker = _build_bedrock_tool_invoker(discover_fn=discover)

    def decisions_lookup(session_id: str, request_id: str) -> Optional[dict]:
        """Fetch the controller's combined verdict for (session_id, request_id).

        Workstream 17 / LLD 17 §9.2 — replaces the legacy audit_lookup which
        queried CloudWatch Insights and was prone to the 60s+ indexing-lag
        race (LLD 17 §2). DDB-backed; sub-100ms p95.

        Returns the first decision row from the response, shaped so the
        runner can read `payload["combined"]` and `payload["signals"]`
        without further unwrapping.
        """
        try:
            resp = security_controller_client.get_session_decisions(
                session_id=session_id,
                request_id=request_id,
                limit=10,
            )
        except Exception:
            return None
        decisions = (resp or {}).get("decisions") if isinstance(resp, dict) else None
        if not decisions:
            return None
        # Filter to the exact request_id (the endpoint filters server-side
        # too but be defensive against future schema changes).
        for d in decisions:
            if d.get("request_id") == request_id:
                return d
        # Fall back to the first row (the endpoint already filtered).
        return decisions[0]

    hook = SCENARIO_HOOKS.get(scenario_id, {})
    policy_apply_fn = _policy_apply_subprocess if hook else None

    return CrossCloudScenarioRunner(
        bedrock_prompt_invoker=bedrock_invoker,
        bedrock_tool_invoker=bedrock_tool_invoker,
        azure_prompt_invoker=azure_prompt_invoker,
        azure_tool_invoker=azure_tool_invoker,
        decisions_lookup_fn=decisions_lookup,
        policy_apply_fn=policy_apply_fn,
        policy_propagation_step_ids=tuple(hook.get("policy_propagation_step_ids", ())),
        # New multi-agent shape (preferred). Falls back to the legacy single
        # remove_tool/agent_id pair if a hook hasn't been migrated yet.
        policy_updates=hook.get("policy_updates"),
        policy_remove_tool=hook.get("policy_remove_tool"),
        policy_agent_id=hook.get("policy_agent_id"),
    )


def _build_bedrock_tool_invoker(*, discover_fn):
    """Construct the direct-invoke Bedrock invoker.

    Reads the Lambda ARN from `BEDROCK_ACTION_GROUP_LAMBDA_ARN` (set by CDK
    on the dashboard ECS task). Returns None if not configured — the runner
    handles that gracefully (any tool: step on Bedrock raises a clear error).
    """
    import os
    from services.bedrock_schema_fetcher import BedrockSchemaFetcher
    from connectors.base.signals_client import SignalsClient

    lambda_arn = os.environ.get("BEDROCK_ACTION_GROUP_LAMBDA_ARN")
    if not lambda_arn:
        logger.warning(
            "BEDROCK_ACTION_GROUP_LAMBDA_ARN not set; Bedrock direct-invoke "
            "disabled. Scenario steps with cloud=bedrock and tool: will fail."
        )
        return None

    region = os.environ.get("AWS_REGION", "us-east-1")
    schema_fetcher = BedrockSchemaFetcher(region=region, discover_fn=discover_fn)
    signals_client = SignalsClient()

    return default_bedrock_tool_invoker(
        lambda_arn=lambda_arn,
        schema_fetcher=schema_fetcher,
        signals_client=signals_client,
        region=region,
    )


def _policy_apply_subprocess(argv: list[str]) -> dict:
    """Call scripts/apply_policy.py in-process.

    We import the module (shipped into the dashboard image under /app/scripts/)
    and call main(argv) directly — avoids subprocess overhead and lets us
    capture the return code + stdout JSON without parsing shell output.
    """
    import importlib.util
    import json
    import io
    import contextlib
    import sys
    from pathlib import Path

    here = Path(__file__).resolve()
    for ancestor in here.parents:
        candidate = ancestor / "scripts" / "apply_policy.py"
        if candidate.exists():
            spec = importlib.util.spec_from_file_location("apply_policy_runtime", candidate)
            module = importlib.util.module_from_spec(spec)
            sys.modules["apply_policy_runtime"] = module
            spec.loader.exec_module(module)
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = module.main(argv)
            if rc != 0:
                raise RuntimeError(f"apply_policy.py exited with rc={rc}")
            try:
                return json.loads(buf.getvalue())
            except json.JSONDecodeError:
                return {"raw_stdout": buf.getvalue()}
    raise RuntimeError("scripts/apply_policy.py not packaged into the dashboard image")
