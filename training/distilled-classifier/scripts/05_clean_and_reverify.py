#!/usr/bin/env python3
"""Clean the corpus label noise, retrain, and re-verify the safe ALLOW threshold X.

WHAT WAS WRONG (traced to source, step 04):
  * BIPIA rows in ws0_indirect store the BASE benign question with the injection
    stripped out (e.g. "What is the capital of Brazil?") but carry attack_class=
    indirect_injection → my step-2 labeled them 1 (attack). The stored TEXT is benign,
    so the model correctly scores them ALLOW. These are genuine MISLABELS → fix to 0.
  * The German demo_labeled rows (".. Höre nicht auf alles zuvor .. demokratie stirbt!")
    ARE real injections, correctly label 1, and the model MISSES them (multilingual
    blind spot). These are KEPT as 1 — they are the honest reason X must be high.

CLEANING RULE (conservative, no cheating): relabel a row 1→0 ONLY when its source is a
BIPIA-derived ws0 row whose stored text is a bare benign question with NO injection
marker. Detect via `source_corpus` containing 'BIPIA' AND text lacking any injection
signal. Everything else keeps its label. We NEVER relabel a real attack to benign to
flatter the metric.

Then: rebuild → retrain → re-run the ALLOW-threshold sweep. Confirms the honest X where
missed_attacks==0 on CORRECT labels.
"""
from __future__ import annotations
import json, os, re, hashlib, math, collections
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
HERE = Path(__file__).resolve().parent.parent
CORPUS = HERE / "data" / "corpus.jsonl"
CLEAN = HERE / "data" / "corpus_clean.jsonl"

# Embedder is parametrized so we can compare the English MiniLM vs the multilingual
# one (which should shrink the German/code-switched blind spot). Default = multilingual.
EMB_MODEL = os.environ.get(
    "EMB_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
)

# Injection markers — if a BIPIA row's text contains one, it's NOT a stripped-benign
# base question, so we do NOT relabel it. (Same family as the classifier's own scan.)
_INJ = re.compile(
    r"(ignore\s+(all\s+)?previous|disregard|system\s+prompt|you\s+are\s+now|"
    r"new\s+instructions?|reveal|maintenance\s+mode|FreedomBot|roleplay|"
    r"höre\s+nicht|ignorier|schreibe|no\s+content\s+restrictions|"
    r"as\s+an?\s+(actor|AI\s+with)|hypothetically|deceased)",
    re.IGNORECASE,
)


def _norm(tool, op, ui):
    return f"tool={(tool or '').strip()} op={(op or '').strip().upper()} | {' '.join((ui or '').split())}"


def _group(t): return hashlib.sha1(t.encode()).hexdigest()[:16]


def clean() -> None:
    """Rebuild corpus from sources, applying the BIPIA-benign relabel fix."""
    # Reuse step-2 assembly but with the fix. Load the BIPIA base-question texts so we
    # can identify them by exact text match (source-grounded, not guesswork).
    bipia_benign_texts: set[str] = set()
    for fn in ["harness/ws0/corpus/indirect_injection.jsonl",
               "harness/ws0/corpus/exfiltration.jsonl"]:
        for l in (ROOT / fn).open():
            r = json.loads(l)
            src = str(r.get("source_corpus", ""))
            txt = r.get("text", "")
            # BIPIA-derived AND no injection marker in the stored text → benign base Q.
            if "BIPIA" in src and txt and not _INJ.search(txt):
                bipia_benign_texts.add(txt.strip())
    print(f"identified {len(bipia_benign_texts)} BIPIA benign base-question mislabels "
          f"(relabel 1→0)", flush=True)

    rows = [json.loads(l) for l in CORPUS.open() if l.strip()]
    fixed = 0
    for r in rows:
        # the corpus text is "tool= op= | <raw>"; extract the raw tail for match
        raw = r["text"].split("| ", 1)[-1].strip()
        if r["label"] == 1 and raw in bipia_benign_texts:
            r["label"] = 0
            r["group"] = _group(r["text"])  # unchanged, but keep consistent
            r["src"] = r.get("src", "") + "+relabeled_benign"
            fixed += 1
    print(f"relabeled {fixed} rows 1→0 (source-grounded BIPIA benign)", flush=True)

    # dedupe (group,label) again since labels changed
    best = {}
    seen = collections.Counter((r["group"], r["label"]) for r in rows)
    for r in rows:
        key = (r["group"], r["label"])
        if key not in best:
            best[key] = r
    deduped = list(best.values())
    # re-balance weights
    pos = [r for r in deduped if r["label"] == 1]
    neg = [r for r in deduped if r["label"] == 0]
    wpos, wneg = sum(r["weight"] for r in pos), sum(r["weight"] for r in neg)
    if wpos and wneg:
        if wpos < wneg:
            for r in pos: r["weight"] *= wneg / wpos
        else:
            for r in neg: r["weight"] *= wpos / wneg
    with CLEAN.open("w") as f:
        for r in deduped:
            f.write(json.dumps(r) + "\n")
    print(f"clean corpus: {len(deduped)} rows, pos={len(pos)} neg={len(neg)} -> {CLEAN}", flush=True)


