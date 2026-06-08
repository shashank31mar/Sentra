const TECH_CARDS = [
  {
    icon: 'ti-container',
    title: 'Kubernetes Sidecar',
    color: 'cyan',
    description: 'Deploys as an Istio-style sidecar proxy — intercepts all agent tool calls at the network level. No SDK changes. No code modifications. Framework-agnostic.',
    tags: ['Zero code changes', '< 1 sprint integration', '< 80ms latency'],
  },
  {
    icon: 'ti-file-code',
    title: 'Stateful Policy Engine',
    color: 'purple',
    description: 'Open-standard YAML/OPA policies with stateful session tracking. Unlike Cedar\'s stateless-by-design approach, AegionAI validates action sequences — ensuring required steps happen in order.',
    tags: ['YAML + OPA Rego', 'Session-aware', 'No vendor lock-in'],
  },
  {
    icon: 'ti-brain',
    title: 'ML Detection Layer',
    color: 'green',
    description: 'Fine-tuned transformer trained on HackAPrompt, JailbreakBench, and HarmBench datasets for prompt injection detection. Behavioral anomaly detection via Isolation Forest on tool call metadata — no content inspection required.',
    tags: ['94% precision', 'Adaptive learning', '< 2% false positives'],
  },
  {
    icon: 'ti-shield-off',
    title: 'Blast Radius Containment',
    color: 'amber',
    description: 'When one agent is compromised, AegionAI quarantines it instantly and auto-rejects all flows touching quarantined agents — preventing cross-cloud cascade attacks before they propagate.',
    tags: ['< 5s quarantine', 'Cross-cloud isolation', 'Topology-aware'],
  },
] as const

const INSPECTS = [
  { title: 'Policy compliance (YAML/OPA)', desc: 'Open-standard policies you define and own' },
  { title: 'Action sequence integrity', desc: 'Stateful step-order validation via Redis session cache' },
  { title: 'Agent identity claims', desc: 'Zero-trust agent verification' },
  { title: 'Prompt injection & jailbreak patterns', desc: 'Fine-tuned transformer classification' },
  { title: 'Behavioral anomalies', desc: 'Isolation Forest on metadata — no content inspection' },
  { title: 'PII and sensitive data', desc: '94% precision real-time detection & redaction' },
] as const

const ACTIONS = [
  'Block unauthorized actions before execution',
  'Quarantine compromised agents instantly',
  'Auto-reject all flows touching quarantined agents',
  'Contain blast radius across clouds',
  'Rollback to safe state',
  'Trace threat source across full agent topology',
] as const

const CLOUDS = [
  { name: 'AWS', sub: 'Bedrock', borderColor: 'border-[#ff9900]/20' },
  { name: 'Azure', sub: 'OpenAI', borderColor: 'border-[#0078d4]/20' },
  { name: 'GCP', sub: 'Vertex AI', borderColor: 'border-[#4285f4]/20' },
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
            Kubernetes-native architecture designed from the ground up for cross-cloud AI agent governance.
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
            Works with any agent framework — zero code changes required
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
