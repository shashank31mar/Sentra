import { useCallback, useState } from 'react'

const NAV_LINKS = [
  { label: 'About', target: 'about' },
  { label: 'Technology', target: 'technology' },
  { label: 'Contact', target: 'contact' },
] as const

export default function Navbar() {
  const [open, setOpen] = useState(false)

  const scrollTo = useCallback((id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth' })
    setOpen(false)
  }, [])

  return (
    <nav className="fixed top-0 left-0 right-0 z-50 bg-bg-primary/80 backdrop-blur-md border-b border-white/5">
      <div className="flex items-center justify-between px-5 sm:px-8 lg:px-12 py-4 sm:py-5">
        <div className="flex items-center gap-2">
          <div className="w-9 h-9 rounded-lg bg-gradient-to-br from-cyan to-purple flex items-center justify-center">
            <i className="ti ti-shield-check text-white text-lg" />
          </div>
          <span className="font-heading text-white font-bold text-xl">
            Aegion<span className="text-cyan">AI</span>
          </span>
        </div>

        {/* Desktop nav */}
        <div className="hidden md:flex items-center gap-8">
          {NAV_LINKS.map((link) => (
            <button
              key={link.target}
              type="button"
              onClick={() => scrollTo(link.target)}
              className="font-body text-sm text-muted hover:text-white transition-colors cursor-pointer bg-transparent border-none"
            >
              {link.label}
            </button>
          ))}
          <button
            type="button"
            onClick={() => scrollTo('demo')}
            className="px-5 py-2.5 rounded-lg bg-gradient-to-r from-cyan to-purple font-body text-sm text-white font-medium hover:opacity-90 transition-opacity cursor-pointer border-none"
          >
            Book a Demo
          </button>
        </div>

        {/* Mobile toggle */}
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-label="Toggle navigation menu"
          aria-expanded={open}
          className="md:hidden w-10 h-10 flex items-center justify-center rounded-lg border border-white/10 bg-transparent text-white cursor-pointer"
        >
          <i className={`ti ${open ? 'ti-x' : 'ti-menu-2'} text-xl`} />
        </button>
      </div>

      {/* Mobile menu */}
      {open && (
        <div className="md:hidden flex flex-col gap-1 px-5 sm:px-8 pb-5 pt-3 border-t border-white/5">
          {NAV_LINKS.map((link) => (
            <button
              key={link.target}
              type="button"
              onClick={() => scrollTo(link.target)}
              className="text-left font-body text-base text-muted hover:text-white transition-colors py-2.5 bg-transparent border-none cursor-pointer"
            >
              {link.label}
            </button>
          ))}
          <button
            type="button"
            onClick={() => scrollTo('demo')}
            className="mt-2 px-5 py-3 rounded-lg bg-gradient-to-r from-cyan to-purple font-body text-sm text-white font-medium text-center cursor-pointer border-none"
          >
            Book a Demo
          </button>
        </div>
      )}
    </nav>
  )
}
