import { NavLink } from 'react-router-dom'
import { IconHexagonLetterA, IconX } from '@tabler/icons-react'
import { PLATFORM_NAV_GROUPS, type NavItem } from '../../app/navConfig'

const line = '1px solid var(--color-line)'

function PlatformNavRailItem({ item, onNavigate }: { item: NavItem; onNavigate: () => void }) {
  const Icon = item.icon
  return (
    <NavLink
      to={item.to}
      end={item.to === '/platform'}
      onClick={onNavigate}
      className={({ isActive }) =>
        `relative flex items-center gap-3 h-9 pl-3 pr-2 rounded-lg text-sm transition-colors ${
          isActive ? 'font-medium text-blue' : 'text-secondary hover:bg-white/[0.03]'
        }`
      }
      style={({ isActive }) => (isActive ? { background: 'rgba(46,95,176,0.12)' } : undefined)}
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <span
              className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-5 rounded-r"
              style={{ background: 'var(--color-blue)', boxShadow: '0 0 10px var(--color-blue)' }}
            />
          )}
          <Icon size={20} stroke={1.75} />
          <span>{item.label}</span>
        </>
      )}
    </NavLink>
  )
}

/**
 * Platform NavRail (G4.8) — mounted ONLY inside `PlatformLayout`. It carries the
 * `PLATFORM` chip (vs the customer `SOC`) and NO customer nav / tenant controls.
 */
export function PlatformNavRail({ open, onClose }: { open: boolean; onClose: () => void }) {
  return (
    <>
      {open && (
        <div className="fixed inset-0 z-40 bg-black/60 lg:hidden" onClick={onClose} aria-hidden="true" />
      )}
      <aside
        className={`fixed inset-y-0 left-0 z-50 w-64 flex flex-col h-screen transition-transform duration-200 ease-out bg-surface-2 lg:static lg:z-30 lg:w-56 lg:translate-x-0 lg:sticky lg:top-0 ${
          open ? 'translate-x-0' : '-translate-x-full'
        }`}
        style={{ borderRight: line }}
      >
        <div className="h-14 shrink-0 flex items-center gap-2.5 px-4" style={{ borderBottom: line }}>
          <div
            className="w-8 h-8 flex items-center justify-center rounded-lg"
            style={{
              background: 'linear-gradient(150deg,#2E5FB0,#01153D)',
              border: '1px solid rgba(79,134,214,0.4)',
              boxShadow: '0 0 18px -6px rgba(79,134,214,.6)',
            }}
          >
            <IconHexagonLetterA size={20} className="text-blue" />
          </div>
          <span className="font-display text-base font-bold tracking-wide text-white">Aegion</span>
          <span
            className="ml-auto text-[9px] font-mono px-1.5 py-0.5 rounded text-blue"
            style={{ background: 'rgba(46,95,176,0.16)', letterSpacing: '.1em' }}
          >
            PLATFORM
          </span>
          <button
            type="button"
            onClick={onClose}
            className="ml-1 -mr-1 w-8 h-8 flex items-center justify-center rounded-lg text-secondary hover:text-blue lg:hidden"
            aria-label="Close navigation"
          >
            <IconX size={18} />
          </button>
        </div>

        <nav className="flex-1 overflow-y-auto scrollbar-thin py-5 px-3 flex flex-col gap-5">
          {PLATFORM_NAV_GROUPS.map((group) => (
            <div key={group.title}>
              <div className="px-3 mb-2 text-[10px] font-semibold uppercase tracking-[0.2em] text-muted">
                {group.title}
              </div>
              <div className="flex flex-col gap-0.5">
                {group.items.map((item) => (
                  <PlatformNavRailItem key={item.to} item={item} onNavigate={onClose} />
                ))}
              </div>
            </div>
          ))}
        </nav>
      </aside>
    </>
  )
}
