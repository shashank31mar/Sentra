"""Template substitution for scenario YAMLs — LLD 18 §4.3 / Workstream 18 M2.

Scenario YAMLs can reference dynamic values via `{rand.foo}` tokens that the
runner substitutes per-fire. Keeps scenarios from drifting into copy-paste
duplication and lets fuzzing live alongside deterministic tests.

Design constraints (LLD 18 §4.3):
  - **Allow-list only.** Scenario authors cannot embed arbitrary Python.
  - **Pure functions** with no side effects other than RNG.
  - **Per-step regeneration.** Same token in two places in one step yields
    the SAME value (one substitution pass per step). Across steps, values
    re-roll.
  - **Unknown tokens log WARN and leave the placeholder.** A typo is visible
    in the output, not silently dropped.

Token taxonomy:
  - `{rand.*}` — random per-substitution-call values from a curated set
  - `{request_id}` / `{session_id}` — runtime correlation IDs passed in by
    the runner; not in the random registry
"""

from __future__ import annotations

import logging
import random
import re
import uuid
from typing import Any, Callable

logger = logging.getLogger(__name__)


# Curated random generators. Each entry is `token_key -> zero-arg callable`.
# Adding a new token is a one-line registry entry; never accept user-supplied
# code paths.
_US_STATES = (
    "CA", "NY", "TX", "FL", "IL", "PA", "OH", "GA", "NC", "MI",
    "NJ", "VA", "WA", "AZ", "MA", "TN", "IN", "MO", "MD", "WI",
)


def _rand_uuid() -> str:
    return uuid.uuid4().hex[:8]


def _rand_us_state() -> str:
    return random.choice(_US_STATES)


def _rand_customer_id() -> str:
    return f"C{random.randint(1, 9999):04d}"


def _rand_transaction_id() -> str:
    return f"tx-{uuid.uuid4().hex[:12]}"


def _rand_order_id() -> str:
    return f"ORD-{random.randint(10000, 99999)}"


# Module-level registry — frozen at import. Validator (M3) cross-checks
# template tokens in scenario YAMLs against this.
SUBSTITUTION_REGISTRY: dict[str, Callable[[], str]] = {
    "rand.uuid": _rand_uuid,
    "rand.us_state": _rand_us_state,
    "rand.state": _rand_us_state,  # alias — common in scenarios
    "rand.customer_id": _rand_customer_id,
    "rand.transaction_id": _rand_transaction_id,
    "rand.order_id": _rand_order_id,
}


# Regex matches `{some.token}` — does NOT match nested braces or whitespace
# inside braces. Strict by design.
_TOKEN_RE = re.compile(r"\{([a-zA-Z0-9_.]+)\}")


def list_known_tokens() -> set[str]:
    """All token keys recognized by the substituter. Includes runtime tokens
    (request_id, session_id) that aren't in SUBSTITUTION_REGISTRY but are
    populated per-call by `substitute(...)`."""
    return set(SUBSTITUTION_REGISTRY.keys()) | {"request_id", "session_id"}


def substitute(
    text: str,
    *,
    request_id: str | None = None,
    session_id: str | None = None,
) -> str:
    """Substitute `{token}` placeholders in `text`.

    Unknown tokens log WARN and stay in place. Known tokens substitute via the
    registry (per-call random) or from the runtime context (`request_id`,
    `session_id`).

    Idempotency note: each call rolls fresh random values. Don't call
    substitute() twice on the same string expecting the same output.
    """
    if not text or "{" not in text:
        return text

    def _replace(match: re.Match) -> str:
        key = match.group(1)
        if key == "request_id":
            if request_id is None:
                logger.warning(
                    "substitute: {request_id} used but no request_id passed; "
                    "leaving placeholder"
                )
                return match.group(0)
            return request_id
        if key == "session_id":
            if session_id is None:
                logger.warning(
                    "substitute: {session_id} used but no session_id passed; "
                    "leaving placeholder"
                )
                return match.group(0)
            return session_id
        generator = SUBSTITUTION_REGISTRY.get(key)
        if generator is None:
            logger.warning(
                "substitute: unknown token {%s} in text; leaving placeholder. "
                "Known tokens: %s",
                key, sorted(list_known_tokens()),
            )
            return match.group(0)
        try:
            return str(generator())
        except Exception as exc:  # noqa: BLE001 — defensive
            logger.error("substitute: generator %s raised: %s", key, exc)
            return match.group(0)

    return _TOKEN_RE.sub(_replace, text)


def substitute_dict(
    d: dict[str, Any],
    *,
    request_id: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Apply `substitute()` to every string value in a dict (one level deep).

    Used by the runner to expand `tool_params` before invocation. Non-string
    values pass through unchanged — tokens only make sense in string positions.
    """
    if not d:
        return d
    result: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, str):
            result[k] = substitute(v, request_id=request_id, session_id=session_id)
        else:
            result[k] = v
    return result


def find_tokens(text: str) -> list[str]:
    """Return the list of token names referenced in text (for validator)."""
    if not text or "{" not in text:
        return []
    return [m.group(1) for m in _TOKEN_RE.finditer(text)]
