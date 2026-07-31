const INDICATORS = [
  { color: 'bg-green', label: 'Continuously learning' },
  { color: 'bg-cyan', label: 'Fewer false positives over time' },
  { color: 'bg-purple', label: 'Novel pattern detection' },
] as const

export default function Intelligence() {
  return (
    <section className="bg-bg-primary py-16 sm:py-24 px-5 sm:px-8 lg:px-12">
      <div className="max-w-4xl mx-auto">
        <div className="relative p-6 sm:p-12 rounded-2xl overflow-hidden">
          {/* Gradient border effect */}
          <div className="absolute inset-0 rounded-2xl bg-gradient-to-r from-cyan/30 via-purple/30 to-cyan/30 p-px">
            <div className="w-full h-full rounded-2xl bg-bg-primary" />
          </div>

          {/* Scan line animation */}
          <div className="absolute inset-0 overflow-hidden rounded-2xl pointer-events-none">
            <div className="absolute top-0 left-0 w-1/3 h-full bg-gradient-to-r from-transparent via-cyan/5 to-transparent animate-scan-line" />
          </div>

          {/* Content */}
          <div className="relative z-10 text-center">
            {/* Pulsing icon */}
            <div className="relative w-20 h-20 mx-auto mb-8">
              <div className="absolute inset-0 rounded-full bg-cyan/20 animate-pulse-ring" />
              <div className="absolute inset-0 rounded-full bg-cyan/15 animate-pulse-ring-delayed" />
              <div className="w-20 h-20 rounded-full bg-cyan/10 border border-cyan/30 flex items-center justify-center">
                <i className="ti ti-brain text-cyan text-3xl" />
              </div>
            </div>

            <h2 className="font-heading text-2xl sm:text-3xl font-bold text-white mb-4">
              Security Intelligence That Grows With You
            </h2>
            <p className="font-body text-muted max-w-2xl mx-auto leading-relaxed mb-6">
              De-identified signals from across the fleet train our detection models — a cross-vendor
              flywheel where every deployment sharpens protection for the rest. New models are validated
              in shadow before they ever enforce, so precision improves without new false positives.
            </p>

            <div className="flex flex-col sm:flex-row items-center justify-center gap-3 sm:gap-6">
              {INDICATORS.map((item) => (
                <div key={item.label} className="flex items-center gap-2">
                  <div className={`w-2 h-2 rounded-full ${item.color}`} />
                  <span className="font-body text-xs text-muted">{item.label}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
