import type { AgentActivity, AgentStatus } from '../../types/enums'

/**
 * FX-1.4 — map the RAW ECS service status the server emits (`agent_service.py`) to
 * the canvas Active / Idle / Offline / Unknown activity label. The server never
 * returns the canvas enum; the old `AgentStatus` type LIED about the contract. This
 * is the single place that projection happens.
 *
 * Mapping:
 *   running + recent traffic   → Active
 *   running + NO recent traffic → Idle   (service is up but the agent is quiet)
 *   starting                   → Idle    (up-and-coming, not yet serving)
 *   stopped / not_found        → Offline
 *   'active' (leaked DynamoDB metadata) → Unknown (see below — NOT a live ECS state)
 *   unknown / anything else    → Unknown (NEVER shown as Active — fail honest)
 *
 * DynamoDB `status='active'` leak-through: the agent's registry metadata carries a
 * static `status='active'` (`agent_service.py:270/470/495`) that is normally
 * OVERWRITTEN by the live ECS probe (`agent_service.py:636`). But on a per-agent
 * enrichment EXCEPTION the un-enriched agent — still carrying `status='active'` — is
 * kept (`agent_service.py:229-231`), so a transient ECS-probe failure can surface
 * `'active'` to the client. `'active'` is registry metadata, NOT a live runtime
 * state: when it reaches us we do NOT actually know if the service is up, so it maps
 * to Unknown (fail honest) — a probe failure must never read as a live/busy agent.
 * Do NOT map `'active'` → Active.
 *
 * "Recent traffic" = a `last_seen`/`last_active` timestamp within `IDLE_AFTER_MS`
 * (default 15 min). A running service with no/stale traffic is Idle, not Active — a
 * dead-quiet agent must not read as busy.
 */

/** A running agent with no traffic newer than this reads as Idle (default 15 min). */
export const IDLE_AFTER_MS = 15 * 60_000

/** Colors for the derived activity label (design-system tokens mirrored). */
export const ACTIVITY_COLOR: Record<AgentActivity, string> = {
  Active: '#22E58B',
  Idle: '#FFB020',
  Offline: '#51636E',
  Unknown: '#8DA2AE',
}

function hasRecentTraffic(lastSeen: string | null | undefined, now: number): boolean {
  if (!lastSeen) return false
  const t = Date.parse(lastSeen)
  if (Number.isNaN(t)) return false
  return now - t <= IDLE_AFTER_MS
}

/**
 * Derive the canvas activity label from the raw ECS status + last-traffic timestamp.
 * `status` is typed as the real server contract; an unexpected value falls through
 * to Unknown (never Active) so a garbage/unknown status never reads as healthy.
 */
export function activityStatus(
  status: AgentStatus | string | null | undefined,
  lastSeen: string | null | undefined,
  now: number = Date.now(),
): AgentActivity {
  switch (status) {
    case 'running':
      return hasRecentTraffic(lastSeen, now) ? 'Active' : 'Idle'
    case 'starting':
      return 'Idle'
    case 'stopped':
    case 'not_found':
      return 'Offline'
    // Leaked DynamoDB registry metadata (agent_service.py:229-231 keeps the
    // un-enriched agent on an ECS-probe exception). NOT a live ECS state → Unknown,
    // never Active. Explicit case so it can't be silently promoted to Active later.
    case 'active':
    case 'unknown':
    default:
      return 'Unknown'
  }
}
