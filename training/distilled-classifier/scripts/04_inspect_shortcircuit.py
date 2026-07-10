#!/usr/bin/env python3
"""Decisive check: at each ALLOW-confidence threshold X, WHAT attacks (if any) would
the fast-ALLOW short-circuit wrongly wave through? Print the actual texts so we can
judge: real attacks the model is confidently-wrong about (→ no safe X), or mislabels
(→ a high X is safe). Reuses the SAME group split + head from step 3."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np

HERE = Path(__file__).resolve().parent.parent
CORPUS = HERE / "data" / "corpus.jsonl"
ART = HERE / "artifacts"


def main() -> None:
    from sentence_transformers import SentenceTransformer
    from sklearn.model_selection import GroupShuffleSplit
    import joblib

    rows = [json.loads(l) for l in CORPUS.open() if l.strip()]
    texts = [r["text"] for r in rows]
    y = np.array([r["label"] for r in rows])
    groups = np.array([r["group"] for r in rows])
    srcs = [r.get("src", "") for r in rows]

    gss = GroupShuffleSplit(n_splits=1, test_size=0.25, random_state=42)
    _, te = next(gss.split(texts, y, groups))

    emb = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    Xte = emb.encode([texts[i] for i in te], normalize_embeddings=True, show_progress_bar=False)
    clf = joblib.load(ART / "head.joblib")
    p_deny = clf.predict_proba(Xte)[:, 1]
    p_allow = 1 - p_deny
    yte = y[te]
    src_te = [srcs[i] for i in te]
    txt_te = [texts[i] for i in te]

    print("=== fine ALLOW-threshold sweep (short-circuit = fast-ALLOW, skip Haiku) ===")
    print(f"{'X':>7} {'n_shortcut':>11} {'missed_atk':>11} {'benign_prec':>12}")
    for X in (0.90, 0.95, 0.99, 0.995, 0.999, 0.9995):
        m = p_allow >= X
        n = int(m.sum())
        missed = int((yte[m] == 1).sum())
        bp = float((yte[m] == 0).mean()) if n else float("nan")
        print(f"{X:>7} {n:>11} {missed:>11} {bp:>12.4f}")

    # The actual attack texts that land in the >=0.95 confident-ALLOW zone.
    print("\n=== ATTACKS the model would WRONGLY fast-ALLOW at P(allow)>=0.95 ===")
    m = (p_allow >= 0.95) & (yte == 1)
    idxs = np.where(m)[0]
    if len(idxs) == 0:
        print("  (none)")
    for i in idxs:
        print(f"  P(allow)={p_allow[i]:.4f} src={src_te[i]}")
        print(f"    {txt_te[i][:160]}")


if __name__ == "__main__":
    main()
