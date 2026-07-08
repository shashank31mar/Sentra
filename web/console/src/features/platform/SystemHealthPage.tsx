import { IconActivityHeartbeat } from '@tabler/icons-react'
import { Card } from '../../components/ui/Card'
import { PageHeader } from '../../components/ui/PageHeader'

/**
 * System Health (G4.7 — ROADMAP). No per-region health route exists (only a scalar
 * `avg_latency_ms`); this page makes ZERO network calls and does NOT fabricate a
 * per-region series from the scalar. Roadmap badge + "sample data" marker only.
 */
export function SystemHealthPage() {
  return (
    <div className="p-4 sm:p-6 lg:p-8">
      <PageHeader
        title="System Health"
        subtitle="Per-region control-plane health."
        actions={
          <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-1 rounded font-mono text-amber" style={{ background: 'rgba(255,176,32,0.12)', border: '1px solid rgba(255,176,32,0.3)' }}>
            Roadmap
          </span>
        }
      />
      <Card className="p-10 flex flex-col items-center gap-3 text-center">
        <IconActivityHeartbeat size={30} className="text-faint" />
        <h2 className="font-display text-lg font-bold text-white">Per-region health is on the roadmap</h2>
        <p className="text-sm text-secondary max-w-md">
          Region-level health lands with the health backend. This screen makes no live reads and does
          not fabricate a series from the single scalar latency metric.
        </p>
        <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-amber">Sample data — not live</span>
      </Card>
    </div>
  )
}
