const PILLARS = [
  {
    icon: 'ti-arrow-badge-right',
    title: 'Intercept',
    description: 'Every agent action — tool calls, API requests, inter-agent messages — passes through our inline sidecar before execution.',
    color: 'cyan',
    highlighted: false,
    badge: null,
  },
  {
    icon: 'ti-layers-intersect',
    title: 'Validate',
    description: 'Multi-layer deep inspection — policy compliance, step-sequence integrity, identity verification, ML threat classification, and behavioral analysis.',
    color: 'cyan',
    highlighted: true,
    badge: 'Layered Defense Architecture',
  },
  {
    icon: 'ti-lock-check',
    title: 'Enforce',
    description: 'Block, quarantine, contain, or rollback — automatically. Compromised agents are isolated in seconds, across any cloud.',
    color: 'purple',
    highlighted: false,
    badge: null,
  },
] as const

const INCIDENTS = [
  {
    tag: 'Supply Chain · 2026',
    description: '1,184 malicious packages found in OpenClaw marketplace. 21,000+ agent deployments exposed before containment.',
    gap: 'No cross-agent blast radius containment.',
    source: { label: 'SecurityWeek', url: 'https://www.securityweek.com/openclaw-vulnerability-allowed-malicious-websites-to-hijack-ai-agents/' },
  },
  {
    tag: 'Blast Radius · March 2026',
    description: 'Amazon SVP calls mandatory all-hands after four "high blast radius" incidents in one week — all from unsupervised GenAI changes.',
    gap: 'No automated governance — manual sign-off bolted on after the fact.',
    source: null,
  },
  {
    tag: 'Cascade Breach · Aug 2025',
    description: 'One compromised AI chatbot credential breaches 700+ companies simultaneously — including Palo Alto Networks and Cloudflare.',
    gap: 'No cross-cloud containment between agents.',
    source: { label: 'Trend Micro', url: 'https://www.trendmicro.com/en_us/research/25/i/ai-app-breach.html' },
  },
] as const

export default function About() {
  return (
    <section id="about" className="bg-bg-primary py-16 sm:py-24 px-5 sm:px-8 lg:px-12 border-t border-white/5">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="text-center mb-12 sm:mb-16">
          <span className="font-body text-sm font-medium tracking-widest uppercase text-cyan">
            What We Do
          </span>
          <h2 className="font-heading text-3xl sm:text-4xl font-bold text-white mt-4 mb-5">
            The AI Security Control Plane
          </h2>
          <p className="font-body text-base sm:text-lg text-muted max-w-3xl mx-auto leading-relaxed">
            AegionAI is to AI agents what Kubernetes is to containers. We sit between your AI agents
            and the systems they interact with — intercepting, validating, and enforcing every action
            before it executes. One governance layer. Every cloud. Every agent.
          </p>
        </div>

        {/* Pillars */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6 sm:gap-8 mb-16 sm:mb-20">
          {PILLARS.map((pillar) => (
            <div
              key={pillar.title}
              className={`relative p-8 rounded-2xl text-center transition-all ${
                pillar.highlighted
                  ? 'bg-cyan/[0.03] border-2 border-cyan/30 shadow-[0_0_40px_rgba(0,240,255,0.05)]'
                  : `bg-white/[0.02] border border-${pillar.color}/15 hover:border-${pillar.color}/30`
              }`}
            >
              <div
                className={`w-16 h-16 rounded-2xl bg-${pillar.color}/10 border border-${pillar.color}/20 flex items-center justify-center mx-auto mb-6`}
              >
                <i className={`ti ${pillar.icon} text-${pillar.color} text-3xl`} />
              </div>
              <h3 className="font-heading text-xl font-bold text-white mb-3">{pillar.title}</h3>
              <p className="font-body text-sm text-muted leading-relaxed">{pillar.description}</p>
              {pillar.badge && (
                <div className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-cyan/5 border border-cyan/15 mt-4">
                  <i className="ti ti-stack-2 text-cyan text-xs" />
                  <span className="font-body text-[10px] text-cyan font-medium">{pillar.badge}</span>
                </div>
              )}
            </div>
          ))}
        </div>

        {/* Incidents */}
        <div className="mb-6">
          <div className="text-center mb-10 sm:mb-12">
            <span className="font-body text-sm font-medium tracking-widest uppercase text-red/80">
              Why This Matters
            </span>
            <h3 className="font-heading text-2xl sm:text-3xl font-bold text-white mt-4">
              Every Incident. Same Root Cause.
            </h3>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-8">
            {INCIDENTS.map((incident) => (
              <div
                key={incident.tag}
                className="p-6 rounded-xl bg-white/[0.02] border-l-2 border-l-red/60 border border-white/5"
              >
                <div className="flex items-center gap-2 mb-3">
                  <i className="ti ti-alert-circle text-red text-base" />
                  <span className="font-body text-[10px] uppercase tracking-wider text-red/70">
                    {incident.tag}
                  </span>
                </div>
                <p className="font-body text-sm text-white/90 leading-relaxed">
                  {incident.description}
                </p>
                <p className="font-body text-xs text-muted mt-3">{incident.gap}</p>
                {incident.source && (
                  <a
                    href={incident.source.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 font-body text-[10px] text-red/60 hover:text-red mt-2 transition-colors"
                  >
                    <i className="ti ti-external-link text-[10px]" />
                    {incident.source.label}
                  </a>
                )}
              </div>
            ))}
          </div>

          <div className="text-center">
            <p className="font-body text-base text-muted">
              It's not the AI that failed. It's the{' '}
              <span className="text-white font-medium">missing governance layer</span>.
            </p>
          </div>
        </div>
      </div>
    </section>
  )
}
