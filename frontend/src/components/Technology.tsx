const TECH_CARDS = [
  {
    icon: 'ti-plug-connected',
    title: 'Drop-in Interception',
    color: 'cyan',
    description: 'Intercept every agent action before it executes — a one-line SDK decorator per tool, or a drop-in connector for AWS Bedrock and Azure Foundry. A zero-code network sidecar is on the roadmap for in-VPC and air-gapped deployments.',
    tags: ['One-line SDK', 'Bedrock + Azure connectors', 'Network sidecar — roadmap'],
  },
  {
    icon: 'ti-file-code',
    title: 'Stateful Policy Engine',
    color: 'purple',
    description: 'Policies authored in YAML/JSON and compiled to Cedar. Beyond stateless allow/deny, AegionAI enforces parameter bounds and action sequences — ensuring required steps happen in the right order, across an agent\'s whole session.',
    tags: ['Cedar policy engine', 'Session-aware', 'No vendor lock-in'],
  },
  {
    icon: 'ti-brain',
    title: 'ML Detection Layer',
    color: 'green',
    description: 'Prompt-injection and jailbreak detection via an LLM classifier, backed by a distilled model (MiniLM + logistic head) trained on production-verified verdicts. Deterministic Sigma signatures enforce today; the ML tier runs in shadow until a precision/recall gate graduates it.',
    tags: ['Sigma signatures — live', 'Distilled ML classifier', 'Shadow before enforce'],
  },
  {
    icon: 'ti-shield-off',
    title: 'Blast Radius Containment',
    color: 'amber',
    description: 'When an agent\'s trust degrades, AegionAI quarantines it and auto-rejects all flows touching quarantined agents. Per-agent quarantine and cross-agent filtering are live today; cross-cloud, topology-aware containment is on the roadmap.',
    tags: ['Trust-driven quarantine', 'Cross-agent filtering', 'Cross-cloud — roadmap'],
  },
] as const

const INSPECTS = [
  { title: 'Policy compliance (YAML/JSON → Cedar)', desc: 'Open-source Cedar policies you define and own' },
  { title: 'Action parameters & sequence integrity', desc: 'Parameter bounds + required step-order, per session' },
  { title: 'Agent identity & authorization', desc: 'Verified per-agent credential — never a self-asserted field' },
  { title: 'Prompt injection & jailbreak patterns', desc: 'Sigma signatures (live) + LLM/distilled classifier' },
  { title: 'Accumulated trust & abuse signals', desc: 'Trust decay, rate/abuse limits, cross-agent filtering' },
  { title: 'PII and sensitive data', desc: 'Detection & redaction — roadmap' },
] as const

const ACTIONS = [
  'Block unauthorized actions before execution',
  'Quarantine agents when trust degrades',
  'Auto-reject all flows touching quarantined agents',
  'Name the deciding layer on every verdict',
  'Roll back actions where they\'re reversible',
  'Record decision, reason & source for audit',
] as const

const CLOUDS = [
  { name: 'AWS', sub: 'Bedrock', borderColor: 'border-[#ff9900]/20' },
  { name: 'Azure', sub: 'Foundry', borderColor: 'border-[#0078d4]/20' },
  { name: 'GCP', sub: 'Vertex AI — roadmap', borderColor: 'border-[#4285f4]/20' },
] as const

