"""Adapter registry — name → factory, and nothing else.

LLD 41 §4.2 (D3) · FR-14.1 · WS-A milestone A1 (task A2).

A dict populated by adapter packages registering themselves at import. This is
the *only* dispatch mechanism in the harness, and its whole purpose is that
``if name == "<some benchmark>": …`` never appears under ``benchmarks/core/`` or
``benchmarks/rigs/``. ``benchmarks/tests/test_extensibility.py`` enforces that as
a code scan; G4's real proof is the zero-diff ``git diff`` over those two
directories when the second adapter lands.

The registry stores **factories, not instances**, so an adapter costs nothing
until it is asked for — importing an adapter package must not construct a
benchmark checkout or reach the network just to make the name selectable.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Tuple

from .adapter import BenchmarkAdapter

#: A zero-or-more-argument callable returning a ready adapter. Keyword arguments
#: passed to :func:`get_adapter` are forwarded verbatim.
AdapterFactory = Callable[..., BenchmarkAdapter]

_REGISTRY: Dict[str, AdapterFactory] = {}


class RegistryError(Exception):
    """Base for registry faults. Not a ``KeyError``: ``KeyError.__str__`` reprs
    its argument, which would mangle the "here is what *was* available" message
    that makes an unknown-name failure actionable."""


class DuplicateAdapter(RegistryError):
    """Two adapters claim one name.

    Silently overwriting would make ``benchmark.adapter`` in the manifest a lie —
    the run would be attributed to whichever package imported last.
    """

    def __init__(self, name: str) -> None:
        super().__init__(
            f"adapter {name!r} is already registered — a name is the manifest's "
            "benchmark.adapter field, so two claimants would make that field "
            "depend on import order"
        )
        self.name = name


class UnknownAdapter(RegistryError):
    """No adapter is registered under this name.

    Lists what *is* registered: a run that dies on a typo should say what was
    available rather than making the operator grep for it.
    """

    def __init__(self, name: str, available: Tuple[str, ...]) -> None:
        listed = ", ".join(available) if available else "(none registered)"
        super().__init__(f"unknown adapter {name!r}; registered adapters: {listed}")
        self.name = name
        self.available = available


def register(name: str, factory: AdapterFactory) -> None:
    """Register ``factory`` under ``name``. Called by an adapter package at import.

    Raises:
        ValueError: the name is empty or not lowercase. ``--adapter`` is matched
            exactly, so a capitalized key is a name nobody can select.
        DuplicateAdapter: the name is already taken.
    """
    if not name or name != name.lower() or name.strip() != name:
        raise ValueError(
            f"adapter name {name!r} must be non-empty, lowercase and unpadded — "
            "it is matched exactly against --adapter and stamped into the manifest"
        )
    if name in _REGISTRY:
        raise DuplicateAdapter(name)
    _REGISTRY[name] = factory


def get_adapter(name: str, /, **kwargs: Any) -> BenchmarkAdapter:
    """Construct the adapter registered under ``name``.

    ``name`` is **positional-only**: every keyword argument belongs to the
    adapter's own factory and is forwarded verbatim, so an adapter that legitimately
    takes a ``name`` parameter is constructible rather than colliding with ours.

    Raises:
        UnknownAdapter: naming every registered adapter.
    """
    try:
        factory = _REGISTRY[name]
    except KeyError:
        raise UnknownAdapter(name, registered_names()) from None
    return factory(**kwargs)


def registered_names() -> Tuple[str, ...]:
    """Every registered name, sorted — a deterministic order for the CLI's help
    text, the error message above and the conformance suite's parametrization."""
    return tuple(sorted(_REGISTRY))
