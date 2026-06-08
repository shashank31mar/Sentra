import { createBrowserRouter } from 'react-router-dom'
import { ROUTES } from './routes'
import { AppLayout } from './AppLayout'
import { RouteErrorBoundary } from './RouteErrorBoundary'
import { OverviewPage } from '../features/overview/OverviewPage'
import { ThreatsPage } from '../features/threats/ThreatsPage'
import { AgentInventoryPage } from '../features/agents/AgentInventoryPage'
import { AgentDetailPage } from '../features/agents/AgentDetailPage'
import { DiscoveryPage } from '../features/discovery/DiscoveryPage'
import { PolicyLibraryPage } from '../features/policies/PolicyLibraryPage'
import { AuditTrailPage } from '../features/audit/AuditTrailPage'
import { PlaceholderPage } from '../components/ui/PlaceholderPage'

export const router = createBrowserRouter([
  {
    element: <AppLayout />,
    errorElement: <RouteErrorBoundary />,
    children: [
      { path: ROUTES.overview, element: <OverviewPage /> },
      { path: ROUTES.threats, element: <ThreatsPage /> },
      { path: ROUTES.deployments, element: <PlaceholderPage title="Deployments" /> },
      { path: ROUTES.agents, element: <AgentInventoryPage /> },
      { path: ROUTES.agentDetail, element: <AgentDetailPage /> },
      { path: ROUTES.discovery, element: <DiscoveryPage /> },
      { path: ROUTES.import, element: <PlaceholderPage title="Import Agents" /> },
      { path: ROUTES.deploy, element: <PlaceholderPage title="Deploy Agent" /> },
      { path: ROUTES.policies, element: <PolicyLibraryPage /> },
      { path: ROUTES.audit, element: <AuditTrailPage /> },
    ],
  },
])
