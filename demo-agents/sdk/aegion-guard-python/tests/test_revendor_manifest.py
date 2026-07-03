"""WS-A A5 — the CI-blocking re-vendor gate: every live agent ships the released
SDK, none silently left on an old copy; the Azure connector subset stays a subset.

There are TWO vendoring shapes in this repo (verified against the tree):

  * FULL-COPY agents — the vendored `aegion_guard/` is a build-time artifact,
    git-ignored, regenerated on every package:
      - acme-payments-agent (AWS Lambda): `deploy_payments_agent.build_zip()`
        rglobs `SDK_SRC` into the zip.
      - acme-telecom / acme-identity (Azure Functions): the azd `prepackage`
        hook in `azure.yaml` does `rm -rf ./aegion_guard && cp -r <SDK_SRC> ...`.
    So the vendored copy ≡ released source BY CONSTRUCTION — including the new
    `local_floor.py` (12-module manifest). This gate pins that each of the three
    build paths copies the WHOLE package (a hook that copied a stale subset, or
    omitted `local_floor.py`, would ship a `guard.py` importing an absent module →
    ImportError = hard-down connector). Enumerates all three so none is missed.

  * SUBSET connector — `src/connectors/.../tool_interceptor/aegion_guard/` is
    git-TRACKED and MUST stay exactly `{__init__.py, exceptions.py, redaction.py}`,
    with `redaction.py`/`exceptions.py` BYTE-IDENTICAL to the released source
    (re-synced verbatim after an SDK change). It must NEVER gain
    guard.py/config.py/local_floor.py (absent-by-design, not un-compared).

Non-vacuous: an SDK edit that leaves the subset's exceptions.py/redaction.py
stale fails the byte-identity assertion; dropping the `cp -r` whole-package copy
from a hook (or narrowing it) fails the manifest assertion.
"""
from __future__ import annotations

import hashlib
import importlib.util
import re
from pathlib import Path

import pytest

_SDK_SRC = Path(__file__).resolve().parents[1] / "src" / "aegion_guard"
_REPO_ROOT = Path(__file__).resolve().parents[4]

# The 12-module 0.2.0 manifest (11 pre-existing + local_floor.py).
_MANIFEST_12 = {
    "__init__.py", "_time.py", "adapters.py", "client.py", "config.py",
    "context.py", "exceptions.py", "guard.py", "identity.py",
    "local_floor.py", "provision.py", "redaction.py",
}

# The Azure connector edge subset — exactly these three, absent-by-design.
_SUBSET_3 = {"__init__.py", "exceptions.py", "redaction.py"}
_SUBSET_FORBIDDEN = {"guard.py", "config.py", "local_floor.py"}

