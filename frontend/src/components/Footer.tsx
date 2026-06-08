const SOCIAL_LINKS = [
  { icon: 'ti-brand-twitter', href: '#', label: 'Twitter' },
  { icon: 'ti-brand-github', href: '#', label: 'GitHub' },
  { icon: 'ti-brand-linkedin', href: '#', label: 'LinkedIn' },
] as const

export default function Footer() {
  return (
    <footer className="bg-bg-primary border-t border-white/5 py-12 px-5 sm:px-8 lg:px-12">
      <div className="max-w-6xl mx-auto">
        <div className="flex flex-col sm:flex-row items-start sm:justify-between gap-8 mb-8">
          <div>
            {/* Logo */}
            <div className="flex items-center gap-2 mb-4">
              <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-cyan to-purple flex items-center justify-center">
                <i className="ti ti-shield-check text-white text-sm" />
              </div>
              <span className="font-heading text-white font-bold text-lg">
                Aegion<span className="text-cyan">AI</span>
              </span>
            </div>

            {/* Contact info */}
            <div className="space-y-2 mt-4">
              <div className="flex items-center gap-2">
                <i className="ti ti-mail text-muted text-sm" />
                <a
                  href="mailto:info@aegionai.ai"
                  className="font-body text-sm text-muted hover:text-white transition-colors"
                >
                  info@aegionai.ai
                </a>
              </div>
            </div>
          </div>

          {/* Social links */}
          <div className="flex items-center gap-5">
            {SOCIAL_LINKS.map((link) => (
              <a
                key={link.label}
                href={link.href}
                aria-label={link.label}
                className="w-9 h-9 rounded-lg bg-white/[0.04] border border-white/10 flex items-center justify-center hover:border-cyan/30 transition-colors"
              >
                <i className={`ti ${link.icon} text-muted text-base`} />
              </a>
            ))}
          </div>
        </div>

        {/* Bottom bar */}
        <div className="flex flex-col sm:flex-row items-start sm:items-center sm:justify-between gap-4 pt-8 border-t border-white/5">
          <p className="font-body text-sm text-muted">© 2026 AegionAI. All rights reserved.</p>
          <div className="flex flex-wrap items-center gap-4 sm:gap-6">
            <a href="#" className="font-body text-sm text-muted hover:text-white transition-colors">
              Privacy Policy
            </a>
            <a href="#" className="font-body text-sm text-muted hover:text-white transition-colors">
              Terms of Service
            </a>
            <div className="flex items-center gap-1.5">
              <i className="ti ti-shield-check text-cyan text-sm" />
              <span className="font-body text-xs text-muted">Patent Pending</span>
            </div>
          </div>
        </div>
      </div>
    </footer>
  )
}
