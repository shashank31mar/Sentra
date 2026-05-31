"""Unit tests for the combiner module — Workstream 17 / LLD 17 §14.1.

Test IDs 1-9 from the LLD test plan plus a small set of codec round-trip
tests for the Signal dataclass. No AWS or DDB involvement — pure-Python.

Run from src/security-controller/:
    PYTHONPATH=. pytest tests/test_combiner.py -v
"""

import pytest

from app.combiners import Signal, DenyOverrides
from app.combiners.protocol import CombiningAlgorithm


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _sig(source: str, decision: str = "ALLOW", priority: int = 0, **kw) -> Signal:
    """Compact Signal constructor for test readability."""
    return Signal(source=source, decision=decision, priority=priority, **kw)


# ---------------------------------------------------------------------------
# Signal codec
# ---------------------------------------------------------------------------


class TestSignalCodec:
    def test_round_trip_minimal(self):
        s = Signal(source="sentra.sigma", decision="DENY", reason="PII")
        assert Signal.from_dict(s.to_dict()) == s

    def test_round_trip_full(self):
        s = Signal(
            source="sentra.ml_classifier",
            decision="DENY",
            reason="adversarial",
            priority=70,
            confidence=0.92,
            threat_type="ADVERSARIAL_PATTERN",
            matched_rule="ml-v1",
            severity="HIGH",
            metadata={"model_version": "1.2.3"},
        )
        assert Signal.from_dict(s.to_dict()) == s

    def test_from_dict_drops_unknown_keys(self):
        """Forward-compat: a writer that adds new attrs shouldn't break readers."""
        s = Signal.from_dict({
            "source": "sentra.sigma",
            "decision": "ALLOW",
            "future_field": "ignored",
        })
        assert s.source == "sentra.sigma"

    def test_from_dict_normalizes_none_metadata(self):
        """Old CW events may have metadata=None; normalize to {}."""
        s = Signal.from_dict({"source": "x", "decision": "ALLOW", "metadata": None})
        assert s.metadata == {}


# ---------------------------------------------------------------------------
# DenyOverrides algorithm — LLD §14.1 tests 1-9
# ---------------------------------------------------------------------------


class TestDenyOverrides:
    """The 9 cases LLD 17 §14.1 demands. Test IDs in the docstrings."""

    @pytest.fixture
    def algo(self) -> CombiningAlgorithm:
        return DenyOverrides()

    def test_01_empty_signals_raises(self, algo):
        """Test 1: empty list → ValueError (no defensible default verdict)."""
        with pytest.raises(ValueError):
            algo.combine([])

    def test_02_single_allow_returns_allow(self, algo):
        """Test 2: single ALLOW → combined ALLOW with no winning source."""
        result = algo.combine([_sig("sentra.sigma", "ALLOW", priority=70)])
        assert result.decision == "ALLOW"
        assert result.source == "combined"
        assert result.metadata["winning_source"] is None

    def test_03_single_deny_returns_deny(self, algo):
        """Test 3: single DENY → combined DENY, that source wins."""
        result = algo.combine([_sig("sentra.sigma", "DENY", priority=70, reason="PII")])
        assert result.decision == "DENY"
        assert result.reason == "PII"
        assert result.metadata["winning_source"] == "sentra.sigma"

    def test_04_all_allow_returns_allow(self, algo):
        """Test 4: all 5 ALLOW → combined ALLOW."""
        result = algo.combine([
            _sig("sentra.trust", "ALLOW", priority=90),
            _sig("sentra.policy", "ALLOW", priority=80),
            _sig("sentra.sigma", "ALLOW", priority=70),
            _sig("sentra.context", "ALLOW", priority=60),
            _sig("sentra.abuse", "ALLOW", priority=50),
        ])
        assert result.decision == "ALLOW"

    def test_05_multiple_denies_highest_priority_wins(self, algo):
        """Test 5: multiple DENYs distinct priorities → highest wins."""
        result = algo.combine([
            _sig("sentra.sigma", "DENY", priority=70, reason="sigma reason"),
            _sig("bedrock_guardrail", "DENY", priority=40, reason="guardrail reason"),
        ])
        assert result.decision == "DENY"
        assert result.metadata["winning_source"] == "sentra.sigma"
        assert result.reason == "sigma reason"

    def test_06_tied_priority_confidence_wins(self, algo):
        """Test 6: tied priority + different confidence → higher confidence wins (Example D)."""
        result = algo.combine([
            _sig("sentra.sigma", "DENY", priority=70, confidence=0.55, reason="weak regex"),
            _sig("sentra.ml_classifier", "DENY", priority=70, confidence=0.92, reason="adversarial"),
        ])
        assert result.decision == "DENY"
        assert result.metadata["winning_source"] == "sentra.ml_classifier"
        assert result.reason == "adversarial"

    def test_07_tied_priority_and_confidence_deterministic(self, algo):
        """Test 7: tied priority + tied confidence → alphabetically first source wins.

        Run the same combine 5x — must produce the same winner every time.
        """
        winners = set()
        for _ in range(5):
            result = algo.combine([
                _sig("sentra.sigma", "DENY", priority=70, confidence=0.7),
                _sig("sentra.context", "DENY", priority=70, confidence=0.7),
                _sig("sentra.policy", "DENY", priority=70, confidence=0.7),
            ])
            winners.add(result.metadata["winning_source"])
        assert len(winners) == 1, f"non-deterministic — saw {winners}"
        # sentra.context sorts before sentra.policy before sentra.sigma
        assert winners == {"sentra.context"}

    def test_08_bedrock_deny_sentra_allow_combined_deny(self, algo):
        """Test 8 / Example B: bedrock_guardrail DENY + Sentra ALLOWs → combined DENY."""
        result = algo.combine([
            _sig("sentra.sigma", "ALLOW", priority=70),
            _sig("sentra.policy", "ALLOW", priority=80),
            _sig("bedrock_guardrail", "DENY", priority=40, reason="Hate speech"),
        ])
        assert result.decision == "DENY"
        assert result.metadata["winning_source"] == "bedrock_guardrail"
        assert result.reason == "Hate speech"

    def test_09_unknown_source_priority_zero_handled(self, algo):
        """Test 9: unknown source → defaults to priority=0, combine doesn't crash."""
        result = algo.combine([
            _sig("future.experimental_validator", "DENY", priority=0, reason="experimental"),
            _sig("sentra.sigma", "DENY", priority=70, reason="real"),
        ])
        # sentra.sigma's priority dominates the unknown source
        assert result.decision == "DENY"
        assert result.metadata["winning_source"] == "sentra.sigma"


