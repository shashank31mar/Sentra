#!/usr/bin/env python3
"""Step 2 — assemble the training corpus from the teacher pairs + on-disk attack corpora.

INPUTS
  * data/teacher_raw.jsonl                     (step 1: distilled Haiku/Sonnet verdicts)
  * harness/ws0/corpus/indirect_injection.jsonl + exfiltration.jsonl   (attack positives)
  * src/security-controller/tests/fixtures/prompt_signatures/attacks.jsonl  (attack pos)
  * demo-agents/eval/labeled_prompts.jsonl     (mixed attack/benign, adds phrasing diversity)

WHY augment: the teacher pairs are real, but the acme agents replay only ~1,836 distinct
user_input strings. A model trained on those alone could confidently mis-ALLOW a NOVEL
attack (the SEC-7 short-circuit risk). The open/on-disk attack corpora inject phrasing
diversity the demo traffic lacks. All sources here are already IN-REPO (ws0 corpus,
test fixtures) — no external download, no new license obligation for this first build.

FEATURE TEXT (what the student embeds): a single normalized string combining the
structural context + the free text, matching what the teacher saw:
   "tool={tool_name} op={operation_type} | {user_input}"

LABEL: 1 = DENY (attack/block), 0 = ALLOW (benign). From the teacher's decision for
signal rows; from the corpus label for augmented rows (attack->1). Augmented attack
rows get tool="" op="" (they are raw injection text, tool-agnostic).

GROUP KEY (leakage guard): a hash of the normalized feature text. Step 3 does a
GROUP split on this so the SAME string never lands in both train and test — otherwise
the ~1,836-distinct-string replay would inflate eval to fake-perfect (memorization).

OUTPUT: data/corpus.jsonl — {text, label, group, weight, src}. `weight` upweights the
minority + the diverse attack rows so the student can't win by always-ALLOW.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # repo root
HERE = Path(__file__).resolve().parent.parent
OUT = HERE / "data" / "corpus.jsonl"


def _norm(tool: str, op: str, user_input: str) -> str:
    """The normalized feature text the student embeds (mirrors the teacher's view)."""
    tool = (tool or "").strip()
    op = (op or "").strip().upper()
    ui = " ".join((user_input or "").split())  # collapse whitespace
    return f"tool={tool} op={op} | {ui}"


def _group(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        print(f"  WARN missing: {path}", file=sys.stderr)
        return []
    return [json.loads(l) for l in path.open() if l.strip()]


def main() -> None:
    rows: list[dict] = []

    # --- teacher pairs (the primary, traffic-matched signal) ------------------
    teacher = _load_jsonl(HERE / "data" / "teacher_raw.jsonl")
    for r in teacher:
        text = _norm(r.get("tool_name"), r.get("operation_type"), r.get("user_input"))
        label = 1 if r.get("decision") == "DENY" else 0
        rows.append({"text": text, "label": label, "group": _group(text),
                     "weight": 1.0, "src": "teacher"})
    print(f"teacher rows: {len(teacher)}", file=sys.stderr)

    # --- attack positives from in-repo corpora (phrasing diversity) -----------
    # These are raw injection/exfiltration TEXT — tool-agnostic. Weighted UP (x3)
    # so the diverse novel-attack phrasing is not drowned by the 145k teacher rows;
    # this is the SEC-7 generalization guard, not just class balance.
    aug_sources = [
        (ROOT / "harness/ws0/corpus/indirect_injection.jsonl", "text", None, "ws0_indirect"),
        (ROOT / "harness/ws0/corpus/exfiltration.jsonl", "text", None, "ws0_exfil"),
        (ROOT / "src/security-controller/tests/fixtures/prompt_signatures/attacks.jsonl",
         "text", "label", "sig_attacks"),
        (ROOT / "demo-agents/eval/labeled_prompts.jsonl", "text", "label", "demo_labeled"),
    ]
    aug_pos = aug_neg = 0
    for path, text_key, label_key, srcname in aug_sources:
        for r in _load_jsonl(path):
            raw = r.get(text_key, "")
            if not raw:
                continue
            # label: explicit label field if present (attack->1, benign->0), else
            # the file is an attack-only corpus (ws0) → positive.
            if label_key and label_key in r:
                lv = str(r[label_key]).lower()
                label = 1 if lv in ("attack", "malicious", "1", "true", "injection", "deny") else 0
            else:
                label = 1  # ws0 corpora are attack-only
            text = _norm("", "", raw)
            rows.append({"text": text, "label": label, "group": _group(text),
                         "weight": 3.0, "src": srcname})
            aug_pos += label == 1
            aug_neg += label == 0
    print(f"augmented rows: +{aug_pos} attack / +{aug_neg} benign", file=sys.stderr)

    # --- dedupe exact (text,label) so a replayed string isn't counted 100x ----
    # Keep ONE row per (group,label) but remember how many collapsed, to reweight
    # by log(frequency) — a string seen 25k times shouldn't dominate 25000:1 over a
    # string seen once, but it IS more representative, so weight by log not raw count.
    import math, collections
    seen = collections.Counter((r["group"], r["label"]) for r in rows)
    best: dict[tuple, dict] = {}
    for r in rows:
        key = (r["group"], r["label"])
        if key not in best:
            r = dict(r)
            r["weight"] = r["weight"] * (1.0 + math.log1p(seen[key]))
            best[key] = r
    deduped = list(best.values())

    # --- class-balance the WEIGHTS so "always ALLOW" can't win ----------------
    pos = [r for r in deduped if r["label"] == 1]
    neg = [r for r in deduped if r["label"] == 0]
    wpos = sum(r["weight"] for r in pos)
    wneg = sum(r["weight"] for r in neg)
    # scale minority class weights up to parity (class_weight='balanced' equivalent,
    # applied on top of the freq weighting).
    if wpos and wneg:
        if wpos < wneg:
            for r in pos: r["weight"] *= wneg / wpos
        else:
            for r in neg: r["weight"] *= wpos / wneg

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w") as f:
        for r in deduped:
            f.write(json.dumps(r) + "\n")

    n_pos = len(pos); n_neg = len(neg)
    n_groups = len(set(r["group"] for r in deduped))
    print(f"\nDONE: {len(deduped)} unique (text,label) rows -> {OUT}", file=sys.stderr)
    print(f"  label 1 (DENY/attack)={n_pos}  label 0 (ALLOW)={n_neg}", file=sys.stderr)
    print(f"  distinct groups (unique texts)={n_groups}  "
          f"(step 3 GROUP-splits on these — no leakage)", file=sys.stderr)
    print(f"  weighted parity: pos_w={sum(r['weight'] for r in pos):.0f} "
          f"neg_w={sum(r['weight'] for r in neg):.0f}", file=sys.stderr)


if __name__ == "__main__":
    main()
