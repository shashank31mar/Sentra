"""Thin Cedar evaluator wrapper (CT03).

One small interface over the `cedarpy` binding so the rest of the pipeline never
touches `cedarpy` directly — and so the backing engine could later be swapped
(localhost sidecar; AVP was rejected on the hot path, feature §9.1) without
touching callers. Pure and side-effect-free: no DynamoDB/S3, no pipeline types.

Cedar semantics this wrapper relies on (verified in the CT01 spike):
  * `cedarpy.is_authorized(request, policies, entities)` → `AuthzResult`.
  * `AuthzResult.decision` is `Decision.Allow` / `Decision.Deny`; **forbid wins**.
  * `AuthzResult.diagnostics.reasons` holds the determining policies' POSITIONAL
    ids (`policy0`, `policy1`, …); `diagnostics.id_annotations_by_reason` maps each
    back to its `@id("…")` annotation. We resolve through it so callers get the
    stable rule names (`forbid_refund_over_cap`), not parse-order positions.
  * `AuthzResult.diagnostics.errors` lists policies that ERRORED during eval
    (e.g. an unguarded missing-attribute access). A forbid that errors is
    DROPPED → fails OPEN, which is why the baseline policies `has`-guard every
    optional access. We surface these errors so CT04 can fail-secure.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Mapping

import cedarpy

from app.validators.cedar.schema import get_schema_json

logger = logging.getLogger(__name__)


class CedarEvaluationError(Exception):
    """Defensive catch-all for a genuine binding fault (the call itself threw).

    In practice `cedarpy` does NOT raise for the common malformed inputs — a
    malformed policy set or entity store comes back as `Decision.Deny` with the
    parse error in `diagnostics.errors` (fail-secure). Those surface via
    `CedarDecision.errors`, which CT04 maps to `POLICY_ERROR`. This exception
    only fires if the binding raises unexpectedly; CT04 treats it the same way."""


@dataclass(frozen=True)
class CedarDecision:
    """Outcome of one `isAuthorized` call."""

    allow: bool
    # Determining policy `@id`s (the rules Cedar used to reach `allow`).
    determining_policy_ids: list[str] = field(default_factory=list)
    # Per-policy evaluation errors (policies dropped mid-eval). Non-empty here
    # means at least one rule failed OPEN — CT04 inspects this to fail-secure.
    errors: list[str] = field(default_factory=list)


class CedarEvaluator:
    """Evaluates a fixed policy set against per-request principal/resource/context.

    The policy set is bound once at construction (it's the agent's compiled
    Cedar text, cached upstream by CT06); the entity store and request vary
    per call. Schema is loaded from the bundled CT02 artifact.
    """

    def __init__(self, policies: str):
        self._policies = policies

    def is_authorized(
        self,
        *,
        principal: str,
        action: str,
        resource: str,
        context: Mapping[str, Any],
        entities: str,
    ) -> CedarDecision:
        """Run one authorization query.

        Args mirror Cedar's request shape:
          principal/action/resource — entity-uid strings, e.g. `Agent::"t#a1"`,
            `Action::"UseTool"`, `Tool::"process_refund"`.
          context — a plain JSON-able dict (the assembled CedarContext).
          entities — the synthesized entity store as a JSON string (CT05b).
        """
        request = {
            "principal": principal,
            "action": action,
            "resource": resource,
            "context": dict(context),
        }
        try:
            result = cedarpy.is_authorized(request, self._policies, entities)
        except Exception as exc:  # malformed policy/entities, binding fault
            logger.exception("Cedar evaluation failed for %s on %s", principal, resource)
            raise CedarEvaluationError(str(exc)) from exc

        diag = result.diagnostics
        errors = [str(e) for e in (getattr(diag, "errors", None) or [])]
        if errors:
            # A dropped forbid fails OPEN — never silent. Surface for CT04.
            logger.warning("Cedar policy eval errors for %s on %s: %s", principal, resource, errors)

        # Resolve positional reason ids -> the policies' @id annotations.
        anno = getattr(diag, "id_annotations_by_reason", None) or {}
        determining = sorted(
            str(anno.get(r, r)) for r in (getattr(diag, "reasons", None) or [])
        )
        return CedarDecision(
            allow=result.decision == cedarpy.Decision.Allow,
            determining_policy_ids=determining,
            errors=errors,
        )


def validate_policy_set(policies: str) -> list[str]:
    """Validate a Cedar policy set against the Sentra schema (CT02/CT08/CT12).

    Returns a list of human-readable validation errors ([] == valid). Used by
    the translator and tests, NOT on the hot path.
    """
    result = cedarpy.validate_policies(policies, get_schema_json())
    if result.validation_passed:
        return []
    return [f"{e.policy_id}: {e.error}" for e in (result.errors or [])]


def entities_to_json(entities: list[dict]) -> str:
    """Serialize a synthesized entity store (list of Cedar entity dicts) to the
    JSON string the binding expects. Centralized so CT05b never hand-rolls it."""
    return json.dumps(entities)
