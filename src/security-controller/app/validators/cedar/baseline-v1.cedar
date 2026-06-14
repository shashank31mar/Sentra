// Sentra baseline Cedar policy set (feature: cedar-policy §6 / §6.1).
//
// These rules are UNIVERSAL — identical for every agent. All per-agent variance
// (which tools/agents are allowed, the refund cap) lives in the synthesized
// entity store (CT05b): `principal.allowed_tools`, `principal.allowed_agents`,
// `principal.max_refund_amount`. The translator (CT08) appends any agent-specific
// rules derived from a policy's structured fields to a copy of this baseline.
//
// Cedar-semantics invariants baked in here (do NOT remove the guards):
//   * forbid wins over permit, so every dangerous tool is a `forbid`.
//   * a `forbid` that reads a MISSING context/principal attribute errors and is
//     DROPPED — which fails OPEN. Every optional attribute access is therefore
//     `has`-guarded, and dangerous tools get an explicit deny-on-missing.
//   * money is Long CENTS (Cedar has no float); CedarContext coerces to cents.

// --- tool allow-list -------------------------------------------------------
// Per-agent allow-list carried as a Set<Tool> principal attribute.
@id("permit_use_tool")
permit(principal, action == Action::"UseTool", resource)
when { resource in principal.allowed_tools };

// --- refund cap ------------------------------------------------------------
// Long cents. has-guards BOTH the context amount AND the principal attribute
// (a policy omitting max_refund_amount would otherwise error → fail-open).
@id("forbid_refund_over_cap")
forbid(principal, action == Action::"UseTool", resource == Tool::"process_refund")
when {
  context has amount &&
  principal has max_refund_amount &&
  context.amount > principal.max_refund_amount
};

// Deny-on-missing: a refund with NO coercible amount must fail SECURE, not open.
@id("forbid_refund_missing_amount")
forbid(principal, action == Action::"UseTool", resource == Tool::"process_refund")
unless { context has amount };

// --- high-fraud identity gate ----------------------------------------------
@id("forbid_high_fraud_identity")
forbid(principal, action == Action::"UseTool", resource == Tool::"verify_identity")
when { context has fraud_risk && context.fraud_risk == "high" };

// --- agent-to-agent invocation ---------------------------------------------
// Second of the two AND-ed authorizations for invoke_agent (CT04): the target
// must be in the caller's allowed_agents. (The first is the UseTool permit on
// Tool::"invoke_agent" above.)
@id("permit_invoke_agent")
permit(principal, action == Action::"InvokeAgent", resource)
when { resource in principal.allowed_agents };

// --- cross-cloud preconditions: DEFERRED, NOT enforced by Cedar -------------
// Cross-cloud sequence enforcement (`cross_cloud_dependencies` → a required
// prior tool call) stays entirely in `context_validator` (a separate pipeline
// stage), exactly as in the legacy engine — `policy_engine` never enforced it
// either, so omitting it here PRESERVES parity. Moving the "Cedar decides,
// pipeline computes" model (feature §5) into Cedar requires threading
// context_validator's computed precondition state into CedarPolicyEngine +
// CedarContext; that is a future enhancement and is intentionally absent here.
// (Earlier drafts had a `forbid_cross_cloud_precondition` rule fed by a
// `requires_precondition` Tool attribute, but the synthesizer keyed off a
// `cross_cloud_dependencies[].tool` field that does NOT exist in the real data
// shape — `required_before`/`target_agent`/`target_tool` — so the rule was dead
// code. Removed rather than left implying enforcement that never fired.)
