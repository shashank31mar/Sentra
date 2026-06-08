/** Central route path registry — reused by the router and the NavRail. */
export const ROUTES = {
  overview: '/',
  threats: '/threats',
  deployments: '/deployments',
  agents: '/agents',
  agentDetail: '/agents/:agentId',
  discovery: '/discovery',
  import: '/import',
  deploy: '/deploy',
  policies: '/policies',
  audit: '/audit',
} as const

export const agentDetailPath = (agentId: string) => `/agents/${agentId}`
