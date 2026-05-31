"""Cross-cloud scenario runner — Workstream 15 M5 Tasks 5.1-5.4.

Drives the four investor-grade cross-cloud scenarios (S1-S4) end-to-end from
the dashboard. Each scenario is declared in a YAML under
src/demo-orchestrator/scenarios/sN_*.yaml; the runner reads the cross_cloud
block and executes its `steps` against the right cloud, sharing one session_id
across every step so the controller's context validator can evaluate
cross_cloud_dependencies (LLD 15 §4.5) correctly.

Design notes
============

This module is **deliberately Streamlit-free** so it can be unit tested
without a Streamlit context. The Streamlit UI in dashboard/tabs/demo_tab.py
wraps the runner and renders progress.

Invocation paths are injected (`step_invokers`) so tests can substitute
fakes without spinning up Bedrock + Azure + the controller. The defaults wire
up:

  - bedrock prompt steps:      AzureConnector-style invocation via the
                               BedrockAgentCaller shim. Resolves the real
                               Bedrock agentId + alias via discovery.
  - azure_foundry prompt steps: AzureConnector.invoke_agent (LLM-driven).
  - azure_foundry tool steps:   POST directly to the Function App's
                               /api/tool/{tool_name} endpoint, bypassing
                               the LLM. Mirrors what AzureConnector does
                               internally for each tool call.

Outcome aggregation produces a single `ScenarioOutcome` per scenario with
deny/allow/error counts, elapsed time, and a narrative string suitable for
the investor-facing badge.

Failure modes are explicit. A step that fails to invoke (network error,
config missing) is recorded with status=ERROR and a non-None `error` field;
the scenario continues so the demo doesn't stall — but the outcome.passed
flag goes False so the UI surfaces the failure clearly.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field

import boto3
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Iterator, List, Optional

# Cross-cloud Pydantic models are defined inline (below) instead of imported
# from the orchestrator package. The dashboard `components/__init__.py`
# eagerly imports streamlit-dependent submodules, so any module loaded under
# `components.<x>` drags Streamlit into the import chain — defining the
# models inline keeps the runner Streamlit-free (and unit-test friendly).
# The two parsers (orchestrator-side and dashboard-side) consume the same
# YAML; if either grows a field, mirror it. Integration tests catch drift.
from pydantic import BaseModel, Field as _PydField


class CrossCloudStep(BaseModel):
    """Mirrors src/demo-orchestrator/app/models/scenario.py:CrossCloudStep.

    Workstream 17 / LLD 17 §9.1 — `request_id` is populated by the runner
    before each step's invoker fires. Invokers thread it to the underlying
    connector (BedrockConnector sessionAttributes, AzureConnector HTTP body)
    so every signal Sentra emits for this step correlates back to one id.
    """
    id: str
    cloud: str  # bedrock | azure_foundry
    agent_id: str
    tool: Optional[str] = None
    tool_params: dict[str, Any] = _PydField(default_factory=dict)
    prompt: Optional[str] = None
    # Populated by CrossCloudScenarioRunner._execute() before each invoker call.
    # YAML authors do not set this — it's a runtime correlation id.
    request_id: Optional[str] = None
    # user_input is the natural-language string carried in the ValidationRequest's
    # `user_input` field. For Bedrock prompt steps this defaults to the prompt
    # itself. For Azure tool steps it defaults to the step description, but
    # can be overridden so the YAML can express an attack payload in the
    # user_input even when the tool params themselves look benign — that's
    # how a scenario can guarantee Sentra's sigma engine sees the payload.
    user_input: Optional[str] = None
    expected_decision: str  # ALLOW | DENY
    expected_reason_contains: Optional[str] = None
    expected_source: Optional[str] = None  # sentra | azure_content_filter | bedrock_guardrail | agent_self_refusal
    description: Optional[str] = None
    # Workstream 18 / LLD 18 §4.4 — scenario authors declare per-step intent
    # so the validator can hard-error on misuse (e.g., a sigma-attack step
    # with `tool:` would silently bypass the LLM and defeat the threat-detection
    # claim). Default None for back-compat with pre-WS18 scenario YAMLs; the
    # scenario validator (M3) enforces required-on-new-scenarios.
    intent: Optional[str] = None  # enforcement | threat_detection
    # Per-step opt-out for the rare scenario that wants intent=enforcement
    # AND prompt: (i.e., test the LLM picking the right tool and policy
    # denying it). Without this flag, intent=enforcement + prompt: is a
    # hard validator error (LLD 18 §4.4.1).
    allow_llm_path: bool = False


class CrossCloudPlan(BaseModel):
    """Mirrors src/demo-orchestrator/app/models/scenario.py:CrossCloudPlan."""
    story: str
    steps: List[CrossCloudStep]
    outcome_template: Optional[str] = None


class _AgentTargets(BaseModel):
    self_hosted: List[str] = []
    bedrock: List[str] = []
    azure_foundry: List[str] = []


class _Prompt(BaseModel):
    id: str
    text: str
    expected_decision: str
    expected_threat: str


class Scenario(BaseModel):
    """Minimum fields the dashboard cross-cloud runner needs from a YAML.

    Accepts the orchestrator's full schema; silently ignores fields the
    dashboard runner doesn't consume.
    """
    scenario_id: str
    name: str
    description: str
    mode: str
    interval: Optional[int] = None
    agents: _AgentTargets
    prompts: List[_Prompt] = []
    cross_cloud: Optional[CrossCloudPlan] = None

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    ERRORED = "errored"


@dataclass
class StepResult:
    step_id: str
    cloud: str
    agent_id: str
    description: str
    expected_decision: str
    status: StepStatus = StepStatus.PENDING
    actual_decision: Optional[str] = None
    reason: Optional[str] = None
    latency_ms: Optional[int] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    error: Optional[str] = None
    # Human-facing summary of what the step actually fired — populated by
    # _execute so the UI can show "prompt + tool" alongside the decision.
    action_summary: Optional[str] = None
    # Which layer made the decision the row is showing. See DECISION_SOURCE_*.
    decision_source: Optional[str] = None
    # Per-step signal breakdown from /v1/sessions/{id}/decisions (LLD 17 §8.2).
    # Empty list when decisions_lookup_fn isn't wired or returned no signals.
    # Used by the UI expander to show every contributor (sentra.sigma DENY,
    # bedrock_guardrail ALLOW, etc.).
    signals: list[dict] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        return self.status == StepStatus.PASSED


@dataclass
class ScenarioOutcome:
    scenario_id: str
    session_id: str
    started_at: str
    finished_at: str
    elapsed_ms: int
    total: int
    deny_count: int
    allow_count: int
    error_count: int
    cloud_count: int
    passed: bool
    narrative: str
    steps: List[StepResult]


# ---------------------------------------------------------------------------
# Invoker protocol — pluggable so tests can sub fakes
# ---------------------------------------------------------------------------


@dataclass
class _InvocationOutcome:
    decision: str  # ALLOW | DENY | ERROR
    reason: Optional[str]
    latency_ms: int
    raw: dict[str, Any]
    error: Optional[str] = None
    # Who actually made the decision the invoker is reporting. Lets the UI
    # honestly distinguish "Sentra denied this" from "the cloud's own filter
    # caught it before Sentra was consulted" — important for the cross-cloud
    # demo's narrative integrity. See `DECISION_SOURCE_*` constants below.
    decision_source: Optional[str] = None


# Decision-source taxonomy. Kept as module-level constants so callers don't
# typo strings — every assignment grep-able.
DECISION_SOURCE_SENTRA = "sentra"
DECISION_SOURCE_AZURE_CONTENT_FILTER = "azure_content_filter"
DECISION_SOURCE_BEDROCK_GUARDRAIL = "bedrock_guardrail"
DECISION_SOURCE_AGENT_SELF_REFUSAL = "agent_self_refusal"
DECISION_SOURCE_RUNNER_LOCAL = "runner_local"
DECISION_SOURCE_INVOKER_ERROR = "invoker_error"


Invoker = Callable[[CrossCloudStep, str], _InvocationOutcome]  # (step, session_id) -> outcome
PolicyApplyFn = Callable[[List[str]], dict]  # argv -> result dict
# Workstream 17 / LLD 17 §9.2 — controller decisions lookup. (session_id,
# request_id) → combined verdict dict, or None if no signals exist yet.
# Shape per /v1/sessions/{id}/decisions: {decision, reason, winning_source,
# signals: [...]}. Sub-100ms p95 because it's a DDB partition Query rather
# than a CloudWatch Insights query. (The legacy CloudWatch-Insights
# `AuditLookupFn` was removed in Workstream 18 M3.6 — see LLD 18 §9.3.)
DecisionsLookupFn = Callable[[str, str], Optional[dict]]


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class CrossCloudScenarioRunner:
    """Executes a scenario's cross_cloud.steps and aggregates the outcome.

    All side-effects (Bedrock invoke, Azure invoke, policy update) flow through
    injected functions. Tests can replace them with deterministic fakes; the
    `default_*_invoker` factories below wire the real cloud paths.
    """

    def __init__(
        self,
        *,
        bedrock_prompt_invoker: Invoker,
        azure_prompt_invoker: Invoker,
        azure_tool_invoker: Invoker,
        bedrock_tool_invoker: Optional[Invoker] = None,
        decisions_lookup_fn: Optional[DecisionsLookupFn] = None,
        policy_apply_fn: Optional[PolicyApplyFn] = None,
        policy_propagation_step_ids: tuple[str, ...] = ("probe_bedrock_after",),
        policy_remove_tool: Optional[str] = None,
        policy_agent_id: Optional[str] = None,
        policy_updates: Optional[List[dict]] = None,
    ) -> None:
        self._bedrock_prompt = bedrock_prompt_invoker
        self._azure_prompt = azure_prompt_invoker
        self._azure_tool = azure_tool_invoker
        # Workstream 18 / LLD 18 §4.2 — optional direct-invoke path for
        # Bedrock. When set, scenario steps with `tool:` route here instead of
        # going through the LLM. Required for deterministic enforcement-claim
        # scenarios (S2, S4). When not set, the runner falls back to the
        # prompt-only routing (any `tool:` Bedrock step raises in _pick_invoker).
        self._bedrock_tool = bedrock_tool_invoker
        # Workstream 17 / LLD 17 §9.2 — controller decisions lookup. Queries
        # /v1/sessions/{id}/decisions (DDB-backed, sub-100ms p95) for the
        # combined verdict on (session_id, request_id). The combiner result
        # drives the dashboard's "By" column. (The legacy
        # CloudWatch-Insights-backed `audit_lookup_fn` was removed in
        # Workstream 18 M3.6 — see LLD 18 §9.3.)
        self._decisions_lookup = decisions_lookup_fn
        self._policy_apply = policy_apply_fn
        # For S2 specifically: when the runner encounters the first step in
        # `policy_propagation_step_ids` it triggers `policy_apply_fn` once per
        # entry in `policy_updates`, then continues. Teardown re-adds each
        # removed tool in reverse order at end-of-scenario.
        self._policy_propagation_step_ids = set(policy_propagation_step_ids)
        # New multi-agent shape: list of {"agent_id": str, "remove_tool": str}
        # dicts. Demonstrates one control plane updating N policies across
        # clouds. If `policy_updates` is None, fall back to the legacy single
        # agent_id+remove_tool form so older test fixtures still work.
        if policy_updates is not None:
            self._policy_updates = list(policy_updates)
        elif policy_remove_tool and policy_agent_id:
            self._policy_updates = [
                {"agent_id": policy_agent_id, "remove_tool": policy_remove_tool},
            ]
        else:
            self._policy_updates = []

    def run(self, scenario: Any, *, session_id: Optional[str] = None) -> Iterator[StepResult]:
        """Execute the scenario's cross_cloud.steps in order, yielding StepResult per step.

        The same `session_id` flows into every step so cross_cloud_dependencies
        evaluations see all events under one session in the controller's DDB
        session-context table.
        """
        cross = getattr(scenario, "cross_cloud", None) or scenario.get("cross_cloud") if isinstance(scenario, dict) else getattr(scenario, "cross_cloud", None)
        if cross is None:
            raise ValueError(f"Scenario {getattr(scenario, 'scenario_id', '<?>')} has no cross_cloud block")

        sid = session_id or f"xcloud-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        policy_apply_triggered = False
        policy_apply_reverted = False

        for step in cross.steps if hasattr(cross, "steps") else cross["steps"]:
            # Coerce dict -> CrossCloudStep for uniform downstream handling.
            if isinstance(step, dict):
                if CrossCloudStep is None:  # pragma: no cover
                    raise RuntimeError("CrossCloudStep model not available — orchestrator package missing")
                step = CrossCloudStep(**step)

            # S2 hook: trigger the policy update(s) right before the first
            # post-update probe so the runner can measure propagation. The
            # hook fires once per entry in `policy_updates` — for cross-cloud
            # propagation, that's one update per cloud-native agent so each
            # post-update probe lands on a tightened policy.
            if (
                not policy_apply_triggered
                and step.id in self._policy_propagation_step_ids
                and self._policy_apply
                and self._policy_updates
            ):
                logger.info(
                    "Applying %d policy update(s) for S2: %s",
                    len(self._policy_updates),
                    [(u["agent_id"], u["remove_tool"]) for u in self._policy_updates],
                )
                policy_apply_triggered = True  # set before loop so teardown runs even on partial failure
                for update in self._policy_updates:
                    try:
                        self._policy_apply(
                            [
                                "--agent-id", update["agent_id"],
                                "--remove-tool", update["remove_tool"],
                                "--reason", f"S2 cross-cloud propagation demo ({update['agent_id']})",
                            ]
                        )
                    # Catch SystemExit too — apply_policy.py raises SystemExit
                    # on network/HTTP errors via its `_http` helper. Without
                    # this, the uncaught SystemExit propagates past Streamlit's
                    # run loop and leaves state["running"]=True forever
                    # (W17 deploy 2026-05-26 diagnosis).
                    except (Exception, SystemExit) as exc:
                        logger.error(
                            "Policy update for %s failed: %s",
                            update["agent_id"], exc, exc_info=True,
                        )
                        # Surface a synthetic failed step per failed agent so
                        # the UI shows exactly which cloud the propagation
                        # broke on.
                        yield StepResult(
                            step_id=f"_policy_update__{update['agent_id']}",
                            cloud="control_plane",
                            agent_id=update["agent_id"],
                            description=f"Apply policy update — remove {update['remove_tool']}",
                            expected_decision="N/A",
                            status=StepStatus.ERRORED,
                            error=str(exc),
                            started_at=_now_iso(),
                            finished_at=_now_iso(),
                        )

            yield self._execute(step, sid)

        # S2 teardown: restore baseline by re-adding each removed tool in
        # reverse order so dependency-style policies (rarely the case but cheap
        # insurance) restore in the same order they were torn down.
        if policy_apply_triggered and not policy_apply_reverted and self._policy_apply and self._policy_updates:
            for update in reversed(self._policy_updates):
                try:
                    self._policy_apply(
                        [
                            "--agent-id", update["agent_id"],
                            "--add-tool", update["remove_tool"],
                            "--reason", f"S2 cross-cloud propagation demo: restore baseline ({update['agent_id']})",
                        ]
                    )
                except (Exception, SystemExit) as exc:  # pragma: no cover — best-effort teardown
                    logger.warning(
                        "Policy restore for %s failed (baseline NOT restored): %s",
                        update["agent_id"], exc,
                    )
            policy_apply_reverted = True

    def summarize(self, scenario: Any, session_id: str, steps: List[StepResult], started_at: str) -> ScenarioOutcome:
        finished = _now_iso()
        elapsed_ms = _iso_delta_ms(started_at, finished)
        deny = sum(1 for s in steps if s.actual_decision == "DENY")
        allow = sum(1 for s in steps if s.actual_decision == "ALLOW")
        errs = sum(1 for s in steps if s.status == StepStatus.ERRORED)
        clouds = {s.cloud for s in steps}
        passed = all(s.passed for s in steps)
        cross = getattr(scenario, "cross_cloud", None)
        template = (cross.outcome_template if cross else None) or "{deny_count} deny, {allow_count} allow, {error_count} error across {cloud_count} clouds in {elapsed_ms}ms"
        try:
            narrative = template.format(
                deny_count=deny,
                allow_count=allow,
                error_count=errs,
                cloud_count=len(clouds),
                elapsed_ms=elapsed_ms,
                total=len(steps),
            )
        except KeyError as exc:
            logger.warning("outcome_template missing key %s — falling back", exc)
            narrative = f"{deny} deny, {allow} allow, {errs} error in {elapsed_ms}ms"
        return ScenarioOutcome(
            scenario_id=getattr(scenario, "scenario_id", "<unknown>"),
            session_id=session_id,
            started_at=started_at,
            finished_at=finished,
            elapsed_ms=elapsed_ms,
            total=len(steps),
            deny_count=deny,
            allow_count=allow,
            error_count=errs,
            cloud_count=len(clouds),
            passed=passed,
            narrative=narrative,
            steps=steps,
        )

    def _execute(self, step: "CrossCloudStep", session_id: str) -> StepResult:
        started = _now_iso()
        # Workstream 17 / LLD 17 §9.1 — runner originates request_id and stamps
        # it on the step so invokers can thread it through to the underlying
        # connector (Bedrock sessionAttributes / Azure HTTP body). All signals
        # for this step land under one request_id, making the decisions
        # endpoint's combiner output authoritative.
        if step.request_id is None:
            step.request_id = f"xc-{step.id}-{uuid.uuid4().hex[:8]}"

        # Workstream 18 M2 / LLD 18 §4.3 — expand `{rand.foo}` / `{request_id}`
        # / `{session_id}` tokens in tool_params, user_input, prompt. Single
        # pass per step; same token expanded in two positions of the SAME
        # step gets the SAME value within that pass (one random roll per
        # generator invocation). Unknown tokens log WARN + stay in place.
        _apply_template_substitution(
            step, request_id=step.request_id, session_id=session_id,
        )

        signals_for_step: list[dict] = []
        try:
            invoker = self._pick_invoker(step)
            outcome = invoker(step, session_id)
        except Exception as exc:
            # Catches both routing errors (malformed step) and invoker-internal
            # crashes. The runner must never raise mid-scenario — investors
            # don't want to see a Python stack trace on stage.
            logger.error("Step %s failed: %s", step.id, exc, exc_info=True)
            return StepResult(
                step_id=step.id,
                cloud=step.cloud,
                agent_id=step.agent_id,
                description=step.description or "",
                expected_decision=step.expected_decision,
                status=StepStatus.ERRORED,
                error=str(exc),
                started_at=started,
                finished_at=_now_iso(),
            )

        # Preferred override path (LLD 17 §9.2): query /v1/sessions/{id}/decisions
        # for the controller's combined verdict on this (session_id, request_id).
        # This replaces the legacy audit_lookup which queried CloudWatch Insights
        # and was prone to the 60s+ indexing-lag race condition (LLD 17 §2).
        if (
            self._decisions_lookup is not None
            and outcome.decision in ("ALLOW", "DENY")
        ):
            try:
                payload = self._decisions_lookup(session_id, step.request_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "decisions lookup for %s/%s failed: %s",
                    session_id, step.request_id, exc,
                )
                payload = None
            if payload:
                combined = (payload or {}).get("combined") or {}
                authoritative = combined.get("decision")
                if authoritative in ("ALLOW", "DENY"):
                    if authoritative != outcome.decision:
                        logger.info(
                            "Step %s: controller decisions (%s) overrides invoker view (%s)",
                            step.id, authoritative, outcome.decision,
                        )
                    winning_source = combined.get("winning_source")
                    # If the winning source is one we have a UI badge for, use
                    # that exact label; otherwise treat anything sentra.* as
                    # the generic "sentra" badge so the runner doesn't grow
                    # source-by-source if-chains as new validators come online.
                    if winning_source and winning_source.startswith("sentra."):
                        ui_source = DECISION_SOURCE_SENTRA
                    elif winning_source == "bedrock_guardrail":
                        ui_source = DECISION_SOURCE_BEDROCK_GUARDRAIL
                    elif winning_source == "azure_content_filter":
                        ui_source = DECISION_SOURCE_AZURE_CONTENT_FILTER
                    else:
                        ui_source = DECISION_SOURCE_SENTRA
                    outcome = _InvocationOutcome(
                        decision=authoritative,
                        reason=combined.get("reason") or outcome.reason,
                        latency_ms=outcome.latency_ms,
                        raw={**outcome.raw, "decisions_override": payload},
                        error=outcome.error,
                        decision_source=ui_source,
                    )
                    signals_for_step = payload.get("signals") or []

        decision = outcome.decision
        status = self._classify(step, outcome)
        return StepResult(
            step_id=step.id,
            cloud=step.cloud,
            agent_id=step.agent_id,
            description=step.description or "",
            expected_decision=step.expected_decision,
            status=status,
            actual_decision=decision,
            reason=outcome.reason,
            latency_ms=outcome.latency_ms,
            started_at=started,
            finished_at=_now_iso(),
            error=outcome.error,
            action_summary=_summarize_step_action(step),
            decision_source=outcome.decision_source,
            signals=signals_for_step,
            raw=outcome.raw,
        )

    def _pick_invoker(self, step: "CrossCloudStep") -> Invoker:
        if step.cloud == "bedrock":
            # LLD 18 §4.2 — tool: routes to direct-invoke (schema-aware,
            # deterministic). prompt: routes to LLM-driven. Both supported;
            # scenario authors choose per-step based on intent (LLD 18 §4.4).
            if step.tool:
                if self._bedrock_tool is None:
                    raise ValueError(
                        f"Bedrock step {step.id} uses tool={step.tool!r} but no "
                        f"bedrock_tool_invoker was injected. Wire one via "
                        f"_build_runner (LLD 18 §4.2)."
                    )
                return self._bedrock_tool
            if step.prompt is not None:
                return self._bedrock_prompt
            raise ValueError(f"Bedrock step {step.id} requires either `tool` or `prompt`")
        if step.cloud == "azure_foundry":
            if step.tool:
                return self._azure_tool
            if step.prompt:
                return self._azure_prompt
            raise ValueError(f"Azure step {step.id} requires either `tool` or `prompt`")
        raise ValueError(f"Unknown cloud {step.cloud!r} on step {step.id}")

    @staticmethod
    def _classify(step: "CrossCloudStep", outcome: _InvocationOutcome) -> StepStatus:
        if outcome.error:
            return StepStatus.ERRORED
        if outcome.decision != step.expected_decision:
            return StepStatus.FAILED
        if step.expected_reason_contains and not (outcome.reason or "").lower().__contains__(step.expected_reason_contains.lower()):
            return StepStatus.FAILED
        # Demo-honesty check: if the YAML explicitly expected the decision to
        # come from a specific source (e.g., Sentra) and we got the right
        # verdict from a *different* source (e.g., Azure content filter caught
        # it before Sentra was consulted), fail the step. Otherwise the demo
        # narrative would silently bend — the investor sees "DENY ✅" while
        # the truth is "Sentra wasn't even on the call path".
        if step.expected_source and outcome.decision_source and step.expected_source != outcome.decision_source:
            return StepStatus.FAILED
        return StepStatus.PASSED


# ---------------------------------------------------------------------------
# Default invokers (real clouds)
# ---------------------------------------------------------------------------


def default_bedrock_prompt_invoker(
    *,
    caller_factory: Callable[[], Any],
    discover_fn: Callable[[str], Optional[dict]],
) -> Invoker:
    """Wire BedrockAgentCaller + discover_agents into a step invoker.

    `caller_factory()` returns a fresh BedrockAgentCaller. `discover_fn(symbolic_id)`
    returns the discovered `{id, alias_id}` for an agent symbolic name like
    "sentra-mvp-customer-service-agent". Both are injected so tests can pass fakes.

    Source attribution: BedrockConnector only sees the Bedrock-side guardrail
    verdict; if a tool-call hit Sentra's policy via the Action Group Lambda
    that happens out of band and only appears in the audit log. So the
    invoker reports the source as "bedrock_guardrail" for DENY (it's the only
    DENY this layer can produce) and leaves source unset for ALLOW so the
    audit-lookup can override to "sentra" if the controller saw the call.
    """
    def invoke(step: "CrossCloudStep", session_id: str) -> _InvocationOutcome:
        info = discover_fn(step.agent_id)
        if not info:
            return _InvocationOutcome(
                decision="ERROR",
                reason=f"Bedrock agent {step.agent_id} not discovered",
                latency_ms=0,
                raw={},
                error=f"agent {step.agent_id} not discovered",
                decision_source=DECISION_SOURCE_INVOKER_ERROR,
            )
        caller = caller_factory()
        t0 = time.perf_counter()
        try:
            result = caller.invoke_agent(
                agent_id=info["id"],
                agent_alias_id=info.get("alias_id", "TSTALIASID"),
                session_id=session_id,
                user_message=step.prompt or "",
                request_id=step.request_id,
            )
        except Exception as exc:
            return _InvocationOutcome(
                decision="ERROR",
                reason=None,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                raw={},
                error=str(exc),
                decision_source=DECISION_SOURCE_INVOKER_ERROR,
            )
        elapsed = int((time.perf_counter() - t0) * 1000)
        decision = result.get("decision") or "ERROR"
        reason = (result.get("validation_result") or {}).get("reason") if isinstance(result, dict) else None
        # Source: DENY here means Bedrock guardrail caught the prompt directly;
        # ALLOW leaves it open for audit-lookup override to "sentra".
        source = DECISION_SOURCE_BEDROCK_GUARDRAIL if decision == "DENY" else None
        return _InvocationOutcome(
            decision=decision,
            reason=reason,
            latency_ms=elapsed,
            raw=result if isinstance(result, dict) else {},
            error=result.get("error") if isinstance(result, dict) else None,
            decision_source=source,
        )
    return invoke


def default_azure_prompt_invoker(connector_factory: Callable[[], Any]) -> Invoker:
    """Drive the Azure agent through AzureConnector (LLM + tool-call loop).

    Source attribution:
      - If AzureConnector.invoke_agent returned decision=DENY with
        validation_result.reason == "azure_content_filter", Azure's content
        filter rejected the prompt *before* it reached gpt-4o-mini, which
        means Sentra was never consulted. Surface as `azure_content_filter`.
      - If AzureConnector returned DENY with any other reason, the LLM
        emitted a tool call and the Function App's /v1/validate round-trip
        produced the DENY → source is `sentra`.
      - ALLOW leaves source unset; the audit-lookup may attribute it to
        sentra if the controller logged the round-trip.
    """
    def invoke(step: "CrossCloudStep", session_id: str) -> _InvocationOutcome:
        connector = connector_factory()
        t0 = time.perf_counter()
        try:
            result = connector.invoke_agent(
                agent_id=step.agent_id,
                session_id=session_id,
                user_message=step.prompt or "",
                request_id=step.request_id,
            )
        except Exception as exc:
            return _InvocationOutcome(
                decision="ERROR",
                reason=None,
                latency_ms=int((time.perf_counter() - t0) * 1000),
                raw={},
                error=str(exc),
                decision_source=DECISION_SOURCE_INVOKER_ERROR,
            )
        elapsed = int((time.perf_counter() - t0) * 1000)
        decision = getattr(result, "decision", "ERROR")
        validation = getattr(result, "validation_result", None) or {}
        reason = validation.get("reason") if isinstance(validation, dict) else None
        source: Optional[str] = None
        if decision == "DENY":
            if (reason or "").lower() == "azure_content_filter":
                source = DECISION_SOURCE_AZURE_CONTENT_FILTER
            else:
                source = DECISION_SOURCE_SENTRA
        return _InvocationOutcome(
            decision=decision,
            reason=reason,
            latency_ms=elapsed,
            raw={"response": getattr(result, "response", ""), "trace": getattr(result, "trace", {})},
            error=getattr(result, "error", None),
            decision_source=source,
        )
    return invoke


def default_azure_tool_invoker(*, function_tool_url: Optional[str] = None, timeout_seconds: float = 30.0) -> Invoker:
    """POST directly to the Azure Function App's /api/tool/{tool_name} endpoint.

    Matches what AzureConnector does internally for one tool call but bypasses
    the LLM so a scenario can be deterministic. The Function App still calls
    Sentra for validation, so the audit log entry is identical to one produced
    by AzureConnector.
    """
    base = (function_tool_url or os.environ.get("AZURE_FUNCTION_TOOL_URL", "")).rstrip("/")

    def invoke(step: "CrossCloudStep", session_id: str) -> _InvocationOutcome:
        if not base:
            return _InvocationOutcome(
                decision="ERROR",
                reason="AZURE_FUNCTION_TOOL_URL not configured",
                latency_ms=0,
                raw={},
                error="missing AZURE_FUNCTION_TOOL_URL",
                decision_source=DECISION_SOURCE_INVOKER_ERROR,
            )
        url = f"{base}/{step.tool}"
        # user_input precedence: step.user_input (explicit) > step.description
        # > a generic placeholder. The scenario YAML uses this to feed Sentra's
        # sigma engine the actual attack payload — see S1 azure_attack step.
        user_input = step.user_input or step.description or f"S15-M5 scenario step {step.id}"
        body_dict: dict[str, Any] = {
            "params": step.tool_params,
            "session_id": session_id,
            "user_input": user_input,
        }
        if step.request_id:
            # Workstream 17 / LLD 17 §9.1.5 — Function App forwards this to
            # /v1/validate so every Sentra signal correlates back to this
            # logical step.
            body_dict["request_id"] = step.request_id
        body = json.dumps(body_dict).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json"},
        )
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
                raw = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # 403 from the Function App is a Sentra DENY surfaced over HTTP —
            # the Function called /v1/validate, the controller said DENY, the
            # Function passed that body back with status 403.
            elapsed = int((time.perf_counter() - t0) * 1000)
            try:
                raw = json.loads(exc.read().decode("utf-8"))
            except (ValueError, AttributeError):
                raw = {"decision": "DENY", "reason": f"Function HTTP {exc.code}"}
            return _InvocationOutcome(
                decision=raw.get("decision") or "DENY",
                reason=raw.get("reason"),
                latency_ms=elapsed,
                raw=raw,
                decision_source=DECISION_SOURCE_SENTRA,
            )
        except urllib.error.URLError as exc:
            return _InvocationOutcome(
                decision="ERROR",
                reason=f"Function unreachable: {exc}",
                latency_ms=int((time.perf_counter() - t0) * 1000),
                raw={},
                error=str(exc),
                decision_source=DECISION_SOURCE_INVOKER_ERROR,
            )
        elapsed = int((time.perf_counter() - t0) * 1000)
        decision = raw.get("decision") or "ALLOW"
        reason = (raw.get("validation") or {}).get("reason") or raw.get("reason")
        # Whether ALLOW or DENY, the Function App always consults Sentra before
        # responding — so this row's source is `sentra` either way.
        return _InvocationOutcome(
            decision=decision,
            reason=reason,
            latency_ms=elapsed,
            raw=raw,
            decision_source=DECISION_SOURCE_SENTRA,
        )
    return invoke


# Bedrock guardrail's slot in the deny-overrides combiner priority order.
# Mirrors connectors/bedrock/bedrock_connector._BEDROCK_GUARDRAIL_PRIORITY —
# importing would create a circular dep, so we restate the constant here. If
# either changes, both must change. (Combiner default_priority() in
# security-controller/app/combiners/sources.py is the source of truth.)
_BEDROCK_GUARDRAIL_PRIORITY = 20


def default_bedrock_tool_invoker(
    *,
    lambda_arn: str,
    schema_fetcher: Any,
    signals_client: Any,
    action_group: str = "customer_tools",
    region: str = "us-east-1",
    boto3_client: Optional[Any] = None,
) -> Invoker:
    """Direct-invoke the Bedrock Action Group Lambda, skipping the LLM.

    Mirrors `default_azure_tool_invoker` shape on the AWS side. Builds a
    schema-aware synthetic Action Group event (LLD 18 §4.2.3) so the Lambda's
    parameter parser receives properly-typed `properties` entries (integer
    declared as integer, number as number, etc.). The Lambda's body is
    unchanged — it still calls /v1/validate first, then executes the tool.

    Sentra is consulted on every invocation, deterministically. After the
    Lambda returns, a synthetic `bedrock_guardrail` ALLOW signal is posted to
    preserve LLD 17 §4 symmetric-emission (§4.2.4).

    Args:
        lambda_arn: ARN of the Action Group Lambda (e.g.
            arn:aws:lambda:us-east-1:...:function:sentra-mvp-bedrock-agent-actions).
            v0.1 hardcoded single-action-group constraint (LLD 18 §4.2.2).
        schema_fetcher: `BedrockSchemaFetcher` instance. Required — the
            invoker uses it to type-tag every param per the agent's OpenAPI.
        signals_client: `SignalsClient` for the synthetic bedrock_guardrail
            ALLOW emission. Best-effort; failures log WARN but don't fail
            the step.
        action_group: Action group name; default `customer_tools`. v0.1
            assumes a single AG per agent (LLD 18 §4.2.2).
        region: AWS region the Lambda lives in.
        boto3_client: Inject a mock for tests. Otherwise built lazily.
    """
    import uuid

    client = boto3_client or boto3.client("lambda", region_name=region)

    def _build_properties(tool_name: str, params: dict, schema: dict) -> list[dict]:
        """Convert {param: value} dict to typed Bedrock properties array.

        For each param, look up its OpenAPI declared type from the agent's
        schema, then emit a properly-typed properties entry. Unknown params
        (caller-supplied but not in schema) emit as string with a warning —
        the schema validator (M3) catches these at orchestrator startup, so
        a runtime warning means the validator was skipped.
        """
        tool_schema = (schema or {}).get(tool_name) or {}
        tool_params_schema = tool_schema.get("parameters") or {}
        properties = []
        for name, raw_value in (params or {}).items():
            declared = tool_params_schema.get(name)
            if declared is None:
                logger.warning(
                    "bedrock_tool_invoker: param %r not in OpenAPI schema for tool %r "
                    "(scenario validator should have caught this); defaulting to string",
                    name, tool_name,
                )
                properties.append({"name": name, "type": "string", "value": str(raw_value)})
                continue
            openapi_type = declared.get("openapi_type", "string")
            bedrock_type = declared.get("type", "string")
            try:
                coerced = schema_fetcher.coerce_param(openapi_type, raw_value)
            except (TypeError, ValueError) as exc:
                logger.warning(
                    "bedrock_tool_invoker: failed to coerce %r=%r to %s for tool %r: %s",
                    name, raw_value, openapi_type, tool_name, exc,
                )
                coerced = raw_value
            properties.append({"name": name, "type": bedrock_type, "value": coerced})
        return properties

    def invoke(step: "CrossCloudStep", session_id: str) -> _InvocationOutcome:
        # request_id is assigned by the runner pre-_execute; sanity check.
        if not step.request_id:
            step.request_id = f"bedrock-tool-{uuid.uuid4().hex[:12]}"

        # Schema-aware type tagging — LLD 18 §4.2.3.
        try:
            schema = schema_fetcher.get(step.agent_id)
        except Exception as exc:
            logger.error("BedrockSchemaFetcher.get(%s) failed: %s", step.agent_id, exc)
            return _InvocationOutcome(
                decision="ERROR",
                reason=f"Bedrock schema unavailable: {exc}",
                latency_ms=0,
                raw={},
                error=str(exc),
                decision_source=DECISION_SOURCE_INVOKER_ERROR,
            )

        properties = _build_properties(step.tool, step.tool_params or {}, schema)
        event = {
            "messageVersion": "1.0",
            "agent": {
                "name": step.agent_id,
                "id": "direct-invoke",
                "alias": "direct",
                "version": "DRAFT",
            },
            "sessionId": session_id,
            "sessionAttributes": {"sentra_request_id": step.request_id},
            "promptSessionAttributes": {},
            "actionGroup": action_group,
            "apiPath": f"/{step.tool}",
            "httpMethod": "POST",
            "requestBody": {
                "content": {
                    "application/json": {"properties": properties}
                }
            },
            "inputText": step.user_input or f"direct-invoke:{step.tool}",
        }

        t0 = time.perf_counter()
        try:
            resp = client.invoke(
                FunctionName=lambda_arn,
                InvocationType="RequestResponse",
                Payload=json.dumps(event).encode("utf-8"),
            )
            payload_raw = resp["Payload"].read()
            payload = json.loads(payload_raw.decode("utf-8")) if payload_raw else {}
        except Exception as exc:
            logger.error("Lambda invoke failed for %s/%s: %s", step.agent_id, step.tool, exc)
            return _InvocationOutcome(
                decision="ERROR",
                reason=f"Lambda invoke failed: {exc}",
                latency_ms=int((time.perf_counter() - t0) * 1000),
                raw={},
                error=str(exc),
                decision_source=DECISION_SOURCE_INVOKER_ERROR,
            )
        elapsed = int((time.perf_counter() - t0) * 1000)

        # Parse OpenAPI envelope.
        envelope = (payload or {}).get("response") or {}
        status_code = envelope.get("httpStatusCode") or 500
        body_str = (
            ((envelope.get("responseBody") or {}).get("application/json") or {})
            .get("body")
            or "{}"
        )
        try:
            body = json.loads(body_str)
        except (TypeError, ValueError):
            body = {}

        # The Lambda's existing handler returns:
        #   ALLOW: 200 + {success: true, ...result}
        #   DENY:  403 + {success: false, error, decision: "DENY", request_id}
        if status_code == 200:
            decision = "ALLOW"
            reason = body.get("reason") or "Tool invocation allowed by Sentra"
        elif status_code == 403:
            decision = body.get("decision") or "DENY"
            reason = body.get("error") or body.get("reason") or "Denied by Sentra"
        else:
            decision = body.get("decision") or "ERROR"
            reason = body.get("error") or body.get("reason") or f"Lambda HTTP {status_code}"

        # Symmetric bedrock_guardrail emission — LLD 18 §4.2.4 / LLD 17 §4.
        # Always ALLOW with metadata.direct_invoke=true so the dashboard
        # expander shows "🟧 Bedrock Guardrail: ALLOW (direct-invoke, LLM bypassed)"
        # rather than implying the guardrail wasn't deployed.
        try:
            signals_client.post_signal(
                session_id=session_id,
                request_id=step.request_id,
                source="bedrock_guardrail",
                decision="ALLOW",
                reason="direct-invoke (LLM bypassed for deterministic scenario run)",
                priority=_BEDROCK_GUARDRAIL_PRIORITY,
                agent_id=step.agent_id,
                platform="bedrock",
                cloud_region=region,
                metadata={
                    "direct_invoke": True,
                    "invoker": "default_bedrock_tool_invoker",
                },
            )
        except Exception as exc:  # noqa: BLE001 — best-effort by design
            logger.warning(
                "synthetic bedrock_guardrail signal post failed for %s/%s: %s",
                session_id, step.request_id, exc,
            )

        return _InvocationOutcome(
            decision=decision,
            reason=reason,
            latency_ms=elapsed,
            raw=payload,
            error=None,
            decision_source=DECISION_SOURCE_SENTRA,
        )

    return invoke


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _apply_template_substitution(
    step: "CrossCloudStep",
    *,
    request_id: str,
    session_id: str,
) -> None:
    """Expand `{rand.foo}` / `{request_id}` / `{session_id}` tokens in
    `step.tool_params`, `step.user_input`, `step.prompt`. Mutates `step`
    in place so downstream invokers see the substituted values.

    Substitution is one pass — same generator may yield different values on
    a second call, so callers that need stable values across positions should
    invoke this once per step.

    See Workstream 18 M2 / LLD 18 §4.3.
    """
    # Import inline + tolerant: dashboard runtime resolves
    # `components.scenario_templates` via PYTHONPATH; unit tests that load
    # this file standalone via importlib don't have that path on sys.path.
    # Falling back to no-op in that case keeps the runner test surface
    # decoupled from the template-substitution feature (templates have
    # their own dedicated tests in tests/unit/test_scenario_templates.py).
    try:
        from components.scenario_templates import substitute, substitute_dict
    except ImportError:
        try:
            # Sibling-file fallback for importlib-loaded test contexts.
            import importlib.util
            import pathlib
            here = pathlib.Path(__file__).resolve().parent
            spec = importlib.util.spec_from_file_location(
                "scenario_templates_runtime", here / "scenario_templates.py",
            )
            if spec is None or spec.loader is None:
                return
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            substitute = mod.substitute
            substitute_dict = mod.substitute_dict
        except Exception as exc:  # noqa: BLE001
            logger.debug("template substitution unavailable: %s", exc)
            return

    if step.tool_params:
        step.tool_params = substitute_dict(
            step.tool_params, request_id=request_id, session_id=session_id,
        )
    if step.user_input:
        step.user_input = substitute(
            step.user_input, request_id=request_id, session_id=session_id,
        )
    if step.prompt:
        step.prompt = substitute(
            step.prompt, request_id=request_id, session_id=session_id,
        )


def _summarize_step_action(step: "CrossCloudStep") -> str:
    """One-line description of what the step actually fired — prompt or tool.

    Used by the dashboard events table so investors can see *which* attack
    payload corresponded to each row without scrolling the YAML.
    """
    if step.tool:
        param_str = ", ".join(f"{k}={v!r}" for k, v in (step.tool_params or {}).items())
        if len(param_str) > 80:
            param_str = param_str[:77] + "…"
        return f"🛠 {step.tool}({param_str})"
    if step.prompt:
        prompt = step.prompt.strip().replace("\n", " ")
        if len(prompt) > 120:
            prompt = prompt[:117] + "…"
        return f"💬 {prompt}"
    return "—"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _iso_delta_ms(start: str, end: str) -> int:
    s = datetime.fromisoformat(start.replace("Z", "+00:00"))
    e = datetime.fromisoformat(end.replace("Z", "+00:00"))
    return int((e - s).total_seconds() * 1000)


# ---------------------------------------------------------------------------
# Scenario metadata constants (S2 hook config)
# ---------------------------------------------------------------------------


# Per-scenario knobs the runner needs but YAML doesn't yet express cleanly.
# Keep this table tiny — large branches belong in scenario YAMLs, not here.
SCENARIO_HOOKS: dict[str, dict[str, Any]] = {
    "s2_cross_cloud_policy_propagation": {
        # One control plane, two cloud-native agents enforcing in lockstep:
        # remove `query_customers` from the AWS-side customer-service-agent
        # AND `check_fraud_score` from the Azure-side verification-agent in
        # one shot. Each post-update probe lands on its own tightened policy
        # and DENIes — that's the actual demo. Updating only one agent makes
        # the other cloud's probe trivially ALLOW (it has no relationship to
        # the policy that moved), which is what we saw on 2026-05-26.
        "policy_updates": [
            {"agent_id": "sentra-mvp-customer-service-agent", "remove_tool": "query_customers"},
            {"agent_id": "azure-verification-agent", "remove_tool": "check_fraud_score"},
        ],
        "policy_propagation_step_ids": ("probe_bedrock_after",),
    },
}
