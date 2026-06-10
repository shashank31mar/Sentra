"""Pytest fixtures for the demo-agent offline tests.

Sets dummy Sentra config (so each agent's guard constructs), puts the SDK + agents on the path, and
wires all three agents' guard clients to ONE shared ``FakeController`` so cross-cloud sequences work
in-process (the Azure verify and the AWS refund share session history).
"""
from __future__ import annotations

import os
import pathlib
import sys

import pytest

DEMO = pathlib.Path(__file__).resolve().parents[1]

# Config the guards read at import (fail-fast otherwise). Memory backend for the store.
os.environ.setdefault("SENTRA_API_BASE", "https://example.execute-api.us-east-1.amazonaws.com/prod")
os.environ.setdefault("SENTRA_API_KEY", "test-key")
os.environ.setdefault("AEGION_DEMO_BACKEND", "memory")

for p in (DEMO, DEMO / "aws-payments-agent" / "tools",
          DEMO / "azure-identity-agent" / "tools", DEMO / "azure-telecom-agent" / "tools",
          DEMO / "traffic", DEMO / "tests"):
    sys.path.insert(0, str(p))


def _load(rel_path: str, name: str):
    """Load a module by explicit path (avoids the lambda_handler name collision)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(name, DEMO / rel_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def wired():
    """Load the three agent modules and point every guard at one FakeController."""
    from fake_controller import FakeController

    payments = _load("aws-payments-agent/tools/lambda_handler.py", "payments_handler")
    identity = _load("azure-identity-agent/tools/identity_core.py", "identity_core_mod")
    telecom = _load("azure-telecom-agent/tools/telecom_core.py", "telecom_core_mod")

    fc = FakeController()
    payments.guard._client.post = fc.post
    identity.guard._client.post = fc.post
    telecom.guard._client.post = fc.post
    return {"fc": fc, "payments": payments, "identity": identity, "telecom": telecom}
