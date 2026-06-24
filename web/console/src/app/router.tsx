import { createBrowserRouter } from 'react-router-dom'
import { ROUTES } from './routes'
import { AppLayout } from './AppLayout'
import { RouteErrorBoundary } from './RouteErrorBoundary'
import { OverviewPage } from '../features/overview/OverviewPage'
import { ThreatsPage } from '../features/threats/ThreatsPage'
import { AgentInventoryPage } from '../features/agents/AgentInventoryPage'
import { AgentDetailPage } from '../features/agents/AgentDetailPage'
import { TopologyPage } from '../features/topology/TopologyPage'
import { ImportAgentsPage } from '../features/import/ImportAgentsPage'
import { ConnectAccountPage } from '../features/connect/ConnectAccountPage'
import { PolicyLibraryPage } from '../features/policies/PolicyLibraryPage'
import { PolicyDetailPage } from '../features/policies/PolicyDetailPage'
import { PolicyEditorPage } from '../features/policies/PolicyEditorPage'
import { QuarantinePage } from '../features/quarantine/QuarantinePage'
import { ResidualAgentsPage } from '../features/identity/ResidualAgentsPage'
import { AuditTrailPage } from '../features/audit/AuditTrailPage'
import { PlaceholderPage } from '../components/ui/PlaceholderPage'

export const router = createBrowserRouter([
  {
    element: <AppLayout />,
    errorElement: <RouteErrorBoundary />,
    children: [
      { path: ROUTES.overview, element: <OverviewPage /> },
      // /overview alias — the public splash (served at `/` by nginx) links here
      // so the operator enters the authenticated console (LLD-26 WS-C). `/` itself
      // is the splash, so this alias is the in-app home target.
      { path: '/overview', element: <OverviewPage /> },
      { path: ROUTES.threats, element: <ThreatsPage /> },
      { path: ROUTES.deployments, element: <PlaceholderPage title="Deployments" /> },
      { path: ROUTES.agents, element: <AgentInventoryPage /> },
      { path: ROUTES.agentDetail, element: <AgentDetailPage /> },
      { path: ROUTES.topology, element: <TopologyPage /> },
      { path: ROUTES.connect, element: <ConnectAccountPage /> },
      { path: ROUTES.import, element: <ImportAgentsPage /> },
      { path: ROUTES.deploy, element: <PlaceholderPage title="Deploy Agent" /> },
      { path: ROUTES.policies, element: <PolicyLibraryPage /> },
      // Static /policies/new MUST precede the /policies/:policyId param route.
      { path: ROUTES.policyNew, element: <PolicyEditorPage /> },
      { path: ROUTES.policyEdit, element: <PolicyEditorPage /> },
      { path: ROUTES.policyDetail, element: <PolicyDetailPage /> },
      { path: ROUTES.quarantine, element: <QuarantinePage /> },
      { path: ROUTES.residualAgents, element: <ResidualAgentsPage /> },
      { path: ROUTES.audit, element: <AuditTrailPage /> },
    ],
  },
])
