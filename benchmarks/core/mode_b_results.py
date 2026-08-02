"""Mode B results aggregation and attribution rollups (LLD 41 §4.6, WS-E milestone E6)."""

from typing import Any, Dict, List


def build_mode_b_results(
    cases_rows: List[Dict[str, Any]],
    synthetic_content_skipped: int = 0,
) -> Dict[str, Any]:
    """Aggregate Mode B cases rows into manifest results.mode_b block."""
    episodes_quarantined_set = set()
    first_deny_by_ep: Dict[str, str] = {}
    all_denies: Dict[str, int] = {}

    for row in cases_rows:
        ep_id = row.get("episode_id", row.get("case_id", "unknown"))
        if row.get("quarantined"):
            episodes_quarantined_set.add(ep_id)

        # Look for DENY decisions
        decision = row.get("decision")
        source = row.get("deciding_source", "unattributed")

        if decision == "DENY" or row.get("allowed") is False:
            all_denies[source] = all_denies.get(source, 0) + 1
            if ep_id not in first_deny_by_ep:
                first_deny_by_ep[ep_id] = source

    first_deny_counts: Dict[str, int] = {}
    for src in first_deny_by_ep.values():
        first_deny_counts[src] = first_deny_counts.get(src, 0) + 1

    total_first_denies = sum(first_deny_counts.values())
    trust_first_denies = first_deny_counts.get("sentra.trust", 0)

    worded_finding = None
    if total_first_denies > 0 and (trust_first_denies / total_first_denies) > 0.5:
        worded_finding = (
            "G2 is defeated for this run: sentra.trust dominates attribution "
            f"({trust_first_denies}/{total_first_denies} = {trust_first_denies/total_first_denies*100:.1f}% of first-denies)."
        )

    return {
        "episodes_quarantined": len(episodes_quarantined_set),
        "synthetic_content_skipped": synthetic_content_skipped,
        "by_deciding_source_first_deny": first_deny_counts,
        "by_deciding_source_all_denies": all_denies,
        "trust_dominance_finding": worded_finding,
    }
