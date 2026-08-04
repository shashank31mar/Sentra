"""BenchmarkSessionStore — In-memory, episode-scoped session store (LLD 41 §4.4a, WS-D milestone D1)."""

from typing import Any, Dict

from app.utils.session_manager import SessionManager


class BenchmarkSessionStore:
    """An in-memory dict-backed session store for isolated benchmark execution.

    Implements exactly the three async methods consumed by ValidationService:
    - get_or_create_session
    - update_trust_score_deny
    - update_trust_score_allow

    Delegates quarantine status, increment amounts, and recovery rules to SessionManager's
    pure helper functions to maintain structural parity.
    """

    def __init__(self, session_manager: SessionManager | None = None) -> None:
        self._sessions: Dict[str, Dict[str, Any]] = {}
        self._sm = session_manager or SessionManager()

    async def get_or_create_session(
        self,
        session_id: str,
        *,
        user_id: str = "bench_user",
        agent_id: str = "bench_agent",
    ) -> Dict[str, Any]:
        """Returns existing session or initializes a fresh episode session."""
        if session_id not in self._sessions:
            self._sessions[session_id] = {
                "session_id": session_id,
                "user_id": user_id,
                "agent_id": agent_id,
                "trust_score": 100.0,
                "quarantine_status": "active",
                "consecutive_allows": 0,
                "abuse_counters": {
                    "calls_this_minute": 0,
                    "last_minute_reset": 0,
                },
                "tool_history": [],
            }
        return self._sessions[session_id]

    async def update_trust_score_deny(
        self,
        session_id: str,
        violation_type: str = "DENY",
        reason: str = "",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Apply DENY penalty and update quarantine status."""
        session = await self.get_or_create_session(session_id)
        
        # Determine penalty amount (POLICY_NOT_FOUND or standard threat = -15)
        penalty = 15.0
        new_score = max(0.0, session["trust_score"] - penalty)
        
        session["trust_score"] = new_score
        session["quarantine_status"] = self._sm._get_quarantine_status(new_score)
        session["consecutive_allows"] = 0
        return session

    async def update_trust_score_allow(
        self,
        session_id: str,
        tool_name: str | None = None,
        agent_id: str | None = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Record ALLOW call, applying asymmetric recovery increment when threshold reached."""
        session = await self.get_or_create_session(session_id)
        current_score = session["trust_score"]

        if current_score >= 100.0:
            session["consecutive_allows"] = session.get("consecutive_allows", 0) + 1
            return session

        consecutive = session.get("consecutive_allows", 0) + 1
        req_allows = self._sm._get_consecutive_allows_required(current_score)

        if consecutive >= req_allows:
            inc = self._sm._get_increment_amount(current_score)
            new_score = min(100.0, current_score + inc)
            session["trust_score"] = new_score
            session["quarantine_status"] = self._sm._get_quarantine_status(new_score)
            session["consecutive_allows"] = 0
        else:
            session["consecutive_allows"] = consecutive

        return session
