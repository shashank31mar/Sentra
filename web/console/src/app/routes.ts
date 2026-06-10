/** Central route path registry — reused by the router and the NavRail. */
export const ROUTES = {
  overview: '/',
  threats: '/threats',
  deployments: '/deployments',
  agents: '/agents',
  agentDetail: '/agents/:agentId',
  topology: '/topology',
  import: '/import',
  deploy: '/deploy',
  policies: '/policies',
  policyDetail: '/policies/:policyId',
  quarantine: '/quarantine',
  audit: '/audit',
} as const

export const agentDetailPath = (agentId: string) => `/agents/${agentId}`
export const policyDetailPath = (policyId: string) => `/policies/${encodeURIComponent(policyId)}`
