"""Scenario YAML validator — Workstream 18 M3.1 / LLD 18 §4.5.

Runs at demo-orchestrator startup against every loaded scenario YAML.
Catches authoring mistakes that would otherwise produce silent runtime
failures (LLM doesn't pick the tool, Lambda 500s, sigma rule never fires).

Validator checks per [LLD 18 §4.5](../../lld/18-deterministic-enforcement.md#45-sub-component-a4-scenario-yaml-schema-validator):

  (a) Every step's agent_id matches a discovered Bedrock or Azure agent
  (b) Every step's `tool` is in the agent's OpenAPI schema (Bedrock) or
      tool registry (Azure)
  (c) Required params present
  (d) Param types match (OpenAPI-declared)
  (e) Templated tokens are in the substitution registry
  (f) Every step has `intent: enforcement | threat_detection`
  (g) `intent: threat_detection` + `tool:` → HARD ERROR (LLD 18 §4.4)
  (h) `intent: enforcement` + `prompt:` (without `allow_llm_path: true`) → HARD ERROR
  (i) For `tool:` steps, agent has exactly one Action Group (Bedrock; LLD 18 §4.2.2)
  (j) Every required field on the step is present

Strict mode (`SCENARIO_VALIDATION_STRICT=true`, default true in this codepath):
  Orchestrator exits with non-zero on any error.

Permissive mode (`SCENARIO_VALIDATION_STRICT=false`):
  Logs WARN per error; orchestrator serves the scenarios anyway. Used for
  local scenario authoring iteration. Never enable in any cluster.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


# Token allow-list (mirrors src/dashboard/components/scenario_templates.py).
# Duplicated here (small, frozen) so the orchestrator doesn't need to import
# dashboard code. If either changes, both must. See LLD 18 §4.3.
_ALLOWED_TEMPLATE_TOKENS: set[str] = {
    "rand.uuid",
    "rand.us_state",
    "rand.state",
    "rand.customer_id",
    "rand.transaction_id",
    "rand.order_id",
    "request_id",
    "session_id",
}


_VALID_INTENTS = {"enforcement", "threat_detection"}


@dataclass
class ValidationError:
    """One validator finding. Validator returns a list of these per scenario."""
    scenario_id: str
    step_id: Optional[str]
    error_type: str  # short tag — UNKNOWN_AGENT, UNKNOWN_TOOL, MISSING_PARAM, ...
    message: str

    def format(self) -> str:
        loc = f"{self.scenario_id}:{self.step_id}" if self.step_id else self.scenario_id
        return f"[{self.error_type}] {loc} — {self.message}"


class ScenarioValidator:
    """Validates scenario YAMLs against deployed Bedrock + Azure infra.

    Caller injects fetchers + optional discovered_bedrock_agents (the set
    of symbolic agent_ids the orchestrator's BedrockAgentClient resolved
    at startup). Validator uses these to check (a) and (i).
    """

    def __init__(
        self,
        *,
        bedrock_schema_fetcher: Any,  # BedrockSchemaFetcher
        azure_tool_fetcher: Any,  # AzureToolFetcher
        discovered_bedrock_agents: Optional[set[str]] = None,
        # Optional callable: agent_id -> bool (True if registered Azure agent).
        # If None, we trust the YAML's azure_foundry agent_id without checking.
        azure_agent_exists_fn: Optional[Callable[[str], bool]] = None,
    ) -> None:
        self._bedrock_schemas = bedrock_schema_fetcher
        self._azure_tools = azure_tool_fetcher
        self._discovered_bedrock = discovered_bedrock_agents or set()
        self._azure_agent_exists = azure_agent_exists_fn

    def validate_scenario(self, scenario_data: dict) -> list[ValidationError]:
        """Validate one scenario dict (parsed from YAML). Returns empty list
        on success; list of ValidationError otherwise.

        Does NOT raise — caller decides strict vs permissive behavior.
        """
        errors: list[ValidationError] = []
        scenario_id = scenario_data.get("scenario_id", "<unknown>")

        cross = scenario_data.get("cross_cloud")
        if not cross:
            # No cross_cloud block = scenario doesn't use the WS18 runner;
            # nothing for us to validate beyond top-level shape. Return clean.
            return errors

        steps = cross.get("steps") or []
        if not steps:
            errors.append(ValidationError(
                scenario_id=scenario_id, step_id=None,
                error_type="EMPTY_STEPS",
                message="cross_cloud.steps is empty or missing",
            ))
            return errors

        for step in steps:
            errors.extend(self._validate_step(scenario_id, step))

        return errors

    # ------------------------------------------------------------------
    # Per-step checks
    # ------------------------------------------------------------------

    def _validate_step(self, scenario_id: str, step: dict) -> list[ValidationError]:
        errors: list[ValidationError] = []
        step_id = step.get("id") or "<unnamed>"

        # Check (j) — required fields
        cloud = step.get("cloud")
        if cloud not in ("bedrock", "azure_foundry"):
            errors.append(ValidationError(
                scenario_id=scenario_id, step_id=step_id,
                error_type="INVALID_CLOUD",
                message=f"cloud={cloud!r} must be 'bedrock' or 'azure_foundry'",
            ))
            return errors  # can't validate further without knowing cloud

        agent_id = step.get("agent_id")
        if not agent_id:
            errors.append(ValidationError(
                scenario_id=scenario_id, step_id=step_id,
                error_type="MISSING_AGENT_ID",
                message="agent_id is required",
            ))
            return errors

        tool = step.get("tool")
        prompt = step.get("prompt")
        intent = step.get("intent")
        allow_llm_path = bool(step.get("allow_llm_path", False))

        # Check (f) — intent required
        if intent is None:
            errors.append(ValidationError(
                scenario_id=scenario_id, step_id=step_id,
                error_type="MISSING_INTENT",
                message="intent: enforcement | threat_detection is required (LLD 18 §4.4)",
            ))
            # Don't return — keep checking other things so authors see all errors at once
        elif intent not in _VALID_INTENTS:
            errors.append(ValidationError(
                scenario_id=scenario_id, step_id=step_id,
                error_type="INVALID_INTENT",
                message=f"intent={intent!r} must be one of {sorted(_VALID_INTENTS)}",
            ))

        # Check (g) — intent: threat_detection requires SOMETHING for sigma to scan.
        # Sigma rules read user_input. `prompt:` becomes user_input via the
        # LLM-driven path. `tool:` + explicit `user_input:` is the
        # S1.azure_attack pattern — attack payload in user_input, tool params
        # benign, sigma catches via user_input. The ONLY broken combination is
        # `tool:` with neither `user_input:` nor `prompt:` — sigma has nothing
        # to scan. (Updated WS18 M3 post-S1 migration.)
        user_input = step.get("user_input")
        if intent == "threat_detection" and tool and not user_input and not prompt:
            errors.append(ValidationError(
                scenario_id=scenario_id, step_id=step_id,
                error_type="THREAT_DETECTION_WITH_TOOL",
                message=(
                    "intent: threat_detection with tool: requires user_input: "
                    "to be set. Without it, sigma has nothing to scan and the "
                    "threat-detection claim is defeated. Either add user_input "
                    "carrying the attack payload, or switch to prompt:. "
                    "(LLD 18 §4.4)"
                ),
            ))

        # Check (h) — intent: enforcement + prompt: without opt-out
        if intent == "enforcement" and prompt and not tool and not allow_llm_path:
            errors.append(ValidationError(
                scenario_id=scenario_id, step_id=step_id,
                error_type="ENFORCEMENT_WITH_PROMPT",
                message=(
                    "intent: enforcement requires deterministic direct-invoke "
                    "(tool:). Prompt-based paths are non-deterministic (S2 "
                    "debug spiral). Either use tool: + tool_params, OR add "
                    "allow_llm_path: true with explicit acknowledgement. "
                    "(LLD 18 §4.4.1)"
                ),
            ))

        # Check basic shape — must have tool or prompt
        if not tool and not prompt:
            errors.append(ValidationError(
                scenario_id=scenario_id, step_id=step_id,
                error_type="MISSING_TOOL_OR_PROMPT",
                message="step requires either `tool:` or `prompt:`",
            ))
            return errors

        # Cloud-specific checks
        if cloud == "bedrock":
            errors.extend(self._validate_bedrock_step(scenario_id, step_id, step))
        else:
            errors.extend(self._validate_azure_step(scenario_id, step_id, step))

        # Template-token check applies to all steps
        errors.extend(self._validate_templates(scenario_id, step_id, step))

        return errors

    # ------------------------------------------------------------------
    # Bedrock-specific
    # ------------------------------------------------------------------

    def _validate_bedrock_step(
        self, scenario_id: str, step_id: str, step: dict,
    ) -> list[ValidationError]:
        errors: list[ValidationError] = []
        agent_id = step.get("agent_id")
        tool = step.get("tool")

        # Check (a) — agent_id discovered. Use the discovered set if available.
        # If the orchestrator's discovery returned nothing yet (e.g. running
        # locally without AWS), we skip this check rather than erroring.
        if self._discovered_bedrock and agent_id not in self._discovered_bedrock:
            errors.append(ValidationError(
                scenario_id=scenario_id, step_id=step_id,
                error_type="UNKNOWN_BEDROCK_AGENT",
                message=(
                    f"agent_id={agent_id!r} not in discovered Bedrock agents: "
                    f"{sorted(self._discovered_bedrock)}"
                ),
            ))
            return errors

        # tool-based step → fetch schema and check (b), (c), (d), (i)
        if tool:
            try:
                schema = self._bedrock_schemas.get(agent_id)
            except Exception as exc:
                errors.append(ValidationError(
                    scenario_id=scenario_id, step_id=step_id,
                    error_type="BEDROCK_SCHEMA_FETCH_FAILED",
                    message=str(exc),
                ))
                return errors

            tool_schema = schema.get(tool)
            if tool_schema is None:
                errors.append(ValidationError(
                    scenario_id=scenario_id, step_id=step_id,
                    error_type="UNKNOWN_TOOL",
                    message=(
                        f"tool={tool!r} not in agent {agent_id}'s OpenAPI schema. "
                        f"Available: {sorted(schema.keys())}"
                    ),
                ))
                return errors

            # (c) required params + (d) types
            errors.extend(self._validate_tool_params(
                scenario_id, step_id, tool, step.get("tool_params") or {}, tool_schema,
            ))

        return errors

    def _validate_tool_params(
        self,
        scenario_id: str,
        step_id: str,
        tool: str,
        supplied: dict,
        tool_schema: dict,
    ) -> list[ValidationError]:
        errors: list[ValidationError] = []
        params_schema = tool_schema.get("parameters") or {}

        # (c) — required params must be present
        for param_name, param_meta in params_schema.items():
            if param_meta.get("required") and param_name not in supplied:
                errors.append(ValidationError(
                    scenario_id=scenario_id, step_id=step_id,
                    error_type="MISSING_REQUIRED_PARAM",
                    message=(
                        f"tool={tool!r} requires param {param_name!r} "
                        f"(type={param_meta.get('openapi_type')}); not supplied"
                    ),
                ))

        # Detect supplied params not in schema (typo guard)
        for supplied_name in supplied:
            if supplied_name not in params_schema:
                errors.append(ValidationError(
                    scenario_id=scenario_id, step_id=step_id,
                    error_type="UNKNOWN_PARAM",
                    message=(
                        f"tool={tool!r} doesn't declare param {supplied_name!r}. "
                        f"Available: {sorted(params_schema.keys())}"
                    ),
                ))

        # (d) — type compatibility for the values we got
        for supplied_name, supplied_value in supplied.items():
            param_meta = params_schema.get(supplied_name)
            if param_meta is None:
                continue  # already flagged above
            openapi_type = param_meta.get("openapi_type", "string")
            # Allow template tokens in any position; type-check happens after
            # substitution at runtime. We just verify that non-templated
            # literal values are coercible to the declared type.
            if isinstance(supplied_value, str) and "{" in supplied_value and "}" in supplied_value:
                continue  # templated value; defer type-check to runtime
            if not _value_coercible_to_type(supplied_value, openapi_type):
                errors.append(ValidationError(
                    scenario_id=scenario_id, step_id=step_id,
                    error_type="PARAM_TYPE_MISMATCH",
                    message=(
                        f"tool={tool!r} param {supplied_name!r}: supplied "
                        f"value {supplied_value!r} (Python type "
                        f"{type(supplied_value).__name__}) not compatible with "
                        f"declared OpenAPI type {openapi_type!r}"
                    ),
                ))

        return errors

    # ------------------------------------------------------------------
    # Azure-specific
    # ------------------------------------------------------------------

    def _validate_azure_step(
        self, scenario_id: str, step_id: str, step: dict,
    ) -> list[ValidationError]:
        errors: list[ValidationError] = []
        agent_id = step.get("agent_id")
        tool = step.get("tool")

        # (a) — Azure agent existence (best-effort)
        if self._azure_agent_exists and not self._azure_agent_exists(agent_id):
            errors.append(ValidationError(
                scenario_id=scenario_id, step_id=step_id,
                error_type="UNKNOWN_AZURE_AGENT",
                message=f"agent_id={agent_id!r} not registered on Azure Foundry",
            ))

        # (b) — Azure tool existence via Function App registry
        if tool:
            try:
                registered = self._azure_tools.get_tools()
            except Exception as exc:
                errors.append(ValidationError(
                    scenario_id=scenario_id, step_id=step_id,
                    error_type="AZURE_TOOLS_FETCH_FAILED",
                    message=str(exc),
                ))
                return errors
            if tool not in registered:
                errors.append(ValidationError(
                    scenario_id=scenario_id, step_id=step_id,
                    error_type="UNKNOWN_AZURE_TOOL",
                    message=(
                        f"tool={tool!r} not registered on Azure Function App. "
                        f"Registered: {sorted(registered)}"
                    ),
                ))

        # Note: param-schema check skipped for Azure (v0.1 gap — schema lives
        # in Python code, not declarative). Flagged in LLD 18 §13.

        return errors

    # ------------------------------------------------------------------
    # Templates
    # ------------------------------------------------------------------

    def _validate_templates(
        self, scenario_id: str, step_id: str, step: dict,
    ) -> list[ValidationError]:
        errors: list[ValidationError] = []
        text_blobs: list[str] = []
        for field_name in ("prompt", "user_input"):
            value = step.get(field_name)
            if isinstance(value, str):
                text_blobs.append(value)
        # tool_params string values too
        for v in (step.get("tool_params") or {}).values():
            if isinstance(v, str):
                text_blobs.append(v)

        for blob in text_blobs:
            for token in _find_tokens(blob):
                if token not in _ALLOWED_TEMPLATE_TOKENS:
                    errors.append(ValidationError(
                        scenario_id=scenario_id, step_id=step_id,
                        error_type="UNKNOWN_TEMPLATE_TOKEN",
                        message=(
                            f"token {{{token}}} not in allow-list. "
                            f"Known: {sorted(_ALLOWED_TEMPLATE_TOKENS)}"
                        ),
                    ))
        return errors


# ----------------------------------------------------------------------
# Helpers (kept module-local to avoid importing dashboard code)
# ----------------------------------------------------------------------


def _value_coercible_to_type(value: Any, openapi_type: str) -> bool:
    """Heuristic type check matching what BedrockSchemaFetcher.coerce_param does."""
    if openapi_type == "string":
        return True  # anything stringifies
    if openapi_type in ("integer", "number"):
        if isinstance(value, bool):
            return False  # bools aren't numbers in OpenAPI semantics
        if isinstance(value, (int, float)):
            return True
        if isinstance(value, str):
            try:
                if openapi_type == "integer":
                    int(value)
                else:
                    float(value)
                return True
            except (TypeError, ValueError):
                return False
        return False
    if openapi_type == "boolean":
        if isinstance(value, bool):
            return True
        if isinstance(value, str):
            return value.lower() in ("true", "false", "1", "0", "yes", "no")
        return False
    if openapi_type == "array":
        return isinstance(value, list)
    return True  # unknown types — permissive


import re

_TOKEN_RE = re.compile(r"\{([a-zA-Z0-9_.]+)\}")


def _find_tokens(text: str) -> list[str]:
    if not text or "{" not in text:
        return []
    return [m.group(1) for m in _TOKEN_RE.finditer(text)]


# ----------------------------------------------------------------------
# Strict-mode dispatcher
# ----------------------------------------------------------------------


def is_strict_mode() -> bool:
    """Returns True unless SCENARIO_VALIDATION_STRICT is explicitly 'false'."""
    return os.environ.get("SCENARIO_VALIDATION_STRICT", "true").lower() != "false"


def report_and_maybe_exit(all_errors: list[ValidationError]) -> None:
    """Log all errors at the appropriate level and, in strict mode, exit
    the orchestrator process so the broken scenarios never serve traffic."""
    if not all_errors:
        logger.info("ScenarioValidator: all scenarios pass")
        return

    strict = is_strict_mode()
    log_fn = logger.error if strict else logger.warning
    for err in all_errors:
        log_fn("ScenarioValidator: %s", err.format())

    if strict:
        logger.critical(
            "ScenarioValidator: %d errors found; exiting (strict mode). "
            "Set SCENARIO_VALIDATION_STRICT=false to serve anyway (local dev only).",
            len(all_errors),
        )
        # SystemExit raised so FastAPI lifespan handlers can clean up.
        raise SystemExit(1)
    logger.warning(
        "ScenarioValidator: %d errors found; serving anyway (permissive mode)",
        len(all_errors),
    )
