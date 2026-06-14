"""Entity-store synthesizer (CT05b, feature §6.1).

Cedar evaluates over **entities**, not loose dicts. Per request the pipeline
builds a small, self-contained entity store. The crucial detail is the
**split origin of the principal**:

  * identity + cloud come from the AGENT record (`cloud_region`, §2.3),
  * authz attributes come from the BOUND POLICY (`allowed_tools`,
    `allowed_agents`, `max_refund_amount`),
  * the `Agent` principal entity is the per-request MERGE of the two.

The store also includes the `Tool`/`Agent` **resource** entities, not just the
principal, so allow-list set-membership references resolve. `Tool` entities carry
NO attributes today (cross-cloud preconditions are not enforced by Cedar — they
stay in context_validator). Every `Agent` entity carries the schema-required
`allowed_tools`/`allowed_agents` (empty sets are fine).

Units: `max_refund_amount` is emitted as **Long cents** (the structured source
stores dollars; we convert here) and defaults to **$5,000 → 500000 cents** when
the policy omits it — exactly `policy_engine`'s hardcoded default, so the
attribute is always present (no `principal has max_refund_amount` fail-open).
"""
from __future__ import annotations

import logging
from typing import Optional

from app.validators.cedar.evaluator import entities_to_json

logger = logging.getLogger(__name__)

# policy_engine.py:286 default — an absent max_refund_amount still enforces $5,000.
DEFAULT_MAX_REFUND_DOLLARS = 5000


def _escape(uid_id: str) -> str:
    """Escape a Cedar entity-id literal (backslash + double-quote)."""
    return uid_id.replace("\\", "\\\\").replace('"', '\\"')


def agent_uid_id(tenant_id: str, agent_id: str) -> str:
    """The tenant-scoped Agent entity id: `{tenant}#{agent_id}` (§6)."""
    return f"{tenant_id}#{agent_id}"


def agent_uid(tenant_id: str, agent_id: str) -> str:
    """Agent principal/resource uid string, e.g. `Agent::"tenant-a#agent-1"`."""
    return f'Agent::"{_escape(agent_uid_id(tenant_id, agent_id))}"'


def tool_uid(tool_name: str) -> str:
    """Tool resource uid string, e.g. `Tool::"process_refund"`."""
    return f'Tool::"{_escape(tool_name)}"'


def _max_refund_cents(policy: dict) -> int:
    raw = policy.get("max_refund_amount", DEFAULT_MAX_REFUND_DOLLARS)
    try:
        dollars = float(raw)
    except (TypeError, ValueError):
        logger.error("max_refund_amount %r not numeric; using $%d default", raw, DEFAULT_MAX_REFUND_DOLLARS)
        dollars = float(DEFAULT_MAX_REFUND_DOLLARS)
    return int(round(dollars * 100))


def _tool_entity(name: str) -> dict:
    # The entity-store id is a plain JSON string — Cedar-string escaping applies
    # only to the `Tool::"…"` uid-string form (see tool_uid), not here. Tool
    # entities carry no attributes today (cross-cloud preconditions are NOT
    # enforced by Cedar — they stay in context_validator; see baseline-v1.cedar).
    return {"uid": {"type": "Tool", "id": name}, "attrs": {}, "parents": []}


def _bare_agent_entity(uid_id: str) -> dict:
    # Resource/target Agent — schema-required attrs present, empty.
    return {"uid": {"type": "Agent", "id": uid_id}, "attrs": {"allowed_tools": [], "allowed_agents": []}, "parents": []}


def synthesize_entities(
    *,
    tenant_id: str,
    agent_id: str,
    policy: dict,
    requested_tool: Optional[str] = None,
    target_agent: Optional[str] = None,
) -> str:
    """Build the per-request entity store and return it as a JSON string.

    Includes: the merged principal Agent (allow-lists + refund cap); a Tool
    entity for every allowed tool plus the requested tool (so allow-list
    membership references resolve); and an Agent entity for every allowed agent
    (plus the invocation target).
    """
    allowed_tools = list(policy.get("allowed_tools", []) or [])
    allowed_agents = list(policy.get("allowed_agents", []) or [])

    principal = {
        "uid": {"type": "Agent", "id": agent_uid_id(tenant_id, agent_id)},
        "attrs": {
            "allowed_tools": [{"__entity": {"type": "Tool", "id": t}} for t in allowed_tools],
            "allowed_agents": [
                {"__entity": {"type": "Agent", "id": agent_uid_id(tenant_id, a)}} for a in allowed_agents
            ],
            "max_refund_amount": _max_refund_cents(policy),
        },
        "parents": [],
    }

    entities: list[dict] = [principal]

    # Tool resource entities — allow-list ∪ requested tool.
    tool_names: set[str] = set(allowed_tools)
    if requested_tool:
        tool_names.add(requested_tool)
    for name in sorted(tool_names):
        entities.append(_tool_entity(name))

    # Agent resource entities — allow-list + invocation target (tenant-scoped).
    agent_ids: set[str] = {agent_uid_id(tenant_id, a) for a in allowed_agents}
    if target_agent:
        agent_ids.add(agent_uid_id(tenant_id, target_agent))
    # Don't redefine the principal.
    agent_ids.discard(agent_uid_id(tenant_id, agent_id))
    for uid_id in sorted(agent_ids):
        entities.append(_bare_agent_entity(uid_id))

    return entities_to_json(entities)
