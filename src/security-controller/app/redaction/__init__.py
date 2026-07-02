"""Server-side redaction package — WS-E2 / LLD 29 §4-§6.

The SERVER half of the two-tier redactor (LLD 29 §2.1):
  * :mod:`phi_ner` — the Tier-2 free-text PHI redactor invoked by the DAG barrier
    node (LLD 29 §4.1, F1), plus the persist-gate ``GateDetector`` (§5.3.3, F2/F3).
  * :mod:`feedback_store` — the opt-in redacted feedback store write/eval/DSAR
    logic (LLD 29 §6), tested hermetically against a moto table.

Tier-1 (the edge structured-PII redactor) lives in the SDK, NOT here (LLD 29 §3.1).
"""
