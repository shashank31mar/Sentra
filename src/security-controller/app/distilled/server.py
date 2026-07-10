"""Distilled-classifier model server — the request-phase tier-1 front-runner (FR-3.12).

A SEPARATE model-serving FastAPI app (NOT co-located on security-controller — same
pattern as phi-ner, LLD 29 §4/§9.3). It hosts the distilled student model
(multilingual-MiniLM sentence-embedder → calibrated LogisticRegression head) trained
by distilling the live Haiku/Sonnet verdicts (training/distilled-classifier/). Runs
warm/always-on behind CloudMap `distilled-classifier.sentra.internal`; the controller's
`DistilledClassifier.classify()` calls `POST /classify` over the in-VPC network.

WHY A SIDECAR (not baked into the controller): the serving stack (torch +
sentence-transformers + the 465MB embedder) is ~1.3GB. The controller is deliberately
stdlib-lean (92MB). Isolating the model keeps the PDP light and lets the model fleet
scale independently — the phi-ner architecture, reused.

CONTRACT (what the controller client depends on — a join key):
  POST /classify  {tool_name, operation_type, user_input}
    → 200 {decision: "ALLOW"|"DENY", confidence: float(0..1), model: str}
       * confidence is P(the returned decision) — for DENY it is P(DENY), for ALLOW
         it is P(ALLOW)=1-P(DENY). The controller gates the short-circuit on it.
  GET /health → 200 {status:"ok", model_loaded: bool}

FAIL-SECURE: the controller treats any error / timeout / non-200 as "escalate to
Haiku" (never as a clean ALLOW) — the server never needs to fabricate a verdict.

COLD-START OFF THE HOT PATH: the model is loaded EAGERLY at startup (warm), never
lazy-per-request. min_capacity>=1 so a model-load is a boot cost, not a request cost.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

logger = logging.getLogger("distilled_server")


class ClassifyRequest(BaseModel):
    """POST /classify body — the fields the controller client sends. Defined at
    MODULE level (not inside the factory) so FastAPI resolves it as the JSON body,
    not a query param."""

    tool_name: str = ""
    operation_type: str = ""
    user_input: str = ""

# Feature text format — MUST match training (02_build_corpus._norm). A drift here
# silently degrades accuracy (the model sees a different string shape than it trained
# on). Kept identical: "tool={t} op={OP} | {user_input}".
def _feature_text(tool_name: str, operation_type: str, user_input: str) -> str:
    tool = (tool_name or "").strip()
    op = (operation_type or "").strip().upper()
    ui = " ".join((user_input or "").split())
    return f"tool={tool} op={op} | {ui}"


class _Model:
    """Holds the eager-loaded embedder + head. One instance, reused per request."""

    def __init__(self) -> None:
        self.embedder = None
        self.head = None
        self.model_tag = "distilled_v1_multilingual"

    def load(self) -> None:
        from sentence_transformers import SentenceTransformer
        import joblib

        model_dir = Path(os.environ.get("DISTILLED_MODEL_DIR", "/models/distilled"))
        emb_path = model_dir / "embedder_st"
        head_path = model_dir / "head.joblib"
        t = time.perf_counter()
        self.embedder = SentenceTransformer(str(emb_path))
        self.head = joblib.load(head_path)
        logger.info("distilled model loaded in %.1fs (dir=%s)",
                    time.perf_counter() - t, model_dir)

    def classify(self, tool_name: str, operation_type: str, user_input: str) -> dict:
        text = _feature_text(tool_name, operation_type, user_input)
        vec = self.embedder.encode([text], normalize_embeddings=True)
        p_deny = float(self.head.predict_proba(vec)[0, 1])
        if p_deny >= 0.5:
            return {"decision": "DENY", "confidence": round(p_deny, 4), "model": self.model_tag}
        return {"decision": "ALLOW", "confidence": round(1.0 - p_deny, 4), "model": self.model_tag}


def create_served_app():
    """FastAPI factory (mirrors phi_ner.create_served_app). Eager-loads at startup."""
    from fastapi import FastAPI

    app = FastAPI(title="distilled-classifier", docs_url=None, redoc_url=None)
    model = _Model()

    @app.on_event("startup")
    def _startup() -> None:
        # Eager load — a model-load must never happen on a request (§4.1 cold-start).
        if os.environ.get("DISTILLED_MODEL_EAGER_LOAD", "1") == "1":
            model.load()

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "model_loaded": model.head is not None}

    @app.post("/classify")
    def classify(req: ClassifyRequest) -> dict:
        if model.head is None:
            # Not loaded yet → the controller's client treats a 503 as escalate-to-Haiku
            # (fail-secure), never as a clean verdict.
            from fastapi import HTTPException
            raise HTTPException(status_code=503, detail="model not loaded")
        return model.classify(req.tool_name, req.operation_type, req.user_input)

    return app
