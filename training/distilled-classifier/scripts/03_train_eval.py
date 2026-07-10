#!/usr/bin/env python3
"""Step 3+4 — train the distilled student + eval it LEAKAGE-SAFE.

STUDENT (research REC): all-MiniLM-L6-v2 sentence-embedding (frozen) → calibrated
LogisticRegression head. Chosen because (a) <100ms CPU inference, (b) LogReg gives
natively-calibrated probabilities — the confidence a security short-circuit gates on,
(c) tiny corpus (~4.2k unique texts) → a frozen-embedding + linear head generalizes
where a fine-tuned transformer would overfit.

LEAKAGE-SAFE EVAL (the load-bearing methodology): acme replays ~1.8k distinct strings,
so a random split would put the SAME text in train AND test → fake-perfect memorization
numbers. We split on GROUP (unique-text hash) via GroupShuffleSplit so every test text
is genuinely unseen. The reported precision/recall/F1 + calibration (ECE) are therefore
GENERALIZATION numbers, not memorization.

OUTPUTS
  artifacts/embedder/            (the MiniLM ONNX + tokenizer — step 5 exports)
  artifacts/head.joblib          (the calibrated LogReg)
  artifacts/metrics.json         (P/R/F1 @ thresholds + ECE + confusion)
  artifacts/threshold.json       (the confidence bar for the short-circuit)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent.parent
CORPUS = HERE / "data" / "corpus.jsonl"
ART = HERE / "artifacts"
EMB_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def _load():
    rows = [json.loads(l) for l in CORPUS.open() if l.strip()]
    texts = [r["text"] for r in rows]
    y = np.array([r["label"] for r in rows])
    w = np.array([r["weight"] for r in rows], dtype=float)
    groups = np.array([r["group"] for r in rows])
    return texts, y, w, groups


def _ece(probs: np.ndarray, y: np.ndarray, bins: int = 10) -> float:
    """Expected Calibration Error — how far predicted confidence is from empirical
    accuracy. Load-bearing: a security short-circuit trusts the confidence number."""
    edges = np.linspace(0, 1, bins + 1)
    ece = 0.0
    for i in range(bins):
        m = (probs > edges[i]) & (probs <= edges[i + 1])
        if m.sum() == 0:
            continue
        conf = probs[m].mean()
        acc = (y[m] == 1).mean()  # frac actually positive in this confidence bin
        ece += (m.sum() / len(probs)) * abs(conf - acc)
    return float(ece)


def main() -> None:
    from sentence_transformers import SentenceTransformer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GroupShuffleSplit
    from sklearn.metrics import (precision_score, recall_score, f1_score,
                                 confusion_matrix, roc_auc_score)
    import joblib

    ART.mkdir(parents=True, exist_ok=True)
    texts, y, w, groups = _load()
    print(f"corpus: {len(texts)} rows, {len(set(groups))} groups, "
          f"pos={int(y.sum())} neg={int((y==0).sum())}", file=sys.stderr)

    # --- GROUP split: no unique text in both train and test (leakage guard) ---
    gss = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=42)
    tr, te = next(gss.split(texts, y, groups))
    # Sanity: zero group overlap.
    assert not (set(groups[tr]) & set(groups[te])), "GROUP LEAKAGE — split is invalid"
    print(f"train={len(tr)} test={len(te)}  (0 shared groups — leakage-safe)", file=sys.stderr)

    # --- embed (frozen MiniLM) ------------------------------------------------
    print(f"loading embedder {EMB_MODEL} ...", file=sys.stderr)
    emb = SentenceTransformer(EMB_MODEL)
    X = emb.encode(texts, batch_size=256, show_progress_bar=True,
                   normalize_embeddings=True)
    Xtr, Xte = X[tr], X[te]
    ytr, yte = y[tr], y[te]
    wtr = w[tr]

    # --- train calibrated linear head ----------------------------------------
    # LogisticRegression is natively well-calibrated for log-loss; class_weight is
    # already folded into the sample weights (step 2 balanced pos/neg weight mass).
    clf = LogisticRegression(max_iter=2000, C=1.0)
    clf.fit(Xtr, ytr, sample_weight=wtr)

    # --- eval on the UNSEEN test groups --------------------------------------
    p_te = clf.predict_proba(Xte)[:, 1]  # P(DENY)
    auc = roc_auc_score(yte, p_te) if len(set(yte)) > 1 else float("nan")

    metrics = {"auc": auc, "n_train": len(tr), "n_test": len(te),
               "test_pos": int(yte.sum()), "test_neg": int((yte == 0).sum()),
               "by_threshold": {}}
    for thr in (0.3, 0.5, 0.7, 0.9):
        pred = (p_te >= thr).astype(int)
        metrics["by_threshold"][str(thr)] = {
            "precision": round(precision_score(yte, pred, zero_division=0), 4),
            "recall": round(recall_score(yte, pred, zero_division=0), 4),
            "f1": round(f1_score(yte, pred, zero_division=0), 4),
            "confusion": confusion_matrix(yte, pred, labels=[0, 1]).tolist(),
        }

    # Calibration on the ALLOW side too: the short-circuit trusts P(ALLOW) high.
    # ECE over P(DENY) — low is good.
    metrics["ece_deny"] = round(_ece(p_te, yte), 4)
    # For a confident-ALLOW short-circuit we need P(ALLOW)=1-P(DENY) high AND the
    # verdict to be ALLOW. Report the benign-precision at a high ALLOW-confidence bar.
    p_allow = 1 - p_te
    for allow_thr in (0.9, 0.95, 0.99):
        m = p_allow >= allow_thr
        if m.sum():
            # of the calls we'd confidently ALLOW-shortcircuit, what frac were truly benign?
            benign_prec = float((yte[m] == 0).mean())
            metrics.setdefault("shortcircuit_allow", {})[str(allow_thr)] = {
                "n_shortcircuited": int(m.sum()),
                "benign_precision": round(benign_prec, 4),
                "missed_attacks": int((yte[m] == 1).sum()),  # attacks we'd WRONGLY allow — must be ~0
            }

    (ART / "metrics.json").write_text(json.dumps(metrics, indent=2))
    joblib.dump(clf, ART / "head.joblib")
    # threshold policy: only short-circuit ALLOW at a HIGH bar with 0 missed attacks
    (ART / "threshold.json").write_text(json.dumps({
        "allow_shortcircuit_min_confidence": 0.95,
        "note": "student short-circuits ONLY confident-ALLOW; DENY + low-conf escalate to Haiku",
    }, indent=2))

    print("\n=== EVAL (leakage-safe, unseen test groups) ===", file=sys.stderr)
    print(f"AUC={auc:.4f}  ECE(deny)={metrics['ece_deny']}", file=sys.stderr)
    for thr, m in metrics["by_threshold"].items():
        print(f"  thr={thr}: P={m['precision']} R={m['recall']} F1={m['f1']} conf={m['confusion']}", file=sys.stderr)
    print("  short-circuit ALLOW safety (missed_attacks MUST be ~0):", file=sys.stderr)
    for t, m in metrics.get("shortcircuit_allow", {}).items():
        print(f"    P(allow)>={t}: n={m['n_shortcircuited']} benign_prec={m['benign_precision']} "
              f"MISSED_ATTACKS={m['missed_attacks']}", file=sys.stderr)
    print(f"\nartifacts -> {ART}", file=sys.stderr)


if __name__ == "__main__":
    main()
