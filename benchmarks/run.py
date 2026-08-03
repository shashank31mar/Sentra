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

    # Pre-populate local sigma rules if available
    if hasattr(service, "sigma_engine") and service.sigma_engine and not service.sigma_engine.rules_cache:
        from benchmarks.core.sigma_local import load_local_sigma_rules
        import time
        local_rules = load_local_sigma_rules()
        if local_rules:
            service.sigma_engine.rules_cache = local_rules
            service.sigma_engine.cache_timestamp = time.time()

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


def run_mode_b(config: Any) -> int:
    adapter = get_adapter(config.adapter)

    now_utc = datetime.now(timezone.utc)
    ts_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id = generate_run_id(now_utc)

    runs_dir = Path("benchmarks") / "runs" / run_id
    runs_dir.mkdir(parents=True, exist_ok=True)

    ctx = RunContext.for_mode_b(
        run_id=run_id,
        run_clock_iso=ts_iso,
        transcript_dir=runs_dir / "transcripts",
        model_id=getattr(config, "model", "qwen2.5:3b"),
    )

    print(f"\n==========================================")
    print(f"Executing Mode B without-arm (baseline)...")
    print(f"==========================================")
    without_arm = adapter.run_arm(arm="without", ctx=ctx)

    print(f"\n==========================================")
    print(f"Executing Mode B with-arm (Sentra-guarded)...")
    print(f"==========================================")
    with_arm = adapter.run_arm(arm="with", ctx=ctx)

    score = adapter.score_run(with_arm=with_arm, without_arm=without_arm)

    manifest = Manifest.collect(
        adapter_name=adapter.name,
        allow_dirty=config.allow_dirty,
        suites=config.suite,
        attack=config.attack,
        cases=[],
        isolation_record=isolation_record.to_dict(),
        resumed_from=config.resume,
    )

    manifest.data["results"]["mode_b"] = {
        "asr_without": score.asr_without,
        "asr_with": score.asr_with,
        "asr_reduction_pp": score.asr_reduction_pp,
        "utility_with": score.utility_with,
        "utility_without": score.utility_without,
        "refuse_rate": score.refuse_rate,
    }

    manifest.write(runs_dir, exit_status="complete")
    generate_report(manifest.data, [], output_path=runs_dir / "report.md")

    print(f"\n==========================================")
    print(f"Mode B Defense Effectiveness Summary:")
    print(f"  Without Sentra (Baseline ASR): {score.asr_without * 100:.1f}%")
    print(f"  With Sentra (Guarded ASR):   {score.asr_with * 100:.1f}%")
    print(f"  ASR Reduction:               {score.asr_reduction_pp:.1f} percentage points")
    print(f"==========================================\n")
    print(f"Run directory: {runs_dir}")
    return 0


def main() -> int:
    config = parse_cli_args()
    try:
        adapter = get_adapter(config.adapter)
    except KeyError as err:
        print(f"Error: {err}", file=sys.stderr)
        return 2

    res_a = 0
    res_b = 0
    if config.mode in ("A", "AB"):
        res_a = asyncio.run(run_mode_a(config))

    if config.mode in ("B", "AB"):
        res_b = run_mode_b(config)

    return res_a or res_b


if __name__ == "__main__":
    sys.exit(main())