# ---------------------------------------------------------------------------
# Algorithm-as-Protocol sanity check
# ---------------------------------------------------------------------------


def test_deny_overrides_satisfies_protocol():
    """DenyOverrides must structurally satisfy CombiningAlgorithm."""
    algo = DenyOverrides()
    # `name` attribute
    assert algo.name == "deny-overrides"
    # Callable `combine` with the expected signature
    assert callable(algo.combine)
    # runtime_checkable Protocol — isinstance works
    assert isinstance(algo, CombiningAlgorithm)


# ---------------------------------------------------------------------------
# WS19 — sigma must outrank ml_classifier in winning_source tiebreaks
# ---------------------------------------------------------------------------


def test_sigma_outranks_ml_classifier_when_both_deny():
    """Per LLD 19 §6.1: when sigma and ml_classifier both DENY, sigma must be
    the winning_source because its deterministic regex match is more
    explainable for compliance teams. Used to fail when both validators
    shared priority=70 — ML's higher confidence won the (priority, confidence)
    tiebreak. sources.py now sets ML to 65, strictly below sigma at 70."""
    from app.combiners import Source
    from app.combiners.sources import DEFAULT_PRIORITIES

    sigma = _sig(
        Source.SENTRA_SIGMA, decision="DENY",
        priority=DEFAULT_PRIORITIES[Source.SENTRA_SIGMA],
        reason="Pattern matched: 'forget previous instructions'",
        threat_type="PROMPT_INJECTION",
        # sigma typically doesn't populate confidence — it's a deterministic match
    )
    ml = _sig(
        Source.SENTRA_ML_CLASSIFIER, decision="DENY",
        priority=DEFAULT_PRIORITIES[Source.SENTRA_ML_CLASSIFIER],
        reason="Request asks the model to disregard prior system instructions",
        threat_type="PROMPT_INJECTION",
        confidence=0.95,  # high — would beat sigma's None confidence at equal priority
    )

    # Try both orderings — combiner result must be order-independent.
    for order in ([sigma, ml], [ml, sigma]):
        combined = DenyOverrides().combine(order)
        assert combined.decision == "DENY"
        # DenyOverrides emits source="combined" with the winner exposed via
        # metadata["winning_source"] (see deny_overrides.py:51).
        winning = combined.metadata.get("winning_source")
        assert winning == Source.SENTRA_SIGMA, (
            f"sigma must outrank ml_classifier; got winning_source={winning} "
            f"(input order {[s.source for s in order]}). Check DEFAULT_PRIORITIES "
            "in sources.py — sigma must be strictly > ml_classifier."
        )
