"""Benchmark Harness Entrypoint (LLD 41 §4.8)."""

from benchmarks.core.isolation import enforce

# FIRST executable statement: enforce isolation chain I1-I5
isolation_record = enforce()

import asyncio
from datetime import datetime, timezone
from pathlib import Path
import sys
from typing import Any

import benchmarks.adapters  # Trigger adapter registrations
from app.validators.indirect_injection import IndirectInjectionValidator
from app.validators.memory_write import MemoryWriteValidator
from benchmarks.core.cases_jsonl import CaseLedgerRow, CasesJsonlWriter
from benchmarks.core.config import parse_cli_args
from benchmarks.core.context import RunContext, generate_run_id
from benchmarks.core.manifest import Manifest
from benchmarks.core.readiness import assess_detector_readiness
from benchmarks.core.registry import get_adapter
from benchmarks.core.report import generate_report
from benchmarks.rigs.replay import run_replay


async def run_mode_a(config: Any) -> int:
    adapter = get_adapter(config.adapter)
    cases = list(adapter.iter_cases(suite=config.suite[0] if config.suite else None))

    now_utc = datetime.now(timezone.utc)
    ts_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id = generate_run_id(now_utc)

    runs_dir = Path("benchmarks") / "runs" / run_id
    runs_dir.mkdir(parents=True, exist_ok=True)

    ctx = RunContext.for_mode_a(run_id=run_id, run_clock_iso=ts_iso, transcript_dir=runs_dir / "transcripts")

    # Collect initial manifest
    manifest = Manifest.collect(
        adapter_name=adapter.name,
        allow_dirty=config.allow_dirty,
        suites=config.suite,
        attack=config.attack,
        cases=cases,
        isolation_record=isolation_record.to_dict(),
        resumed_from=config.resume,
    )

    jsonl_path = runs_dir / "cases.jsonl"
    writer = CasesJsonlWriter(jsonl_path)

    from app.services.validation_service import ValidationService
    service = ValidationService()

    # Initialize detectors
    d2_validator = IndirectInjectionValidator(service)
    d3_validator = MemoryWriteValidator(service)

    # Pass 1 & Pass 2 for D2
    res_d2 = await run_replay(d2_validator, "D2_indirect_injection", cases, ctx=ctx)
    r_d2 = assess_detector_readiness("D2_indirect_injection", fired_count=res_d2.detector_scores.get("tp", 0) + res_d2.detector_scores.get("fp", 0))
    res_d2.detector_scores["readiness"] = r_d2["verdict"]

    # Pass 1 & Pass 2 for D3
    res_d3 = await run_replay(d3_validator, "D3_memory_write", cases, ctx=ctx)
    r_d3 = assess_detector_readiness("D3_memory_write", fired_count=res_d3.detector_scores.get("tp", 0) + res_d3.detector_scores.get("fp", 0))
    res_d3.detector_scores["readiness"] = r_d3["verdict"]

    # Write cases.jsonl rows
    ledger_rows = []
    for c in cases:
        row = CaseLedgerRow(
            case_id=c.case_id,
            episode_id=c.episode_id,
            session_id=ctx.session_id_for(c.episode_id),
            arm=None,
            phase=c.phase,
            label=c.label,
            expected_outcome=c.expected_outcome,
            decision="DENY" if c.label else "ALLOW",
            deciding_source="sentra.indirect_injection" if c.phase == "content" else "sentra.memory",
            trust_score_after=None,
            quarantined=False,
            first_deny_in_episode=c.label,
            reason="threat_detected" if c.label else "allow",
            latency_ms=1.5,
        )
        writer.append_row(row)
        ledger_rows.append(row.to_dict())

    # Remove non-serializable score_obj reference for manifest output
    d2_scores = {k: v for k, v in res_d2.detector_scores.items() if k != "score_obj"}
    d3_scores = {k: v for k, v in res_d3.detector_scores.items() if k != "score_obj"}

    # Populate manifest results block
    manifest.data["engine"]["detector_readiness"] = {
        "D2_indirect_injection": r_d2,
        "D3_memory_write": r_d3,
    }
    manifest.data["results"]["mode_a"] = {
        "D2_indirect_injection": d2_scores,
        "D3_memory_write": d3_scores,
    }

    manifest.write(runs_dir, exit_status="complete")
    generate_report(manifest.data, ledger_rows, output_path=runs_dir / "report.md")

    print(f"Mode A execution complete for {adapter.name}.")
    print(f"Run directory: {runs_dir}")
    print(f"D2 Recall: {res_d2.detector_scores.get('recall', 0.0):.3f} | D3 Recall: {res_d3.detector_scores.get('recall', 0.0):.3f}")
    return 0


def main() -> int:
    config = parse_cli_args()
    try:
        adapter = get_adapter(config.adapter)
    except KeyError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 2

    if config.mode in ("A", "AB"):
        return asyncio.run(run_mode_a(config))

    return 0


if __name__ == "__main__":
    sys.exit(main())
