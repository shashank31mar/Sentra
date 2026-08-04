"""Noise floor calculation and dispersion estimation (LLD 41 §7.1.1, WS-E milestone E5)."""

import math
from typing import Any, Dict, List, Literal


def calculate_noise_floor(
    replicates: List[float],
    method: Literal["paired", "single_arm_x_sqrt2"] = "paired",
) -> Dict[str, Any]:
    """Calculate noise_floor_pp over >= 2 replicate pairs as max absolute pairwise difference.
    
    Refuses n < 2 replicates with ValueError.
    """
    n = len(replicates)
    if n < 2:
        raise ValueError(f"Noise floor estimation requires >= 2 replicate pairs; got n={n}")

    # Calculate max absolute pairwise difference
    max_diff = 0.0
    for i in range(n):
        for j in range(i + 1, n):
            diff = abs(replicates[i] - replicates[j])
            if diff > max_diff:
                max_diff = diff

    final_floor_pp = max_diff
    independence_assumption = None

    if method == "single_arm_x_sqrt2":
        final_floor_pp = max_diff * math.sqrt(2)
        independence_assumption = "Assumes without-arm and with-arm variance are independent; inflated single-arm spread by sqrt(2)."

    return {
        "n_replicates": n,
        "method": method,
        "noise_floor_pp": round(final_floor_pp, 2),
        "raw_spread_pp": round(max_diff, 2),
        "independence_assumption": independence_assumption,
    }
