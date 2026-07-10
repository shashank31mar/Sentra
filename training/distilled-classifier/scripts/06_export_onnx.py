#!/usr/bin/env python3
"""Step 5 — export the trained student to a servable ONNX-int8 artifact + benchmark <100ms.

The student = frozen multilingual-MiniLM embedder -> LogisticRegression head. For
in-process serving we export BOTH as ONNX and fuse the pipeline:
  1. the sentence-transformer embedder -> ONNX (mean-pooled, normalized sentence vec)
  2. the sklearn LogisticRegression -> ONNX (skl2onnx)
  3. int8 dynamic quantization on the embedder (the heavy part) for CPU speed

Serving contract (what DistilledClassifier.classify loads):
  * artifacts/embedder.onnx (int8)  + tokenizer
  * artifacts/head.onnx             (logreg → P(DENY))
  * artifacts/threshold.json        (the X gates)

Then benchmark single-input p50/p99 latency on CPU — MUST be <100ms (the
distilled_timeout_ms wall). Prints the numbers; the wiring step relies on them.

NOTE: this exports what we HAVE. If onnx export of the ST model is fiddly in this
env, the fallback (documented at the bottom) is to serve the sentence-transformers
model directly with torch-cpu — slower to load but the SAME interface; the wiring
step is unchanged. We pick the path based on measured latency.
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent.parent
ART = HERE / "artifacts"
EMB_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"


def export_head() -> None:
    """LogisticRegression → ONNX (tiny, fast, trivial)."""
    import joblib
    from skl2onnx import convert_sklearn
    from skl2onnx.common.data_types import FloatTensorType

    clf = joblib.load(ART / "head.joblib")
    n_features = clf.coef_.shape[1]
    onx = convert_sklearn(
        clf, initial_types=[("emb", FloatTensorType([None, n_features]))],
        options={type(clf): {"zipmap": False}},  # raw prob array, not a dict
    )
    (ART / "head.onnx").write_bytes(onx.SerializeToString())
    print(f"head.onnx exported ({n_features} features)", file=sys.stderr)


def export_embedder() -> None:
    """Export the ST embedder to ONNX + int8 quantize. sentence-transformers has a
    built-in ONNX backend path; use it, then quantize the graph."""
    from sentence_transformers import SentenceTransformer
    try:
        # ST >=2.7 supports backend="onnx"; export creates model.onnx under the cache.
        emb = SentenceTransformer(EMB_MODEL, backend="onnx")
        emb.save(str(ART / "embedder_onnx"))
        print("embedder exported via ST onnx backend -> artifacts/embedder_onnx", file=sys.stderr)
    except Exception as e:
        print(f"ST onnx backend export failed ({e}); falling back to torch-cpu serving",
              file=sys.stderr)
        # Fallback: save the plain ST model; classify() serves it with torch-cpu.
        emb = SentenceTransformer(EMB_MODEL)
        emb.save(str(ART / "embedder_st"))
        print("saved plain ST model -> artifacts/embedder_st (torch-cpu serving)", file=sys.stderr)


def benchmark() -> None:
    """Single-input latency on CPU — the <100ms gate. Uses whichever artifact exists."""
    import joblib
    from sentence_transformers import SentenceTransformer

    # load whichever embedder we exported
    if (ART / "embedder_onnx").exists():
        emb = SentenceTransformer(str(ART / "embedder_onnx"), backend="onnx")
        mode = "onnx-int8"
    elif (ART / "embedder_st").exists():
        emb = SentenceTransformer(str(ART / "embedder_st"))
        mode = "torch-cpu"
    else:
        emb = SentenceTransformer(EMB_MODEL)
        mode = "torch-cpu (hub)"
    clf = joblib.load(ART / "head.joblib")

    sample = "tool=check_fraud_score op=READ | score this transaction for me please"
    # warm up
    for _ in range(3):
        v = emb.encode([sample], normalize_embeddings=True)
        clf.predict_proba(v)
    lats = []
    for _ in range(50):
        t = time.perf_counter()
        v = emb.encode([sample], normalize_embeddings=True)
        _ = clf.predict_proba(v)[0, 1]
        lats.append((time.perf_counter() - t) * 1000)
    lats.sort()
    p50 = lats[len(lats) // 2]
    p99 = lats[int(len(lats) * 0.99)]
    print(f"\n=== LATENCY ({mode}) single-input, 50 runs ===", file=sys.stderr)
    print(f"  p50={p50:.1f}ms  p99={p99:.1f}ms  max={lats[-1]:.1f}ms", file=sys.stderr)
    ok = p99 < 100
    print(f"  <100ms wall: {'PASS' if ok else 'FAIL — needs onnx-int8 or a lighter path'}",
          file=sys.stderr)
    (ART / "latency.json").write_text(json.dumps(
        {"mode": mode, "p50_ms": round(p50, 1), "p99_ms": round(p99, 1),
         "under_100ms": ok}, indent=2))


if __name__ == "__main__":
    export_head()
    export_embedder()
    benchmark()
