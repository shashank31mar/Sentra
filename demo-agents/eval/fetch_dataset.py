#!/usr/bin/env python3
"""Fetch a real, labeled prompt-injection dataset for the traffic loop + the eval harness.

Source: **deepset/prompt-injections** (HuggingFace) — 662 prompts labeled benign (0) / injection (1).
Pulled via the public HF datasets-server API (no auth). Writes two artifacts:

  1. ``traffic/attack_prompts/injection.txt``  — the injection prompts (label=1), one per line, used
     by the continuous traffic generator so the DENY traffic is REAL attacks, not hand-written.
  2. ``eval/labeled_prompts.jsonl``            — every {text,label} row, the ground truth for
     ``measure.py`` (precision/recall/F1 of the security controller).

    python demo-agents/eval/fetch_dataset.py
"""
from __future__ import annotations

import json
import pathlib
import urllib.parse
import urllib.request

HERE = pathlib.Path(__file__).resolve().parent
DEMO = HERE.parent
DATASET = "deepset/prompt-injections"
API = "https://datasets-server.huggingface.co/rows"


def fetch_split(split: str) -> list[tuple[str, int]]:
    rows: list[tuple[str, int]] = []
    offset = 0
    while True:
        q = urllib.parse.urlencode({"dataset": DATASET, "config": "default",
                                    "split": split, "offset": offset, "length": 100})
        with urllib.request.urlopen(f"{API}?{q}", timeout=30) as r:
            data = json.load(r)
        batch = data.get("rows", [])
        if not batch:
            break
        rows += [(x["row"]["text"], int(x["row"]["label"])) for x in batch]
        offset += len(batch)
        if offset >= data.get("num_rows_total", offset):
            break
    return rows


def main() -> int:
    rows: list[tuple[str, int]] = []
    for split in ("train", "test"):
        s = fetch_split(split)
        print(f"  {split}: {len(s)} rows")
        rows += s

    def clean(t: str) -> str:
        return " ".join(t.split()).strip()

    injections = [clean(t) for t, lbl in rows if lbl == 1 and clean(t)]
    benign = [t for t, lbl in rows if lbl == 0]
    print(f"  total {len(rows)} | injection {len(injections)} | benign {len(benign)}")

    corpus = DEMO / "traffic" / "attack_prompts" / "injection.txt"
    corpus.write_text(
        f"# Real injection prompts from {DATASET} (HuggingFace, label=1).\n"
        f"# https://huggingface.co/datasets/{DATASET}  |  refresh: python demo-agents/eval/fetch_dataset.py\n"
        + "\n".join(injections) + "\n"
    )
    print(f"  wrote {corpus} ({len(injections)} attacks)")

    labeled = HERE / "labeled_prompts.jsonl"
    with labeled.open("w") as f:
        for t, lbl in rows:
            if clean(t):
                f.write(json.dumps({"text": clean(t), "label": lbl}) + "\n")
    print(f"  wrote {labeled} ({len(rows)} labeled rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
