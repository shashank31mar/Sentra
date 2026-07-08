import { Suspense, type ReactNode } from 'react'
import { createBrowserRouter } from 'react-router-dom'
import { ROUTES } from './routes'
import { AppLayout } from './AppLayout'
import { PlatformLayout } from './PlatformLayout'
import { RequirePlatform } from './RequirePlatform'
import { RouteErrorBoundary } from './RouteErrorBoundary'
import { PlaceholderPage } from '../components/ui/PlaceholderPage'
import { LoadingState } from '../components/ui/states'
// Lazy page declarations live in a component-only module so this file keeps
// exporting only `router` (eslint react-refresh/only-export-components).
import {
  OverviewPage,
  ThreatsPage,
  AgentInventoryPage,
  AgentDetailPage,
  TopologyPage,
  ImportAgentsPage,
  ConnectAccountPage,
  PolicyLibraryPage,
  PolicyDetailPage,
  PolicyEditorPage,
  QuarantinePage,
  ResidualAgentsPage,
  AuditTrailPage,
  FleetOverviewPage,
  TenantDetailPage,
  FleetTopologyPage,
  SystemHealthPage,
} from './lazyPages'

/** Wrap a lazy page in a Suspense fallback so the shell paints while its chunk
 *  loads. One helper keeps every route consistent. */
const withSuspense = (node: ReactNode) => (
  <Suspense fallback={<LoadingState label="Loading…" />}>{node}</Suspense>
)

export const router = createBrowserRouter([
  {
    element: <AppLayout />,
    errorElement: <RouteErrorBoundary />,
    children: [
      { path: ROUTES.overview, element: withSuspense(<OverviewPage />) },
      // /overview alias — the public splash (served at `/` by nginx) links here
      // so the operator enters the authenticated console (LLD-26 WS-C). `/` itself
      // is the splash, so this alias is the in-app home target.
      { path: '/overview', element: withSuspense(<OverviewPage />) },
      { path: ROUTES.threats, element: withSuspense(<ThreatsPage />) },
      { path: ROUTES.deployments, element: <PlaceholderPage title="Deployments" /> },
      { path: ROUTES.agents, element: withSuspense(<AgentInventoryPage />) },
      { path: ROUTES.agentDetail, element: withSuspense(<AgentDetailPage />) },
      { path: ROUTES.topology, element: withSuspense(<TopologyPage />) },
      { path: ROUTES.connect, element: withSuspense(<ConnectAccountPage />) },
      { path: ROUTES.import, element: withSuspense(<ImportAgentsPage />) },
      { path: ROUTES.deploy, element: <PlaceholderPage title="Deploy Agent" /> },
      { path: ROUTES.policies, element: withSuspense(<PolicyLibraryPage />) },
      // Static /policies/new MUST precede the /policies/:policyId param route.
      { path: ROUTES.policyNew, element: withSuspense(<PolicyEditorPage />) },
      { path: ROUTES.policyEdit, element: withSuspense(<PolicyEditorPage />) },
      { path: ROUTES.policyDetail, element: withSuspense(<PolicyDetailPage />) },
      { path: ROUTES.quarantine, element: withSuspense(<QuarantinePage />) },
      { path: ROUTES.residualAgents, element: withSuspense(<ResidualAgentsPage />) },
      { path: ROUTES.audit, element: withSuspense(<AuditTrailPage />) },
    ],
  },
  // Platform (cross-tenant) tree — a DISTINCT top-level route with its own layout,
  // gated at the router root on `is_platform` (G4.1). NOT nested under AppLayout
  // (that would render customer tenant chrome around a platform view). Static
  // routes precede the `:tenantId` param route.
  {
    path: ROUTES.platformOverview,
    element: (
      <RequirePlatform>
        <PlatformLayout />
      </RequirePlatform>
    ),
    errorElement: <RouteErrorBoundary />,
    children: [
      { index: true, element: withSuspense(<FleetOverviewPage />) },
      { path: ROUTES.platformTenants, element: withSuspense(<FleetOverviewPage />) },
      { path: ROUTES.platformTopology, element: withSuspense(<FleetTopologyPage />) },
      { path: ROUTES.platformHealth, element: withSuspense(<SystemHealthPage />) },
      { path: ROUTES.platformTenantDetail, element: withSuspense(<TenantDetailPage />) },
    ],
  },
])
