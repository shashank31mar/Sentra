"""
Canonical cursor pagination helpers (WS-21 T06 / LLD 21 §11.1).

Every list endpoint uses one standard: request `limit` + opaque `cursor`,
response `next_token` (null ⇒ last page). No `has_more`, no offset/page params
(DynamoDB has no offset). The opaque token is a base64-encoded DynamoDB
`LastEvaluatedKey`; callers MUST treat it as opaque and round-trip it unchanged.
"""
import base64
import json
from typing import Any, Dict, Optional


def encode_cursor(last_evaluated_key: Dict[str, Any]) -> str:
    """Base64-encode a DynamoDB LastEvaluatedKey into an opaque next_token."""
    return base64.b64encode(
        json.dumps(last_evaluated_key, default=str).encode("utf-8")
    ).decode("ascii")


def decode_cursor(cursor: str) -> Dict[str, Any]:
    """Decode an opaque next_token back into a DynamoDB ExclusiveStartKey.

    Raises ValueError on a malformed token (routes map this to HTTP 400).
    """
    try:
        raw = base64.b64decode(cursor.encode("ascii")).decode("utf-8")
        return json.loads(raw)
    except Exception as exc:  # noqa: BLE001 - normalize to ValueError for the route
        raise ValueError(f"invalid cursor: {exc}") from exc


def next_token_from_response(ddb_response: Dict[str, Any]) -> Optional[str]:
    """Return the next_token for a DDB query/scan response, or None if last page."""
    lek = ddb_response.get("LastEvaluatedKey")
    return encode_cursor(lek) if lek else None
