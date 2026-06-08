export default function Compliance() {
  return (
    <section className="bg-bg-primary py-12 px-5 sm:px-8 lg:px-12">
      <div className="max-w-4xl mx-auto">
        <div className="p-6 sm:p-8 rounded-2xl bg-gradient-to-r from-purple/5 to-cyan/5 border border-purple/15">
          <div className="flex items-start gap-4">
            <div className="w-12 h-12 rounded-xl bg-purple/10 border border-purple/20 flex items-center justify-center flex-shrink-0">
              <i className="ti ti-gavel text-purple text-xl" />
            </div>
            <div>
              <h3 className="font-heading text-xl font-bold text-white mb-2">
                EU AI Act — Enforcement Is Underway
              </h3>
              <div className="space-y-2">
                <p className="font-body text-sm text-muted">
                  <span className="text-green font-medium">✓ Aug 2025:</span> GPAI governance &
                  transparency obligations in effect. National authorities designated. Penalties active.
                </p>
                <p className="font-body text-sm text-muted">
                  <span className="text-amber font-medium">→ Aug 2026:</span> Full high-risk AI system
                  obligations apply. All AI agents in finance, HR, healthcare, and critical infrastructure
                  in scope.
                </p>
                <p className="font-body text-sm text-muted">
                  <span className="text-red font-medium">Fines:</span> Up to 7% of global annual
                  revenue or €35M — whichever is higher.
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}