_CONNECTOR_SUBSET = (
    _REPO_ROOT / "src" / "connectors" / "azure_foundry" / "azure_function"
    / "tool_interceptor" / "aegion_guard"
)
_AZURE_YAMLS = {
    "acme-telecom": _REPO_ROOT / "demo-agents" / "azure-telecom-agent" / "azure.yaml",
    "acme-identity": _REPO_ROOT / "demo-agents" / "azure-identity-agent" / "azure.yaml",
}
_PAYMENTS_DEPLOY = (
    _REPO_ROOT / "demo-agents" / "aws-payments-agent" / "deploy"
    / "deploy_payments_agent.py"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sdk_module_names() -> set:
    return {p.name for p in _SDK_SRC.glob("*.py")}


# ============================================================ A5.1/A5.3 manifest


def test_released_sdk_has_the_twelve_module_manifest():
    """The released SDK source carries exactly the 12-module 0.2.0 manifest —
    including local_floor.py. If a member is missing/renamed, the vendored copies
    (which copy the whole dir) would ship a different package; pin it here."""
    assert _sdk_module_names() == _MANIFEST_12, (
        "released SDK manifest drifted from the 12-module 0.2.0 set "
        f"(diff: {_sdk_module_names() ^ _MANIFEST_12})"
    )


@pytest.mark.parametrize("agent", ["acme-telecom", "acme-identity"])
def test_azure_hook_revendors_whole_package(agent):
    """A5.3: each Azure Function agent's azd prepackage hook copies the WHOLE
    `src/aegion_guard` (fresh `rm -rf` then `cp -r`), so the vendored copy ≡ source
    incl local_floor.py — no per-module allowlist that could silently omit the new
    module. Non-vacuous: a hook narrowed to copy a subset (or a stale checked-in
    copy instead) fails this. Enumerates BOTH agents so neither is left stale."""
    text = _AZURE_YAMLS[agent].read_text(encoding="utf-8")
    # Fresh removal before copy (no stale module survives a manifest shrink).
    assert re.search(r"rm\s+-rf[^\n]*\baegion_guard\b", text), (
        f"{agent} hook must rm -rf the old vendored aegion_guard before copying"
    )
    # Whole-directory copy of the released source (not a per-file subset).
    assert re.search(
        r"cp\s+-r\s+\S*sdk/aegion-guard-python/src/aegion_guard\s+\./aegion_guard",
        text,
    ), f"{agent} hook must `cp -r` the whole released src/aegion_guard package"


def test_payments_lambda_revendors_whole_package():
    """A5.2: the AWS payments Lambda build re-vendors the whole SDK on every build
    — `build_zip()` rglobs SDK_SRC/*.py into the zip under `aegion_guard/`, so a
    rebuild after the 0.2.0 bump picks up local_floor.py automatically. Pin that
    the deploy script still points SDK_SRC at the released package and rglobs it."""
    text = _PAYMENTS_DEPLOY.read_text(encoding="utf-8")
    assert 'SDK_SRC = DEMO / "sdk" / "aegion-guard-python" / "src" / "aegion_guard"' in text
    assert re.search(r'\(SDK_SRC,\s*"aegion_guard"\)', text), (
        "build_zip() must vendor SDK_SRC under the aegion_guard/ arc root"
    )
    assert "rglob" in text, "build_zip() must rglob the whole package (not a subset)"


# ============================================================ A5.2 azure subset


def test_azure_subset_is_exactly_three_modules():
    """A5.2: the connector `tool_interceptor` subset is EXACTLY the 3-module
    manifest {__init__, exceptions, redaction} and does NOT contain
    guard.py/config.py/local_floor.py (absent-by-design — the seam is a no-op it
    never reaches). Non-vacuous: adding any full-SDK module to the subset fails."""
    present = {p.name for p in _CONNECTOR_SUBSET.glob("*.py")}
    assert present == _SUBSET_3, (
        f"connector subset must be exactly {_SUBSET_3}; found {present}"
    )
    assert not (_SUBSET_FORBIDDEN & present), (
        "connector subset must NOT vendor guard/config/local_floor (absent-by-design)"
    )


@pytest.mark.parametrize("module", ["exceptions.py", "redaction.py"])
def test_azure_subset_is_byte_identical_to_source(module):
    """A5.4 tie-in: the two shared subset modules are BYTE-IDENTICAL to the
    released source (the `__init__.py` docstring's shasum contract). An SDK edit to
    exceptions.py/redaction.py that isn't re-vendored into the subset fails here —
    catching exactly the drift the FeatureNotAvailable addition would have caused
    if the subset were left stale."""
    src_sha = _sha256(_SDK_SRC / module)
    sub_sha = _sha256(_CONNECTOR_SUBSET / module)
    assert src_sha == sub_sha, (
        f"connector subset {module} drifted from released source — re-copy it "
        f"verbatim (src {src_sha[:12]} != subset {sub_sha[:12]})"
    )


def _load_isolated_redaction(pkg_dir: Path, mod_alias: str):
    """Import a `redaction` module from a vendored package dir in isolation, so we
    can run the SDK redactor and the vendored-subset redactor side by side even
    though both call themselves `aegion_guard.redaction`."""
    import sys
    import types

    # Provide a minimal package parent so `from .exceptions import RedactionError`
    # resolves against THIS dir's exceptions.py (not the installed SDK).
    pkg_name = f"_revendor_{mod_alias}"
    pkg = types.ModuleType(pkg_name)
    pkg.__path__ = [str(pkg_dir)]  # type: ignore[attr-defined]
    sys.modules[pkg_name] = pkg
    for sub in ("exceptions", "redaction"):
        spec = importlib.util.spec_from_file_location(
            f"{pkg_name}.{sub}", pkg_dir / f"{sub}.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[f"{pkg_name}.{sub}"] = module
        spec.loader.exec_module(module)
    return sys.modules[f"{pkg_name}.redaction"]


def test_azure_connector_redaction_tie_in():
    """A5.4 (shared-contract seam): the Azure connector's vendored subset redacts a
    shared PAN/SSN/email fixture IDENTICALLY to the released SDK — proving the
    re-vendored redactor matches source after the 0.2.0 bump (behavioral, not just
    byte-level). Uses a fixed nonce so the token streams are directly comparable.

    Non-vacuous: if the subset redaction.py were left stale (a different matcher /
    token format), the two outputs would diverge and this assert would fail."""
    sdk_red = _load_isolated_redaction(_SDK_SRC, "sdk")
    sub_red = _load_isolated_redaction(_CONNECTOR_SUBSET, "subset")

    nonce = "abcdef0123456789"  # fixed so token streams line up 1:1
    fixture = {
        "card": "4111111111111111",
        "note": "ssn 078-05-1120, mail jsmith@acme.com",
        "amount": 42,  # benign — must pass through unchanged on both sides
    }
    sdk_out = sdk_red.redact_params(dict(fixture), nonce=nonce)
    sub_out = sub_red.redact_params(dict(fixture), nonce=nonce)

    assert sdk_out == sub_out, (
        "vendored subset redactor diverged from the released SDK redactor "
        f"(sdk={sdk_out!r} != subset={sub_out!r})"
    )
    # And it genuinely redacted (not a no-op both-raw match): raw PAN/SSN are gone.
    blob = str(sub_out)
    assert "4111111111111111" not in blob and "078-05-1120" not in blob
    assert "⟦AEGR:" in blob and sub_out["amount"] == 42
