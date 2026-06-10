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

export type AgentStatus = 'active' | 'idle' | 'quarantined' | 'inactive'

export type QuarantineStatus = 'active' | 'quarantined' | 'suspended'

export type DiscoveryStatus = 'managed' | 'unmanaged'

export type ScanStatus = 'scanning' | 'idle'

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
