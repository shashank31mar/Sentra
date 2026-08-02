"""Unit tests for two-pass replay rig (LLD 41 §4.3, §5.1, WS-C milestone C1)."""

from unittest.mock import AsyncMock, MagicMock
import pytest
from app.api.models import ValidationResult
from benchmarks.core.case import BenchmarkCase
from benchmarks.core.context import RunContext
from benchmarks.rigs.replay import CorpusIntegrityError, run_replay


@pytest.fixture
def run_ctx(tmp_path):
    return RunContext(
        run_id="run1",
        run_clock_iso="2026-07-27T14:02:11Z",
        transcript_dir=tmp_path,
        mode="A",
    )


def make_test_case(case_id: str, label: bool) -> BenchmarkCase:
    return BenchmarkCase(
        benchmark="agentdojo",
        suite="banking",
        case_id=case_id,
        episode_id=case_id,
        phase="request",
        agent_id="a1",
        tool_name="t1",
        tool_params={},
        user_input="prompt",
        content_text=None,
        operation_type="READ",
        label=label,
        attack_type="indirect_injection" if label else None,
        injection_goal="goal" if label else None,
        expected_outcome="deny" if label else "allow",
        raw={},
    )


@pytest.mark.asyncio
async def test_detector_exception_drops_case_and_counts_it(run_ctx):
    cases = [make_test_case(f"c{i}", label=(i % 2 == 0)) for i in range(100)]

    detector = MagicMock()
    # Raise exception on case c0, return normal ValidationResult for rest
    async def fake_validate(req):
        if req.request_id == "bench-c0":
            raise ValueError("Simulated fault")
        return ValidationResult(is_valid=True, action="allow", reason="ok", source="sentra.test")

    detector.validate = AsyncMock(side_effect=fake_validate)

    res = await run_replay(detector, "D2", cases, ctx=run_ctx)
    assert res.scored_count == 99
    assert len(res.errors) == 1
    assert res.errors[0].case_id == "bench-c0"
    assert res.scored_count + len(res.errors) == res.total_cases


@pytest.mark.asyncio
async def test_error_is_never_scored_as_allow(run_ctx):
    cases = [make_test_case(f"c{i}", label=(i < 50)) for i in range(100)]

    detector = MagicMock()
    async def fake_validate(req):
        if req.request_id == "bench-c0":
            raise ValueError("Simulated fault")
        return ValidationResult(is_valid=False, action="deny", reason="threat", source="sentra.test")

    detector.validate = AsyncMock(side_effect=fake_validate)

    res = await run_replay(detector, "D2", cases, ctx=run_ctx)
    scores = res.detector_scores
    assert scores["tp"] + scores["fp"] + scores["tn"] + scores["fn"] == 99


@pytest.mark.asyncio
async def test_detector_invoked_exactly_once_per_case(run_ctx):
    cases = [make_test_case(f"c{i}", label=False) for i in range(5)]

    detector = MagicMock()
    detector.validate = AsyncMock(return_value=ValidationResult(is_valid=True, action="allow", reason="ok", source="s"))

    res = await run_replay(detector, "D2", cases, ctx=run_ctx)
    assert detector.validate.call_count == 5


@pytest.mark.asyncio
async def test_abort_above_2pc_error_rate(run_ctx):
    # 3 errors out of 100 cases (3% > 2%)
    cases = [make_test_case(f"c{i}", label=False) for i in range(100)]

    detector = MagicMock()
    async def fake_validate(req):
        if req.request_id in ("bench-c0", "bench-c1", "bench-c2"):
            raise RuntimeError("Error")
        return ValidationResult(is_valid=True, action="allow", reason="ok", source="s")

    detector.validate = AsyncMock(side_effect=fake_validate)

    with pytest.raises(CorpusIntegrityError):
        await run_replay(detector, "D2", cases, ctx=run_ctx)
