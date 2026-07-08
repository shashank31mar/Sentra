import { IconSitemap } from '@tabler/icons-react'
import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'

/**
 * Fleet Topology (G4.7 — ROADMAP). No `GET /v1/topology` route exists, so this page
 * makes ZERO network calls and renders a roadmap badge + explicit "sample data"
 * marker. A live fetch to a nonexistent route would surface a spurious 404 error.
 */
export function FleetTopologyPage() {
  return (
    <div className="p-4 sm:p-6 lg:p-8">
      <PageHeader
        title="Fleet Topology"
        subtitle="Cross-tenant cloud → agent → tool flow."
        actions={
          <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded font-mono text-amber" style={{ background: 'rgba(255,176,32,0.12)', border: '1px solid rgba(255,176,32,0.3)' }}>
            Roadmap
          </span>
        }
      />
      <Card className="p-10 flex flex-col items-center gap-3 text-center">
        <IconSitemap size={30} className="text-faint" />
        <h2 className="font-display text-lg font-bold text-white">Fleet topology is on the roadmap</h2>
        <p className="text-sm text-secondary max-w-md">
          A cross-tenant topology view lands with the fleet-topology backend. This screen makes no live
          reads until then.
        </p>
        <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-amber">Sample data — not live</span>
      </Card>
    </div>
  )
}
