"""EventBridge-triggered traffic Lambda (LLD 22 §9).

Fires one batch of labelled cross-cloud sequences per tick against the deployed agents, so the
console shows a steady ALLOW/DENY stream. Stdlib + boto3 only (no SDK here — it calls the agents,
which call Sentra). Env: PAYMENTS_LAMBDA_NAME, IDENTITY_FUNC_URL, TELECOM_FUNC_URL.
"""
from __future__ import annotations

import random

from generator import LiveInvoker, build_sequences, run


def handler(event=None, context=None):
    seqs = build_sequences(seed=random.randint(0, 10**6))
    tally = run(seqs, LiveInvoker())
    print(f"traffic tick complete: {tally}")
    return {"sequences": len(seqs), "tally": tally}
