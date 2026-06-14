"""Cedar generator (CT12) — structured AgentPolicyDocument → compiled Cedar text.

Single source of truth for turning a stored structured policy into its `.cedar`
co-artifact. Used by:
  * the save path (`policy_service.create/update_policy`) — born-Cedar when
    `cedar_enabled`,
  * the backfill translator (`scripts/translate_policies_to_cedar.py`, CT08),
  * the read-only generated-Cedar preview API (CT13).

Model (feature §6.1 / workstream §4b): the authorization RULES are universal
(the bundled `baseline-v{N}.cedar`, derived from `policy_engine`'s real hardcoded
checks); ALL per-agent variance is entity-borne (synthesized at evaluation time
by CT05b), NOT baked into the `.cedar` text. So generation = a provenance header
+ the validated baseline rule set, identical for every agent. Per-agent
structured fields (allow-lists, refund cap) are consumed at evaluation time by
the entity synthesizer, NOT by this generator — so there is no per-policy
expressibility check here; the baseline is schema-validated once. The inert
`policies[].rule` strings are NOT translated (they enforce nothing — C2).

Generated Cedar is READ-ONLY (Kiro #6 single-source-of-truth): the structured
view is the only editor while it exists; there is no Cedar→structured round-trip.
"""
from __future__ import annotations

from app.validators.cedar.schema import CEDAR_SCHEMA_VERSION, get_baseline_policies

# Bump REQUIRES re-running the CT08 backfill: the compiled-Cedar cache key (CT06)
# includes generator_version, and persisted .cedar is otherwise stale even though
# the structured source is unchanged.
GENERATOR_VERSION = "v1"


def generate_cedar(policy_id: str, structured_policy: dict | None = None) -> str:
    """Return the compiled `.cedar` text for a policy: a provenance header + the
    universal baseline rule set. `structured_policy` is accepted for future
    per-agent extension and expressibility checks; today only `policy_id` is used
    in the header (per-agent data is entity-borne)."""
    header = (
        f"// GENERATED — do not edit. Source of truth is the structured .yaml.\n"
        f"// policy_id: {policy_id}\n"
        f"// generator_version: {GENERATOR_VERSION}  schema_version: {CEDAR_SCHEMA_VERSION}\n"
        f"// Per-agent allow-lists / refund cap / cross-cloud deps are entity-borne\n"
        f"// (synthesized at evaluation time), not baked into these rules.\n\n"
    )
    return header + get_baseline_policies()
