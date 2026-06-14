"""Process-wide boto3 client/resource registry (WS24 M2.3).

boto3 clients are thread-safe and hold connection pools, so they should be
created **once and reused** — never per request. The singleton `ValidationService`
already builds its validators once; this registry centralizes the underlying
clients so every component shares the same pooled connections, and leaves a single
seam to later hand back **per-tenant** (assume-role) clients for cross-account
isolation without touching any call site.

Usage:
    from app.utils.clients import get_clients
    table = get_clients().dynamodb_resource().Table(...)
    get_clients().s3().get_object(...)
"""
import threading
from typing import Any, Callable, Dict

import boto3

from app.config import settings


class ClientRegistry:
    """Lazily-built, thread-safe, reused boto3 clients/resources.

    Keyed today by service name (tenant-agnostic). The `tenant` parameter is
    accepted and threaded through so a future cross-account implementation can
    return per-tenant assume-role clients without changing callers.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: Dict[str, Any] = {}

    def _get(self, key: str, factory: Callable[[], Any]) -> Any:
        client = self._cache.get(key)
        if client is None:
            with self._lock:
                client = self._cache.get(key)
                if client is None:
                    client = factory()
                    self._cache[key] = client
        return client

    def dynamodb_resource(self, tenant: str = "default") -> Any:
        return self._get(
            f"dynamodb_resource:{tenant}",
            lambda: boto3.resource("dynamodb", region_name=settings.aws_region),
        )

    def s3(self, tenant: str = "default") -> Any:
        return self._get(
            f"s3:{tenant}",
            lambda: boto3.client("s3", region_name=settings.aws_region),
        )

    def cloudwatch(self, tenant: str = "default") -> Any:
        return self._get(
            f"cloudwatch:{tenant}",
            lambda: boto3.client("cloudwatch", region_name=settings.aws_region),
        )

    def logs(self, tenant: str = "default") -> Any:
        return self._get(
            f"logs:{tenant}",
            lambda: boto3.client("logs", region_name=settings.aws_region),
        )


_registry: ClientRegistry = None  # type: ignore[assignment]
_registry_lock = threading.Lock()


def get_clients() -> ClientRegistry:
    """Return the process-wide client registry (singleton)."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = ClientRegistry()
    return _registry
