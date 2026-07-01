"""Cedar policy loader (CT06).

Surfaces the Cedar evaluation inputs for `CedarPolicyEngine` WITHOUT disturbing
`PolicyEngine.get_agent_policy`, whose structured-dict return type four enforcement
consumers still depend on (cross_agent / context / abuse / validation_service —
the C6 blocker). This loader:

  * reuses `PolicyEngine.resolve_policy_bundle` for binding resolution +
    cloud-from-agent stamping (no duplication),
  * keeps the **structured source** dict (for entity synthesis + the non-Cedar
    fields Cedar never sees — allowed_callers, cross_cloud_dependencies, …),
  * loads the compiled `.cedar` co-artifact via the CT06c convention,
  * caches the compiled text by **`schema_version` + `content_hash` +
    `generator_version`** — the 3rd component closes the "generator fix, same
    source → stale compiled Cedar" hole. Only the immutable S3 body is cached;
    the metadata row is read fresh every call (two-layer freshness).
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

from app.validators.cedar import policy_artifact
from app.validators.cedar.schema import CEDAR_SCHEMA_VERSION

logger = logging.getLogger(__name__)

# Process-local LRU for compiled Cedar text. Key = (schema_version, content_hash,
# generator_version); the text is immutable for a given key, so no TTL is needed —
# a change to any component yields a new key and a fresh S3 read.
_COMPILED_CACHE_MAX = 512
_compiled_cache: "OrderedDict[tuple, str]" = OrderedDict()

# WS-I I5.2 (LLD 28 §5.6, §8): lazily-shared metrics publisher + a background-task
# set so the CedarEvalLatencyMs emit is fire-and-forget and OFF the eval path. A
# metric failure (or no event loop) must NEVER disturb a verdict — every touch here
# is guarded. The cache hit/miss split proves §8: ~1–5 ms on an LRU hit; a spike of
# cache_hit=false flags a cold/thrashing cache.
_metrics_publisher = None  # type: ignore[var-annotated]
_eval_metric_tasks: "set" = set()


def _emit_eval_latency(latency_ms: float, cache_hit: bool) -> None:
    global _metrics_publisher
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return  # no event loop (e.g. a sync unit test) — skip silently
    try:
        if _metrics_publisher is None:
            from app.utils.metrics_publisher import MetricsPublisher
            _metrics_publisher = MetricsPublisher()
        from app.utils import tenancy
        task = loop.create_task(_metrics_publisher.publish_cedar_eval_latency(
            latency_ms=latency_ms, cache_hit=cache_hit, tenant_id=tenancy.current_tenant()))
        _eval_metric_tasks.add(task)
        task.add_done_callback(_eval_metric_tasks.discard)
    except Exception:  # noqa: BLE001 — telemetry must never block eval
        logger.debug("CedarEvalLatencyMs emit skipped", exc_info=True)


def clear_compiled_cache() -> None:
    """Drop the compiled-Cedar cache (tests / hot config reload)."""
    _compiled_cache.clear()


class PolicyNotMigratedError(Exception):
    """The resolved policy has no Cedar co-artifact (`policy_format != cedar`).

    Expected pre-cutover: in shadow mode CedarPolicyEngine ABSTAINS on this
    (the agent simply isn't migrated yet) rather than fabricating a disagreement."""


@dataclass(frozen=True)
class LoadedCedarPolicy:
    policy: dict       # structured source of truth (CT06c) — for entity synthesis
    metadata: dict     # DynamoDB metadata row (binding, s3 refs, cache-key inputs)
    agent: dict        # agent record (verified identity + cloud, §2.3)
    compiled_cedar: str  # compiled `.cedar` policy text for the evaluator


class CedarPolicyLoader:
    """Loads everything CedarPolicyEngine needs for one agent."""

    def __init__(self, policy_engine, s3_client=None):
        # policy_engine: an app.validators.policy_engine.PolicyEngine. Injected so
        # the Cedar engine and the legacy engine share binding-resolution logic.
        self._engine = policy_engine
        self._s3 = s3_client if s3_client is not None else policy_engine.s3_client

    async def load(self, agent_id: str) -> LoadedCedarPolicy:
        """Resolve + load. Raises PolicyDisabledError / PolicyNotFoundError (from
        the shared resolver) and PolicyNotMigratedError (no `.cedar` yet)."""
        policy, metadata, agent = await self._engine.resolve_policy_bundle(agent_id)

        if not policy_artifact.is_cedar_format(metadata):
            raise PolicyNotMigratedError(
                f"Policy for agent {agent_id} is not in Cedar format "
                f"(policy_format={metadata.get(policy_artifact.POLICY_FORMAT_FIELD)!r})"
            )

        t0 = time.perf_counter()
        compiled, cache_hit = self._load_compiled_cached(metadata)
        _emit_eval_latency((time.perf_counter() - t0) * 1000.0, cache_hit)
        return LoadedCedarPolicy(policy=policy, metadata=metadata, agent=agent, compiled_cedar=compiled)

    def _cache_key(self, metadata: dict) -> tuple:
        return (
            metadata.get("schema_version", CEDAR_SCHEMA_VERSION),
            metadata.get("content_hash"),
            metadata.get("generator_version"),
        )

    def _load_compiled_cached(self, metadata: dict) -> tuple[str, bool]:
        """Return (compiled_text, cache_hit). cache_hit=True means the immutable
        LRU served it (no S3 round-trip) — the §8 fast path."""
        key = self._cache_key(metadata)
        cached = _compiled_cache.get(key)
        if cached is not None:
            _compiled_cache.move_to_end(key)  # LRU touch
            return cached, True

        text = policy_artifact.load_compiled_policies(
            self._s3, metadata["s3_bucket"], metadata["s3_key"]
        )
        _compiled_cache[key] = text
        _compiled_cache.move_to_end(key)
        while len(_compiled_cache) > _COMPILED_CACHE_MAX:
            _compiled_cache.popitem(last=False)
        return text, False