export default function Technology() {
  return (
    <section id="technology" className="bg-bg-primary py-16 sm:py-24 px-5 sm:px-8 lg:px-12 border-t border-white/5">
      <div className="max-w-6xl mx-auto">
        {/* Header */}
        <div className="text-center mb-12 sm:mb-16">
          <span className="font-body text-sm font-medium tracking-widest uppercase text-purple">
            Technology
          </span>
          <h2 className="font-heading text-3xl sm:text-4xl font-bold text-white mt-4">
            Built for the Agentic Era
          </h2>
          <p className="font-body text-muted mt-4 max-w-2xl mx-auto">
            A neutral control-plane architecture built from the ground up for cross-cloud AI-agent governance.
          </p>
        </div>

        {/* Tech Cards */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 sm:gap-8 mb-12">
          {TECH_CARDS.map((card) => (
            <div
              key={card.title}
              className={`p-8 rounded-2xl bg-white/[0.02] border border-white/5 hover:border-${card.color}/20 transition-colors`}
            >
              <div className="flex items-center gap-3 mb-5">
                <div className={`w-10 h-10 rounded-xl bg-${card.color}/10 border border-${card.color}/20 flex items-center justify-center`}>
                  <i className={`ti ${card.icon} text-${card.color} text-xl`} />
                </div>
                <h3 className="font-heading text-lg font-bold text-white">{card.title}</h3>
              </div>
              <p className="font-body text-sm text-muted leading-relaxed mb-4">{card.description}</p>
              <div className="flex flex-wrap gap-2">
                {card.tags.map((tag) => (
                  <span
                    key={tag}
                    className={`px-2.5 py-1 rounded-md bg-${card.color}/5 border border-${card.color}/10 font-body text-[10px] text-${card.color}`}
                  >
                    {tag}
                  </span>
                ))}
              </div>
            </div>
          ))}
        </div>

        {/* Inspects / Does */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 sm:gap-8">
          <div className="p-8 rounded-2xl bg-white/[0.02] border border-white/5">
            <h3 className="font-heading text-lg font-bold text-white mb-6 flex items-center gap-2">
              <i className="ti ti-scan text-cyan text-xl" /> What AegionAI Inspects
            </h3>
            <div className="space-y-4">
              {INSPECTS.map((item) => (
                <div key={item.title} className="flex items-start gap-3">
                  <div className="w-6 h-6 rounded-md bg-cyan/10 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <i className="ti ti-check text-cyan text-xs" />
                  </div>
                  <div>
                    <p className="font-body text-sm text-white">{item.title}</p>
                    <p className="font-body text-xs text-muted">{item.desc}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="p-8 rounded-2xl bg-white/[0.02] border border-white/5">
            <h3 className="font-heading text-lg font-bold text-white mb-6 flex items-center gap-2">
              <i className="ti ti-bolt text-purple text-xl" /> What AegionAI Does
            </h3>
            <div className="space-y-4">
              {ACTIONS.map((action) => (
                <div key={action} className="flex items-start gap-3">
                  <div className="w-6 h-6 rounded-md bg-purple/10 flex items-center justify-center flex-shrink-0 mt-0.5">
                    <i className="ti ti-x text-purple text-xs" />
                  </div>
                  <p className="font-body text-sm text-white">{action}</p>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Cloud Support */}
        <div className="mt-16 text-center">
          <p className="font-body text-sm text-muted mb-6">
            Works with any agent framework — via SDK decorator or connector
          </p>
          <div className="flex flex-wrap items-center justify-center gap-4 sm:gap-5">
            {CLOUDS.map((cloud) => (
              <div
                key={cloud.name}
                className={`px-6 sm:px-8 py-5 rounded-xl bg-white/[0.03] ${cloud.borderColor} border text-center min-w-[120px] sm:min-w-[140px]`}
              >
                <p className="font-heading text-base font-semibold text-white">{cloud.name}</p>
                <p className="font-body text-[11px] text-muted">{cloud.sub}</p>
              </div>
            ))}
            <div className="px-6 sm:px-8 py-5 rounded-xl bg-transparent border-2 border-dashed border-muted/30 text-center min-w-[120px] sm:min-w-[140px] group hover:border-cyan/30 transition-colors">
              <div className="flex items-center justify-center gap-2">
                <i className="ti ti-plus text-muted group-hover:text-cyan transition-colors" />
                <p className="font-heading text-base font-semibold text-muted group-hover:text-white transition-colors">
                  Any Cloud
                </p>
              </div>
              <p className="font-body text-[11px] text-muted">Easy Integration</p>
            </div>
          </div>
          <p className="font-body text-xs text-muted/60 mt-4">
            Compatible with LangChain · CrewAI · AutoGen · and any MCP-compatible framework
          </p>
        </div>
      </div>
    </section>
  )
}
