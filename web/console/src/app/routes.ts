/** Central route path registry — reused by the router and the NavRail. */
export const ROUTES = {
  overview: '/',
  threats: '/threats',
  deployments: '/deployments',
  agents: '/agents',
  agentDetail: '/agents/:agentId',
  topology: '/topology',
  connect: '/connect',
  import: '/import',
  deploy: '/deploy',
  policies: '/policies',
  policyNew: '/policies/new',
  policyEdit: '/policies/:policyId/edit',
  policyDetail: '/policies/:policyId',
  quarantine: '/quarantine',
  residualAgents: '/identity/residual-agents',
  audit: '/audit',
  // M-G3.0 — new/promoted customer views.
  activity: '/activity',
  // Decision detail keys on the COMPOSITE PK {session_id}#{request_id} — never
  // :requestId alone (routes.py:554), so both params are in the path.
  decisionDetail: '/decisions/:sessionId/:requestId',
  sessionDetail: '/sessions/:sessionId',
  usage: '/usage',
  // Platform (cross-tenant) console — a separate is_platform-gated tree (M-G4).
  platformOverview: '/platform',
  platformTenants: '/platform/tenants',
  platformTenantDetail: '/platform/tenants/:tenantId',
  platformTopology: '/platform/topology',
  platformHealth: '/platform/health',
} as const

export const agentDetailPath = (agentId: string) => `/agents/${agentId}`
/** Import review scoped to a just-connected cloud account. */
export const importPath = (connectionId?: string) =>
  connectionId ? `/import?connection=${encodeURIComponent(connectionId)}` : '/import'
export const policyDetailPath = (policyId: string) => `/policies/${encodeURIComponent(policyId)}`
export const policyNewPath = () => '/policies/new'
export const policyEditPath = (policyId: string) => `/policies/${encodeURIComponent(policyId)}/edit`
export const platformTenantDetailPath = (tenantId: string) =>
  `/platform/tenants/${encodeURIComponent(tenantId)}`
// Decision detail needs BOTH ids (composite PK) — encode each segment.
export const decisionDetailPath = (sessionId: string, requestId: string) =>
  `/decisions/${encodeURIComponent(sessionId)}/${encodeURIComponent(requestId)}`
export const sessionDetailPath = (sessionId: string) =>
  `/sessions/${encodeURIComponent(sessionId)}`
export const usagePath = () => '/usage'
