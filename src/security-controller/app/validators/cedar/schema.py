"""Sentra-owned Cedar schema + baseline policy loader (CT02).

The schema and the universal baseline policy set are bundled in the image
(`COPY src/security-controller/app/ ./app/`) and are the single source of truth.
A deploy-time step may publish them to S3 for auditability, but the runtime
always loads the bundled copy — no network read on the hot path.

`CEDAR_SCHEMA_VERSION` is part of the compiled-Cedar cache key (CT06): bump it and
every agent's compiled policy set is recomputed. Keep it in lockstep with the
`agent-policy-v{N}.cedarschema.json` filename.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

# Bump together with the schema filename below. Part of the CT06 cache key.
CEDAR_SCHEMA_VERSION = "v1"

_HERE = Path(__file__).resolve().parent
_SCHEMA_PATH = _HERE / f"agent-policy-{CEDAR_SCHEMA_VERSION}.cedarschema.json"
_BASELINE_PATH = _HERE / f"baseline-{CEDAR_SCHEMA_VERSION}.cedar"


@lru_cache(maxsize=1)
def get_schema_json() -> str:
    """The Cedar JSON schema as a string (the form `cedarpy` consumes)."""
    return _SCHEMA_PATH.read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def get_schema_dict() -> dict:
    """The Cedar JSON schema parsed — for introspection/tests."""
    return json.loads(get_schema_json())


@lru_cache(maxsize=1)
def get_baseline_policies() -> str:
    """The universal baseline Cedar policy set (feature §6).

    Per-agent variance lives in the synthesized entity store (CT05b); these
    rules are identical for every agent. The translator (CT08) appends any
    agent-specific rules to a copy of this set.
    """
    return _BASELINE_PATH.read_text(encoding="utf-8")
