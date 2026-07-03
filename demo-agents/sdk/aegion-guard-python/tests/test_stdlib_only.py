"""Guard: the SDK runtime stays stdlib-only (WS-E1 shared convention #1).

The Tier-1 redactor must import ONLY the standard library (LLD 23 §2 — the SDK
vendors unchanged into a Lambda zip / Azure Function). A runtime dependency added
to pyproject.toml would break that. This test is the arbiter: it MUST FAIL if a
runtime dep is added or the redactor grows a third-party import.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

# tomllib is 3.11+; the SDK targets 3.9+, so parse the tiny dependencies line
# without a toml dep (which would itself violate stdlib-only). Prefer tomllib.
_ROOT = Path(__file__).resolve().parents[1]
_PYPROJECT = _ROOT / "pyproject.toml"
_REDACTION = _ROOT / "src" / "aegion_guard" / "redaction.py"

# The stdlib modules the redactor is allowed to use (shared convention #1) plus
# intra-package relative imports. Every name here is a Python standard-library
# module (verified below against ``sys.stdlib_module_names`` on 3.10+), so the
# no-runtime-dependency invariant (``dependencies == []``) still holds. ``ipaddress``
# (stdlib since 3.3) is the authoritative RFC-4291 IPv6 validator behind the ``IP``
# matcher's IPv6 arm (FIX-B) — the redactor need not re-encode the grammar.
_ALLOWED_STDLIB = {
    "re", "math", "unicodedata", "secrets", "ipaddress",
    "__future__", "dataclasses", "typing",
}


def test_allowlist_is_genuinely_stdlib():
    # Guard the guard: every name we allow must ACTUALLY be a stdlib module, so the
    # allowlist can never quietly bless a third-party import (which would break the
    # vendor-into-a-Lambda-zip invariant). ``sys.stdlib_module_names`` is the
    # authoritative set (3.10+); ``__future__`` is a stdlib pseudo-module.
    names = getattr(sys, "stdlib_module_names", None)
    if names is None:
        import pytest

        pytest.skip("sys.stdlib_module_names requires Python 3.10+")
    for mod in _ALLOWED_STDLIB:
        assert mod in names or mod == "__future__", f"{mod!r} is not stdlib"


def _runtime_dependencies() -> list:
    text = _PYPROJECT.read_text(encoding="utf-8")
    if sys.version_info >= (3, 11):
        import tomllib

        data = tomllib.loads(text)
        return data["project"]["dependencies"]
    # 3.9/3.10 fallback: find the `dependencies = [...]` under [project].
    # The file keeps it on a single line (`dependencies = []`).
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("dependencies") and "=" in stripped:
            rhs = stripped.split("=", 1)[1].strip()
            return ast.literal_eval(rhs)
    raise AssertionError("no `dependencies` key found in [project]")


def test_runtime_dependencies_stay_empty():
    # Non-negotiable: runtime deps == [] (test-only deps live in the dev extra).
    assert _runtime_dependencies() == [], (
        "SDK runtime must stay stdlib-only (LLD 23 §2); do not add runtime deps"
    )


def test_redactor_imports_only_stdlib():
    tree = ast.parse(_REDACTION.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                assert top in _ALLOWED_STDLIB, f"non-stdlib import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # intra-package relative import (e.g. from .exceptions)
            top = (node.module or "").split(".")[0]
            assert top in _ALLOWED_STDLIB, f"non-stdlib import: {node.module}"


# ================================================================ WS-A A1.2
# The ship-now local-floor SEAM must add NO runtime dep and NO `[local-floor]`
# extra (crypto/caching is lld/37) — the seam is enum + a config bool only.

_LOCAL_FLOOR = _ROOT / "src" / "aegion_guard" / "local_floor.py"

# Stdlib names the seam module + the seam edits are allowed to use. `enum` (the
# LocalFloorVerdict base) is stdlib; the rest are the general SDK-module allowlist.
_SEAM_ALLOWED_STDLIB = _ALLOWED_STDLIB | {"enum"}


def _optional_dependencies() -> dict:
    text = _PYPROJECT.read_text(encoding="utf-8")
    if sys.version_info >= (3, 11):
        import tomllib

        return tomllib.loads(text).get("project", {}).get("optional-dependencies", {})
    # 3.9/3.10 fallback: collect the top-level keys under
    # [project.optional-dependencies] (we only need the KEY set for A1.2).
    keys: dict = {}
    in_section = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_section = stripped == "[project.optional-dependencies]"
            continue
        if in_section and "=" in stripped and not stripped.startswith(("#", '"', "]")):
            key = stripped.split("=", 1)[0].strip()
            if key:
                keys[key] = None
    return keys


def test_stdlib_only_holds():
    """A1.2 guard: the seam introduces (a) no non-stdlib runtime import in
    local_floor.py, (b) dependencies == [], (c) NO `local-floor` optional extra.

    Non-vacuous: adding a crypto/interpreter dep to local_floor.py, a runtime dep,
    or a `[local-floor]` extra (all lld/37 scope creep) fails this test."""
    # (a) local_floor.py imports only stdlib (enum) / intra-package relatives.
    tree = ast.parse(_LOCAL_FLOOR.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                assert top in _SEAM_ALLOWED_STDLIB, f"non-stdlib import: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                continue  # intra-package relative import
            top = (node.module or "").split(".")[0]
            assert top in _SEAM_ALLOWED_STDLIB, f"non-stdlib import: {node.module}"

    # (b) runtime deps stay empty (re-pinned here so A1.2 is self-contained).
    assert _runtime_dependencies() == []

    # (c) the ONLY optional extras are the pre-existing ones; NO `local-floor`.
    extras = set(_optional_dependencies())
    assert "local-floor" not in extras, (
        "no `[local-floor]` extra in lld/36 — crypto/caching is lld/37 scope creep"
    )
    assert "identity" in extras, "the identity extra must remain the opt-in ES256 signer"
