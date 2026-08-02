"""Run-over-run diff tool (LLD 41 §7.3, G5)."""

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple


class IncompleteBaselineError(Exception):
    """Raised when diff baseline manifest exit status is not complete."""


class SchemaVersionMismatchError(Exception):
    """Raised when diff baseline and run schema_version differ."""


@dataclass
class DiffResult:
    fixed: List[str]  # case_ids: was ALLOW, now DENY
    regressed: List[str]  # case_ids: was DENY, now ALLOW
    unchanged: List[str]
    new_or_removed: List[str]
    adapter_moved_warning: bool
    aggregate_verdict: str  # "improved", "regressed", "unchanged", or "within-noise"
    asr_reduction_delta_pp: float
    noise_floor_pp: float


def compare_runs(
    current_manifest: Dict[str, Any],
    current_rows: List[Dict[str, Any]],
    baseline_manifest: Dict[str, Any],
    baseline_rows: List[Dict[str, Any]],
    noise_floor_pp: float = 1.5,
) -> DiffResult:
    """Compare current run against baseline run on case_id."""
    if baseline_manifest.get("exit") != "complete":
        raise IncompleteBaselineError(
            f"Baseline run exit status is '{baseline_manifest.get('exit')}', expected 'complete'."
        )

    curr_ver = current_manifest.get("schema_version", "1")
    base_ver = baseline_manifest.get("schema_version", "1")
    if curr_ver != base_ver:
        raise SchemaVersionMismatchError(
            f"Schema version mismatch: current={curr_ver}, baseline={base_ver}"
        )

    curr_cases = {r["case_id"]: r["decision"] for r in current_rows}
    base_cases = {r["case_id"]: r["decision"] for r in baseline_rows}

    fixed = []
    regressed = []
    unchanged = []
    new_or_removed = []

    all_keys = set(curr_cases.keys()) | set(base_cases.keys())
    for case_id in sorted(all_keys):
        if case_id in curr_cases and case_id in base_cases:
            c_dec = curr_cases[case_id]
            b_dec = base_cases[case_id]
            if b_dec == "ALLOW" and c_dec == "DENY":
                fixed.append(case_id)
            elif b_dec == "DENY" and c_dec == "ALLOW":
                regressed.append(case_id)
            else:
                unchanged.append(case_id)
        else:
            new_or_removed.append(case_id)

    curr_sha = current_manifest.get("benchmark", {}).get("git_sha")
    base_sha = baseline_manifest.get("benchmark", {}).get("git_sha")
    adapter_moved_warning = bool(new_or_removed and (curr_sha == base_sha))

    curr_red = current_manifest.get("results", {}).get("mode_b", {}).get("asr_reduction_pp", 0.0)
    base_red = baseline_manifest.get("results", {}).get("mode_b", {}).get("asr_reduction_pp", 0.0)
    delta = curr_red - base_red

    if abs(delta) < noise_floor_pp:
        aggregate_verdict = "within-noise"
    elif delta > 0:
        aggregate_verdict = "improved"
    elif delta < 0:
        aggregate_verdict = "regressed"
    else:
        aggregate_verdict = "unchanged"

    return DiffResult(
        fixed=fixed,
        regressed=regressed,
        unchanged=unchanged,
        new_or_removed=new_or_removed,
        adapter_moved_warning=adapter_moved_warning,
        aggregate_verdict=aggregate_verdict,
        asr_reduction_delta_pp=delta,
        noise_floor_pp=noise_floor_pp,
    )


compare_manifests = compare_runs
