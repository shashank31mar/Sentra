"""Tests for the distilled model SERVER (app/distilled/server.py) — the sidecar.

Covers the contract the controller client depends on: the feature-text format
matches training, and the /classify response shape maps confidence to P(decision).
Uses a fake embedder+head so no torch/model download is needed in CI.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.distilled.server import _Model, _feature_text

# The server runs in the SIDECAR image (which has numpy/torch/sklearn), NOT the
# stdlib-lean controller venv. The classify() indexing tests need numpy; skip them
# where numpy is absent (the controller venv) — the pure-logic feature-text +
# health/contract tests still run everywhere.
np = pytest.importorskip("numpy", reason="numpy only present in the sidecar image")


def test_feature_text_matches_training_format():
    """The served feature text MUST equal the training normalizer
    (02_build_corpus._norm): 'tool={t} op={OP} | {ui}', whitespace-collapsed, op
    upper-cased. A drift here silently degrades accuracy."""
    assert _feature_text("check_fraud_score", "read", "score  this   txn") == \
        "tool=check_fraud_score op=READ | score this txn"
    assert _feature_text("", "", "") == "tool= op= | "


def _model_with(p_deny: float) -> _Model:
    m = _Model()
    m.embedder = MagicMock()
    m.embedder.encode.return_value = np.array([[0.0]])  # shape irrelevant; head is mocked
    head = MagicMock()
    head.predict_proba.return_value = np.array([[1 - p_deny, p_deny]])
    m.head = head
    return m


def test_classify_deny_returns_p_deny():
    """P(DENY) >= 0.5 → decision DENY, confidence = P(DENY)."""
    out = _model_with(0.97).classify("t", "READ", "attack text")
    assert out["decision"] == "DENY"
    assert out["confidence"] == 0.97


def test_classify_allow_returns_p_allow():
    """P(DENY) < 0.5 → decision ALLOW, confidence = P(ALLOW) = 1 - P(DENY)."""
    out = _model_with(0.03).classify("t", "READ", "benign text")
    assert out["decision"] == "ALLOW"
    assert out["confidence"] == 0.97   # 1 - 0.03


def test_health_reports_model_loaded():
    from fastapi.testclient import TestClient
    from app.distilled.server import create_served_app
    import os
    # don't eager-load a real model in the test
    os.environ["DISTILLED_MODEL_EAGER_LOAD"] = "0"
    app = create_served_app()
    with TestClient(app) as c:
        r = c.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"
        # model not loaded (eager-load off) → /classify 503 (client escalates to Haiku)
        r2 = c.post("/classify", json={"tool_name": "t", "operation_type": "READ",
                                       "user_input": "x"})
        assert r2.status_code == 503