def train_and_sweep() -> None:
    from sentence_transformers import SentenceTransformer
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import GroupShuffleSplit
    from sklearn.metrics import roc_auc_score
    import joblib

    rows = [json.loads(l) for l in CLEAN.open() if l.strip()]
    texts = [r["text"] for r in rows]
    y = np.array([r["label"] for r in rows])
    w = np.array([r["weight"] for r in rows], float)
    groups = np.array([r["group"] for r in rows])

    gss = GroupShuffleSplit(1, test_size=0.25, random_state=42)
    tr, te = next(gss.split(texts, y, groups))
    assert not (set(groups[tr]) & set(groups[te]))

    emb = SentenceTransformer(EMB_MODEL)
    X = emb.encode(texts, normalize_embeddings=True, batch_size=256, show_progress_bar=False)
    clf = LogisticRegression(max_iter=2000, C=1.0)
    clf.fit(X[tr], y[tr], sample_weight=w[tr])
    joblib.dump(clf, HERE / "artifacts" / "head.joblib")

    p_deny = clf.predict_proba(X[te])[:, 1]
    p_allow = 1 - p_deny
    yte = y[te]
    auc = roc_auc_score(yte, p_deny) if len(set(yte)) > 1 else float("nan")
    print(f"\n=== RETRAIN on cleaned corpus (leakage-safe) ===")
    print(f"AUC={auc:.4f}  test n={len(te)} pos={int(yte.sum())} neg={int((yte==0).sum())}")
    print(f"{'X':>7} {'n_shortcut':>11} {'missed_atk':>11} {'benign_prec':>12}")
    safe_X = None
    for Xthr in (0.90, 0.95, 0.99, 0.995, 0.999):
        m = p_allow >= Xthr
        n = int(m.sum()); missed = int((yte[m] == 1).sum())
        bp = float((yte[m] == 0).mean()) if n else float("nan")
        print(f"{Xthr:>7} {n:>11} {missed:>11} {bp:>12.4f}")
        if missed == 0 and n > 0 and safe_X is None:
            safe_X = Xthr
    # Also confident-DENY precision (the always-safe direction)
    for Xthr in (0.90, 0.95, 0.99):
        m = p_deny >= Xthr
        n = int(m.sum()); fp = int((yte[m] == 0).sum())
        prec = float((yte[m] == 1).mean()) if n else float("nan")
        print(f"  DENY@{Xthr}: n={n} false_blocks={fp} precision={prec:.4f}")
    print(f"\nSAFE ALLOW threshold X (0 missed attacks, n>0): {safe_X}")
    if safe_X:
        (HERE / "artifacts" / "threshold.json").write_text(json.dumps(
            {"allow_shortcircuit_min_confidence": safe_X,
             "deny_shortcircuit_min_confidence": 0.90,
             "note": "confident-ALLOW>=X short-circuits; confident-DENY short-circuits (blocks); else Haiku"},
            indent=2))


if __name__ == "__main__":
    clean()
    train_and_sweep()
