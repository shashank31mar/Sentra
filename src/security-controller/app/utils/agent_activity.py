"""Signal-derived agent activity — "is this agent receiving validate traffic?"

Feature §8.1: an agent is **Managed** (data flowing) once we observe its
`/v1/validate` signals; `last_active` is the most recent one. Presence is sticky
(once seen, stays Managed) and surfaced with a timestamp so a quiet agent is
visible. Source of truth = the validation-signal store's agent index (LLD 17).

This is the first app reader of the signal store's `agent-timestamp-index`.
"""
from typing import Dict, List

from botocore.exceptions import ClientError

from app.utils import tenancy

_AGENT_TS_INDEX = "agent-timestamp-index"


def last_active(signals_table, agent_ids: List[str]) -> Dict[str, str]:
    """Return ``{agent_id: latest timestamp_iso}`` for agents that have any
    validate signal. Agents with no traffic are simply absent from the map.

    One ``Limit=1`` newest-first GSI query per agent — fine at MVP scale; batch
    or cache if the fleet grows. Never raises: a missing/unavailable signal store
    yields an empty map (→ everything reads as not-yet-Managed, fail-honest).
    """
    out: Dict[str, str] = {}
    for aid in agent_ids:
        if not aid:
            continue
        kce, val = tenancy.agent_index_kce_value(aid)
        try:
            resp = signals_table.query(
                IndexName=_AGENT_TS_INDEX,
                KeyConditionExpression=kce,
                ExpressionAttributeValues={":agent_id": val},
                ProjectionExpression="timestamp_iso",
                Limit=1,
                ScanIndexForward=False,  # newest first
            )
            items = resp.get("Items", [])
            if items:
                out[aid] = items[0].get("timestamp_iso") or ""
        except ClientError:
            continue
    return out
