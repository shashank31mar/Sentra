const METRICS = [
  { label: 'Actions Blocked', value: '12.4K', color: 'text-cyan' },
  { label: 'Active Agents', value: '312', color: 'text-green' },
  { label: 'Quarantined', value: '7', color: 'text-amber' },
  { label: 'Cloud Vendors', value: '2', color: 'text-purple' },
] as const

const BAR_HEIGHTS = [40, 55, 45, 70, 60, 80, 75, 90, 65, 85, 70, 95] as const

export default function Dashboard() {
  return (
    <section className="bg-bg-primary py-16 sm:py-24 px-5 sm:px-8 lg:px-12 border-t border-white/5">
      <div className="max-w-5xl mx-auto text-center">
        <span className="font-body text-sm font-medium tracking-widest uppercase text-cyan">
          Visibility
        </span>
        <h2 className="font-heading text-3xl sm:text-4xl font-bold text-white mt-4 mb-4">
          One Dashboard. Every Cloud. Every Threat.
        </h2>
        <p className="font-body text-muted mb-10 sm:mb-12">
          Real-time visibility across your entire AI fleet. Trace any issue back to its source.
        </p>

        {/* Dashboard mockup */}
        <div className="p-6 rounded-2xl bg-white/[0.02] border border-white/10 max-w-4xl mx-auto">
          {/* Window chrome */}
          <div className="flex items-center gap-2 mb-5">
            <div className="w-3 h-3 rounded-full bg-red/50" />
            <div className="w-3 h-3 rounded-full bg-amber/50" />
            <div className="w-3 h-3 rounded-full bg-green/50" />
            <span className="font-body text-xs text-muted ml-3">
              AegionAI — Unified Security Dashboard (illustrative)
            </span>
          </div>

          {/* Metrics row */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
            {METRICS.map((metric) => (
              <div key={metric.label} className="p-3 rounded-lg bg-bg-primary border border-white/5">
                <p className="font-body text-[10px] text-muted">{metric.label}</p>
                <p className={`font-heading text-xl font-bold ${metric.color}`}>{metric.value}</p>
              </div>
            ))}
          </div>

          {/* Charts */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div className="sm:col-span-2 h-32 rounded-lg bg-bg-primary border border-white/5 p-3 flex flex-col">
              <p className="font-body text-[10px] text-muted mb-2">Threats Blocked Over Time</p>
              <div className="flex-1 flex items-end gap-1">
                {BAR_HEIGHTS.map((height, i) => (
                  <div
                    key={i}
                    className="flex-1 bg-cyan/20 rounded-t-sm"
                    style={{ height: `${height}%`, opacity: 0.2 + (i * 0.04) }}
                  />
                ))}
              </div>
            </div>
            <div className="h-32 rounded-lg bg-bg-primary border border-white/5 p-3 flex flex-col">
              <p className="font-body text-[10px] text-muted mb-2">Agent Topology</p>
              <div className="flex-1 flex items-center justify-center">
                <div className="relative">
                  <div className="w-8 h-8 rounded-full bg-cyan/20 border border-cyan/30 flex items-center justify-center">
                    <div className="w-3 h-3 rounded-full bg-cyan/60" />
                  </div>
                  <div className="absolute -top-3 -right-5 w-5 h-5 rounded-full bg-green/20 border border-green/30" />
                  <div className="absolute -bottom-2 -right-6 w-5 h-5 rounded-full bg-green/20 border border-green/30" />
                  <div className="absolute -top-1 -left-6 w-5 h-5 rounded-full bg-green/20 border border-green/30" />
                  <div className="absolute -bottom-3 -left-4 w-5 h-5 rounded-full bg-amber/20 border border-amber/30" />
                  <div className="absolute top-4 right-[-2rem] w-5 h-5 rounded-full bg-green/20 border border-green/30" />
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
