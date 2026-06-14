"""CedarContext — context assembly + coercion (CT05, feature §5.1).

Cedar's verdict is only as good as the `context` it's handed. This module is the
ONE place that turns a `ValidationRequest` (+ stateful pipeline lookups) into the
context record Cedar evaluates — and crucially it **owns input coercion**, so a
parity disagreement is a real policy difference, never a parsing difference.

Per-field contract (feature §5.1 provenance table):

| field              | source                         | type      | missing-semantics                         | trust          |
|--------------------|--------------------------------|-----------|-------------------------------------------|----------------|
| amount             | tool_params → **Long cents**   | Long?     | omit ⇒ refund deny-on-missing fires       | ⚠ agent-supplied |
| fraud_risk         | tool_params.fraud_risk (lower) | String?   | omit ⇒ fraud rule doesn't fire            | 🔴 agent-supplied |
| cloud_region       | agent record (§2.3)            | String?   | omit                                      | ✅ controller    |

(Cross-cloud `preconditions_met` and rate `calls_this_minute` are NOT in the
Cedar context — no baseline rule references them; they stay in context_validator
/ abuse_detector, see the note below. If Cedar ever takes over the "decides,
pipeline computes" cross-cloud model, `preconditions_met` would be added here.)

🔴 Self-asserted-context caveat (feature §5.1): `amount` and `fraud_risk` come
from the calling agent's own `tool_params` today. A 1:1 port carries that
vulnerability forward — Cedar fixing the *principal* (verified identity) does NOT
fix self-asserted *context*. These fields are flagged `AGENT_SUPPLIED_FIELDS`;
hardening them to controller-derived signals is tracked separately. Ships no
worse than today, but explicitly not "solved".

Coercion mirrors `policy_engine.py` so shadow-mode parity is exact, with ONE
intentional improvement: a missing/non-coercible refund `amount` is OMITTED
(→ Cedar deny-on-missing → fail-secure DENY) rather than defaulted to `0` and
ALLOWed (policy_engine's fail-open). That divergence is cedar-intentional (CT09).
"""
from __future__ import annotations

import logging
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)

# Context fields sourced from the calling agent's own tool_params — untrusted
# (feature §5.1 caveat). Surfaced so audit/telemetry can flag self-asserted input.
AGENT_SUPPLIED_FIELDS = ("amount", "fraud_risk")


def coerce_amount_to_cents(raw: Any) -> Optional[int]:
    """Coerce a tool_params amount to integer **cents** (Cedar has no float).

    Accepts dollars as number or string with `$`/`,` adornment, exactly like
    `policy_engine` (`"$100,000"` → 10_000_000 cents). Returns None when the
    value is absent or non-coercible — the caller then OMITS `amount` so the
    refund deny-on-missing rule fails secure.
    """
    if raw is None:
        return None
    try:
        dollars = float(str(raw).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        logger.warning("Non-coercible refund amount %r — omitting (fail-secure)", raw)
        return None
    return int(round(dollars * 100))


def build_context(
    tool_params: Mapping[str, Any],
    *,
    cloud_region: Optional[str] = None,
) -> dict:
    """Assemble the Cedar `context` record.

    A field is included ONLY when it has a usable value, so the policies'
    `has`-guards / deny-on-missing rules behave as designed. `cloud_region` is
    the agent-sourced value (§2.3) passed in by the engine; `amount`/`fraud_risk`
    come from the request's tool_params. This function stays pure and trivially
    unit-testable.

    Note: cross-cloud preconditions and rate are NOT part of the Cedar context —
    they stay in `context_validator`/`abuse_detector` (feature §5; no baseline
    Cedar rule references them). If Cedar ever takes over the "decides, pipeline
    computes" cross-cloud model, the computed `preconditions_met` would be
    threaded in here.
    """
    context: dict[str, Any] = {}

    amount_cents = coerce_amount_to_cents(tool_params.get("amount"))
    if amount_cents is not None:
        context["amount"] = amount_cents

    fraud_risk = tool_params.get("fraud_risk")
    if fraud_risk is not None and str(fraud_risk).strip() != "":
        # Lowercased to match policy_engine's `== "high"` comparison.
        context["fraud_risk"] = str(fraud_risk).lower()

    if cloud_region:
        context["cloud_region"] = cloud_region

    return context
