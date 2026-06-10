"""An in-process emulator of the Sentra ``/v1/validate`` decision path (offline e2e harness).

Emulates exactly the core behaviors the demo relies on (verified against ``policy_engine.py`` /
``context_validator.py``, LLD 22 §6.5):
  * **sigma / injection** on ``user_input`` -> DENY (policy-independent);
  * **refund limit**: ``process_refund`` amount > $5000 -> DENY (hardcoded engine default);
  * **cross-cloud precondition**: refund/transfer/reset_sim/port_out require a prior
    ``verify_identity`` in the SAME session within the window -> else DENY ``cross_cloud_dependency_not_met``;
  * records ALLOWED calls in a shared session history (capped at 10, like ``session_manager``).

Wiring every agent's guard client to ONE instance is what makes the cross-cloud sequences work
offline: the Azure ``verify_identity`` and the AWS ``process_refund`` share the same session history.
This is a test/dev stand-in — the real decisions come from the deployed controller.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

# Cross-cloud preconditions (must match policies.demo.yaml).
_REQUIRES_VERIFY = {"process_refund", "transfer_funds", "reset_sim", "port_out_number"}
_VERIFY_TOOL = "verify_identity"
_MAX_REFUND = 5000.0

# Injection markers (a small stand-in for the sigma ruleset). Kept in sync with the deepset
# phrasings added to the live rule `sigma_rules/llm/prompt_injection_basic.yaml` (recall work), so
# the local mock agrees with what the deployed controller actually denies.
_INJECTION_SUBSTR = ("DROP TABLE", "UPDATE accounts", "jndi:", "{{7*7}}", "DELETE FROM")
_INJECTION_LOWER = (
    "ignore all previous", "ignore previous instructions", "ignore all preceding", "ignore the above",
    "you are now dan", "developer mode", "jailbreak", "disregard your policies", "exfiltrate",
    "bypass sentra", "pretend the verification",
    # deepset/prompt-injections phrasings (mirror the live sigma instruction_override/role_manipulation)
    "forget all previous", "forget everything", "forget about all", "new task:", "your new task",
    "focus on your new task", "start over with a new task", "i want you to act as", "now you are",
    "you will act as", "stay in character",
)


# Per-session trust (mirror session_manager): start 100, decay on DENY, quarantine at <= threshold.
_INITIAL_TRUST = 100.0
_QUARANTINE_AT = 40.0
_PENALTY = {"PROMPT_INJECTION": 20.0, "POLICY_VIOLATION": 15.0, "CROSS_CLOUD": 15.0, "REFUND_LIMIT": 10.0}


class FakeController:
    def __init__(self, window_s: float = 300.0, history_cap: int = 10) -> None:
        self.window_s = window_s
        self.history_cap = history_cap
        self._hist: Dict[str, List[Tuple[str, str, float]]] = {}  # session -> [(agent, tool, ts)]
        self._trust: Dict[str, float] = {}        # session -> running trust score
        self._quarantined: set = set()            # sessions past the quarantine threshold

    def _deny(self, sid: str, reason: str, threat: Any, kind: str) -> Dict[str, Any]:
        """Apply the trust penalty for a DENY, flip to quarantine at the threshold, and respond."""
        trust = self._trust.get(sid, _INITIAL_TRUST) - _PENALTY.get(kind, 10.0)
        self._trust[sid] = trust
        if trust <= _QUARANTINE_AT:
            self._quarantined.add(sid)
        return {"decision": "DENY", "reason": reason, "threat_type": threat, "trust_score": trust}

    def post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        sid = payload["session_id"]
        tool = payload["tool_name"]
        agent = payload["agent_id"]
        ui = payload.get("user_input", "") or ""
        params = payload.get("tool_params", {}) or {}
        now = time.monotonic()
        self._trust.setdefault(sid, _INITIAL_TRUST)

        # 0. Blast-radius containment: a quarantined session blocks EVERYTHING (even benign).
        if sid in self._quarantined:
            return {"decision": "DENY", "reason": "session quarantined — all operations blocked",
                    "threat_type": None, "trust_score": self._trust[sid]}

        # 1. Sigma / injection (independent of policy).
        low = ui.lower()
        if any(s in ui for s in _INJECTION_SUBSTR) or any(s in low for s in _INJECTION_LOWER):
            return self._deny(sid, "sigma:INJECTION", "PROMPT_INJECTION", "PROMPT_INJECTION")

        # 2a. High-fraud identity gate (real IEEE-CIS risk forwarded by the identity agent).
        if tool == _VERIFY_TOOL and str(params.get("fraud_risk", "")).lower() == "high":
            return self._deny(sid, "Identity verification refused: high fraud risk",
                              None, "POLICY_VIOLATION")

        # 2b. Hardcoded refund limit.
        if tool == "process_refund":
            try:
                amount = float(params.get("amount", 0))
            except (TypeError, ValueError):
                amount = 0.0
            if amount > _MAX_REFUND:
                return self._deny(sid, "max_refund_amount exceeded ($5000)", None, "REFUND_LIMIT")

        # 3. Cross-cloud precondition.
        if tool in _REQUIRES_VERIFY:
            recent = [h for h in self._hist.get(sid, []) if now - h[2] <= self.window_s]
            if not any(h[1] == _VERIFY_TOOL for h in recent):
                return self._deny(sid, "cross_cloud_dependency_not_met", None, "CROSS_CLOUD")

        # 4. ALLOW — record (newest-last, capped). Only ALLOWED calls satisfy preconditions.
        hist = self._hist.setdefault(sid, [])
        hist.append((agent, tool, now))
        self._hist[sid] = hist[-self.history_cap:]
        return {"decision": "ALLOW", "reason": "ok", "trust_score": self._trust[sid]}
