import { lazy } from 'react'

// Route-level code-splitting lives here (not in router.tsx) so router.tsx keeps
// exporting only the non-component `router` — co-locating these component
// declarations with that export trips eslint's react-refresh/only-export-
// components rule. Each feature page becomes its own lazy chunk, so first load
// pulls the shell + landed route instead of the old ~645 KB monolith (see the
// captured HAR that showed ~28 s on index-*.js). Static imports would defeat
// the split, so every page is lazy().
export const OverviewPage = lazy(() =>
  import('../features/overview/OverviewPage').then((m) => ({ default: m.OverviewPage })),
)
export const ThreatsPage = lazy(() =>
  import('../features/threats/ThreatsPage').then((m) => ({ default: m.ThreatsPage })),
)
export const AgentInventoryPage = lazy(() =>
  import('../features/agents/AgentInventoryPage').then((m) => ({ default: m.AgentInventoryPage })),
)
export const AgentDetailPage = lazy(() =>
  import('../features/agents/AgentDetailPage').then((m) => ({ default: m.AgentDetailPage })),
)
export const TopologyPage = lazy(() =>
  import('../features/topology/TopologyPage').then((m) => ({ default: m.TopologyPage })),
)
export const ImportAgentsPage = lazy(() =>
  import('../features/import/ImportAgentsPage').then((m) => ({ default: m.ImportAgentsPage })),
)
export const ConnectAccountPage = lazy(() =>
  import('../features/connect/ConnectAccountPage').then((m) => ({ default: m.ConnectAccountPage })),
)
export const PolicyLibraryPage = lazy(() =>
  import('../features/policies/PolicyLibraryPage').then((m) => ({ default: m.PolicyLibraryPage })),
)
export const PolicyDetailPage = lazy(() =>
  import('../features/policies/PolicyDetailPage').then((m) => ({ default: m.PolicyDetailPage })),
)
export const PolicyEditorPage = lazy(() =>
  import('../features/policies/PolicyEditorPage').then((m) => ({ default: m.PolicyEditorPage })),
)
export const QuarantinePage = lazy(() =>
  import('../features/quarantine/QuarantinePage').then((m) => ({ default: m.QuarantinePage })),
)
export const ResidualAgentsPage = lazy(() =>
  import('../features/identity/ResidualAgentsPage').then((m) => ({ default: m.ResidualAgentsPage })),
)
export const AuditTrailPage = lazy(() =>
  import('../features/audit/AuditTrailPage').then((m) => ({ default: m.AuditTrailPage })),
)
