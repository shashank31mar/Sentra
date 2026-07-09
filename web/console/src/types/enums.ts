/**
 * Enum-like union types from LLD-21 §11.1.
 * Using string unions (not TS `enum`) per project guidelines.
 */

export type CloudProvider = 'aws' | 'gcp' | 'azure'

/** Connector axis — distinct from cloud_provider (LLD-21 §2 / §10.1). */
export type Platform = 'sentra' | 'bedrock' | 'azure_foundry'

/** LLD-21 §2: the console decision feed is ALLOW | DENY (REDACT is a /validate-only verdict). */
export type Decision = 'ALLOW' | 'DENY'

/** Discovery import mode (WS-21 D2). Default monitor. */
export type EnforcementMode = 'monitor' | 'enforce'

export type Risk = 'high' | 'med' | 'low'

export type TrustStatus = 'healthy' | 'degraded' | 'critical' | 'unknown'

/**
 * RAW ECS service status the server emits for an agent (`agent_service.py:636/666/
 * 680/691-696`) — NOT the canvas activity label. `running` = has ≥1 running task;
 * `starting` = desired but not yet running; `stopped` = 0 running; `not_found` = no
 * ECS service; `unknown` = the status probe failed. FX-1.4: the type must reflect
 * the real server contract; the canvas Active/Idle/Offline label is DERIVED from
 * this + recent traffic by `features/agents/activityStatus.ts` (never asserted as
 * if the server returned it).
 */
export type AgentStatus = 'running' | 'starting' | 'stopped' | 'not_found' | 'unknown'

/** The derived, canvas-facing activity label (FX-1.4). Mapped from `AgentStatus`
 *  + recent traffic — never a raw server value. */
export type AgentActivity = 'Active' | 'Idle' | 'Offline' | 'Unknown'

export type QuarantineStatus = 'active' | 'quarantined' | 'suspended'

/** Detected-agents lifecycle (feature §8.1). managed = validate data flowing. */
export type DiscoveryStatus = 'not_imported' | 'imported' | 'managed'

export type ScanStatus = 'scanning' | 'idle'

/** Cloud-account connection lifecycle (connections-api-spec §2). */
export type ConnectionStatus = 'connecting' | 'connected' | 'error' | 'disconnected'

/** Interception state for a managed agent (feature.md §8). UI label only in P0. */
export type InterceptionStatus = 'planned' | 'live' | 'none'

export type PolicyStatus = 'active' | 'disabled' | 'draft'

export type SigmaStatus = 'enabled' | 'disabled'

export type MetricsRange = '1h' | '24h' | '7d' | '30d'

export type TimeseriesBucket = '1h' | '1d'

/** Operator verdict on a past decision (LLD §12.3). */
export type Verdict =
  | 'false_positive'
  | 'confirmed_threat'
  | 'false_negative'
  | 'confirmed_safe'

export type Role = 'viewer' | 'operator' | 'admin'

/** Open threat-type set; common values surfaced, but treat as open string. */
export type ThreatType =
  | 'PROMPT_INJECTION'
  | 'POLICY_VIOLATION'
  | 'JAILBREAK'
  | 'DATA_EXFILTRATION'
  | 'PII_LEAK'
  | 'POLICY_DISABLED' // agent-policy-management T14: bound policy disabled → fail-secure DENY
  | (string & {})

/** Standard machine error codes (LLD §11.1). */
export type ErrorCode =
  | 'VALIDATION_ERROR'
  | 'UNAUTHENTICATED'
  | 'FORBIDDEN'
  | 'NOT_FOUND'
  | 'CONFLICT'
  | 'UNPROCESSABLE'
  | 'RATE_LIMITED'
  | 'DEPENDENCY_UNAVAILABLE'
  | (string & {})
