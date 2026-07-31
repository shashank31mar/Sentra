import { useCallback } from 'react'

const FLEET_STATS = [
  { icon: 'ti-shield-check', color: 'text-green', label: 'Actions Blocked', value: '2,847' },
  { icon: 'ti-robot', color: 'text-cyan', label: 'Agents Governed', value: '156' },
  { icon: 'ti-cloud', color: 'text-purple', label: 'Cloud Vendors', value: '2' },
  { icon: 'ti-alert-triangle', color: 'text-amber', label: 'Agents Quarantined', value: '3' },
] as const

export default function Hero() {
  const scrollTo = useCallback((id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  return (
    <section className="relative overflow-hidden bg-bg-primary min-h-screen flex items-center justify-center">
      {/* Background video */}
      <video
        className="absolute inset-0 w-full h-full object-cover opacity-25"
        src="https://videos.pexels.com/video-files/3129671/3129671-sd_426_240_30fps.mp4"
        poster="https://images.pexels.com/videos/3129671/free-video-3129671.jpg?auto=compress&cs=tinysrgb&fit=crop&h=630&w=1200"
        autoPlay
        muted
        loop
        playsInline
        preload="metadata"
      />

      {/* Overlays */}
      <div className="absolute inset-0 bg-gradient-to-b from-bg-primary/70 via-transparent to-bg-primary" />
      <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[900px] h-[900px] max-w-[140vw] max-h-[140vw] rounded-full bg-cyan/4 blur-[140px]" />

      {/* Content */}
      <div className="relative z-10 max-w-7xl mx-auto px-5 sm:px-8 lg:px-12 flex flex-col lg:flex-row items-center gap-10 lg:gap-16 w-full pt-28 pb-16 lg:py-20">
        <div className="flex-1 text-center lg:text-left">
          {/* Badge */}
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full border border-cyan/20 bg-cyan/5 mb-6">
            <i className="ti ti-sparkles text-cyan text-sm" />
            <span className="font-body text-xs sm:text-sm text-muted">
              Setting the standard for AI-agent security
            </span>
          </div>

          {/* Headline */}
          <h1 className="font-heading text-[2rem] sm:text-5xl lg:text-[3.5rem] font-bold text-white leading-[1.1] mb-5">
            Govern What Your<br />
            Agents Actually Do.<br />
            <span className="text-cyan drop-shadow-[0_0_20px_rgba(0,240,255,0.3)]">
              Not Just What They Say.
            </span>
          </h1>

          {/* Description */}
          <p className="font-body text-base sm:text-lg text-muted max-w-lg mx-auto lg:mx-0 leading-relaxed mb-8">
            Most tools check whether a tool is allowed. AegionAI governs
            <span className="text-white font-medium"> what the action actually does</span> —
            its parameters, the agent's identity, the required sequence, its
            session and trust state — and blocks the harmful one in real time.
            Neutral across AWS, Azure, and on-prem: the standard no single cloud can set.
          </p>

          {/* CTAs */}
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-center lg:justify-start gap-4">
            <button
              type="button"
              onClick={() => scrollTo('technology')}
              className="group px-7 py-3.5 rounded-lg bg-gradient-to-r from-cyan to-cyan/80 font-body text-sm font-semibold text-bg-primary flex items-center justify-center gap-2 hover:shadow-[0_0_30px_rgba(0,240,255,0.3)] transition-all cursor-pointer border-none"
            >
              See How It Works
              <i className="ti ti-arrow-right text-base group-hover:translate-x-0.5 transition-transform" />
            </button>
            <button
              type="button"
              onClick={() => scrollTo('demo')}
              className="px-7 py-3.5 rounded-lg border border-muted/30 font-body text-sm font-medium text-white hover:border-cyan/50 transition-all cursor-pointer bg-transparent"
            >
              Book a Demo
            </button>
          </div>
        </div>

        {/* Fleet Status Card */}
        <div className="w-full max-w-[380px] lg:w-[380px] lg:flex-shrink-0">
          <div className="p-6 rounded-2xl bg-white/[0.03] border border-cyan/15 backdrop-blur-sm">
            <div className="flex items-center gap-2 mb-5">
              <div className="w-2 h-2 rounded-full bg-cyan/60" />
              <span className="font-body text-xs text-muted">Fleet dashboard — illustrative</span>
            </div>
            <div className="space-y-4">
              {FLEET_STATS.map((stat) => (
                <div
                  key={stat.label}
                  className="flex items-center justify-between p-3 rounded-lg bg-bg-primary/60 border border-white/5"
                >
                  <div className="flex items-center gap-2">
                    <i className={`ti ${stat.icon} ${stat.color} text-base`} />
                    <span className="font-body text-xs text-muted">{stat.label}</span>
                  </div>
                  <span className="font-heading text-lg font-bold text-white">{stat.value}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
