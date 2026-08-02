"""Report generator for benchmark runs (LLD 41 §7.3, FR-14.5)."""

from pathlib import Path
from typing import Any, Dict, List, Optional
from .manifest import redact_secrets


INTERSTITIAL_SENTENCE = (
    "Mode A below measures detector quality, not defense effectiveness. "
    "Mode A recall does not predict the ASR above in either direction — see LLD 41 §2.3."
)


def generate_report(
    manifest_data: Dict[str, Any],
    rows: List[Dict[str, Any]],
    output_path: Optional[Path] = None,
) -> str:
    """Generate Markdown report in fixed 5-section order."""
    lines = []

    # Section 1: Disclosures
    lines.append("# Sentra Security Benchmark Report")
    lines.append("")
    lines.append("## 1. Disclosures")
    lines.append("")
    dirty_flag = manifest_data.get("benchmark", {}).get("dirty", False)
    if dirty_flag:
        lines.append("> **WARNING**: Run conducted on a DIRTY git checkout (`--allow-dirty`).")
        lines.append("")
    
    suites = manifest_data.get("benchmark", {}).get("suites", ["all"])
    if suites != ["all"] and len(suites) < 5:
        lines.append("> **NOTE**: single-suite inner loop — not comparable to a full-suite headline.")
        lines.append("")

    disclosures = manifest_data.get("disclosures", [])
    if disclosures:
        for d in disclosures:
            lines.append(f"- {d}")
        lines.append("")
    else:
        lines.append("No active disclosures.")
        lines.append("")

    # Section 2: Mode B — defense effectiveness
    lines.append("## 2. Mode B — Defense Effectiveness")
    lines.append("")
    mode_b = manifest_data.get("results", {}).get("mode_b", {})
    if mode_b:
        asr_with = mode_b.get("asr_with", 0.0)
        asr_without = mode_b.get("asr_without", 0.0)
        reduction = mode_b.get("asr_reduction_pp", 0.0)
        noise_floor = mode_b.get("noise_floor_pp", 1.5)
        lines.append(f"- **ASR with defense**: {asr_with:.1f}%")
        lines.append(f"- **ASR without defense**: {asr_without:.1f}%")
        lines.append(f"- **ASR reduction**: {reduction:.1f} pp (noise floor: ±{noise_floor:.1f} pp)")
        lines.append(f"- **Refusal rate**: {mode_b.get('refuse_rate', 0.0):.1f}%")
        lines.append(f"- **Episodes quarantined**: {mode_b.get('episodes_quarantined', 0)}")
        lines.append("")
    else:
        lines.append("Mode B not executed for this run.")
        lines.append("")

    # Section 3: Interstitial sentence (LLD 41 §2.3)
    lines.append("---")
    lines.append(f"*{INTERSTITIAL_SENTENCE}*")
    lines.append("---")
    lines.append("")

    # Section 4: Mode A — detector metrics
    lines.append("## 3. Mode A — Detector Performance")
    lines.append("")
    mode_a = manifest_data.get("results", {}).get("mode_a", {})
    if mode_a:
        for detector_name, metrics in mode_a.items():
            readiness = metrics.get("readiness", "scored")
            lines.append(f"### Detector: {detector_name}")
            if readiness == "inert":
                lines.append("- **Status**: `inert` (no metrics rendered)")
            elif readiness.startswith("partial"):
                dead_leg = metrics.get("dead_leg", "unknown_leg")
                lines.append(f"- **Status**: `partial` (dead leg: {dead_leg})")
            else:
                recall = metrics.get("recall", 0.0)
                gate_verdict = metrics.get("fp_budget_gate", "PASS")
                lines.append(f"- **Recall**: {recall:.3f}")
                lines.append(f"- **Precision**: {metrics.get('precision', 0.0):.3f}")
                lines.append(f"- **F1**: {metrics.get('f1', 0.0):.3f}")
                lines.append(f"- **fp_budget_gate verdict**: {gate_verdict} (recall: {recall:.3f})")
            lines.append("")
    else:
        lines.append("Mode A metrics not available.")
        lines.append("")

    # Section 5: Errors & Exclusions
    lines.append("## 4. Errors & Exclusions")
    lines.append("")
    errors = manifest_data.get("errors", [])
    if errors:
        lines.append(f"Total recorded errors: {len(errors)}")
        for err in errors:
            lines.append(f"- {err}")
    else:
        lines.append("No errors encountered during run.")
    lines.append("")

    report_content = redact_secrets("\n".join(lines))
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report_content)

    return report_content
