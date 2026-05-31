"""Decorator that stamps a Source.* string onto every ValidationResult a
validator returns — Workstream 17 / LLD 17 §4.

Why a decorator instead of editing every `return ValidationResult(...)` call:
the validators have 28 return sites total. A decorator is one line per
validator and keeps each validator's existing constructor calls untouched,
which makes the change easy to review and easy to revert.

Symmetric-emission rule (LLD 17 §4): every validator that runs emits
exactly one signal — ALLOW if it passed, DENY if it rejected. Validators
short-circuited by an upstream DENY (see ValidationService) don't emit;
that's handled at the orchestrator, not here.
"""

from __future__ import annotations

import functools
from typing import Callable

from app.api.models import ValidationResult


def stamps(source: str):
    """Decorator factory — stamps `source` onto the ValidationResult.

    Applied at the validator's primary public method (the one whose return
    value reaches ValidationService). Idempotent: if a result already has
    a source set (e.g. tests construct one manually), leave it alone.
    """

    def decorator(fn: Callable):
        if not _is_coroutine(fn):
            raise TypeError(
                f"stamps({source!r}) expects an async function; got {fn!r}"
            )

        @functools.wraps(fn)
        async def wrapper(*args, **kwargs):
            result = await fn(*args, **kwargs)
            if isinstance(result, ValidationResult) and result.source is None:
                # Pydantic BaseModel is mutable by default — set directly.
                # Avoids the model_copy round-trip cost on the hot path.
                result.source = source
            return result

        return wrapper

    return decorator


def _is_coroutine(fn: Callable) -> bool:
    import asyncio
    return asyncio.iscoroutinefunction(fn)
