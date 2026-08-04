"""ASB seam fingerprint verification (LLD 41 §6.3, WS-F milestone F1)."""

import hashlib
import inspect
import sys
from pathlib import Path

# Pinned SHA256 of ReactAgentAttack.call_tools source text in ASB checkout at SHA 1f561dccf92d55302368fa67679b4ba9d9c8fdc4
EXPECTED_SEAM_SHA256 = "78444230e9e2e93f0b5cb2060f3478832697e1f32205c632b00fffe342bd371b"

ASB_REPO_PATH = Path("/Users/ruchikkachaudhary/closed-source/ASB")


class SeamDrift(Exception):
    """Raised when ASB ReactAgentAttack.call_tools source text has drifted from pinned SHA256."""


def verify_seam(repo_path: Path = ASB_REPO_PATH) -> str:
    """Verify ReactAgentAttack.call_tools source text equals EXPECTED_SEAM_SHA256.
    
    Returns the sha256 digest on match, or raises SeamDrift at startup.
    """
    path_str = str(repo_path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)

    try:
        from pyopenagi.agents.react_agent_attack import ReactAgentAttack
    except ImportError as exc:
        raise SeamDrift(f"Could not import pyopenagi.agents.react_agent_attack from {repo_path}: {exc}") from exc

    src = inspect.getsource(ReactAgentAttack.call_tools)
    digest = hashlib.sha256(src.encode("utf-8")).hexdigest()

    if digest != EXPECTED_SEAM_SHA256:
        raise SeamDrift(
            f"ASB call_tools source text changed: computed {digest} != expected {EXPECTED_SEAM_SHA256}. "
            "Re-verify call_tools semantics before updating EXPECTED_SEAM_SHA256."
        )

    return digest
