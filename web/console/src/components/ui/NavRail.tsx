import { NavLink } from 'react-router-dom'
import { IconHexagonLetterA, IconSettings, IconX } from '@tabler/icons-react'
import { NAV_GROUPS, type NavItem } from '../../app/navConfig'

const line = '1px solid var(--color-line)'

function NavRailItem({ item, onNavigate }: { item: NavItem; onNavigate: () => void }) {
  const Icon = item.icon
  return (
    <NavLink
      to={item.to}
      end={item.to === '/'}
      onClick={onNavigate}
      className={({ isActive }) =>
        `relative flex items-center gap-3 h-9 pl-3 pr-2 rounded-lg text-sm transition-colors ${
          isActive ? 'font-medium text-cyan' : 'text-secondary hover:bg-white/[0.03]'
        }`
      }
      style={({ isActive }) =>
        isActive ? { background: 'rgba(15,255,255,0.09)' } : undefined
      }
    >
      {({ isActive }) => (
        <>
          {isActive && (
            <span
              className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-5 rounded-r"
              style={{ background: '#0FFFFF', boxShadow: '0 0 10px #0FFFFF' }}
            />
          )}
          <Icon size={20} stroke={1.75} />
          <span>{item.label}</span>
        </>
      )}
    </NavLink>
  )
}

interface NavRailProps {
  open: boolean
  onClose: () => void
}

export function NavRail({ open, onClose }: NavRailProps) {
  return (
    <>
      {/* Backdrop (mobile only) */}
      {open && (
        <div
          className="fixed inset-0 z-40 bg-black/60 lg:hidden"
          onClick={onClose}
          aria-hidden="true"
        />
      )}

      <aside
        className={`fixed inset-y-0 left-0 z-50 w-64 flex flex-col h-screen transition-transform duration-200 ease-out bg-surface lg:static lg:z-30 lg:w-56 lg:translate-x-0 lg:sticky lg:top-0 ${
          open ? 'translate-x-0' : '-translate-x-full'
        }`}
        style={{ borderRight: line }}
      >
        {/* Brand */}
        <div className="h-14 shrink-0 flex items-center gap-2.5 px-4" style={{ borderBottom: line }}>
          <div
            className="w-8 h-8 flex items-center justify-center rounded-lg"
            style={{
              background: 'linear-gradient(140deg,rgba(15,255,255,0.16),rgba(255,0,128,0.16))',
              border: '1px solid rgba(15,255,255,0.3)',
              boxShadow: '0 0 18px -6px rgba(15,255,255,.6)',
            }}
          >
            <IconHexagonLetterA size={20} className="text-cyan" />
          </div>
          <span className="font-display text-base font-bold tracking-wide text-white">Aegion</span>
          <span
            className="ml-auto text-[9px] font-mono px-1.5 py-0.5 rounded text-cyan"
            style={{ background: 'rgba(15,255,255,0.08)', letterSpacing: '.1em' }}
          >
            SOC
          </span>
          {/* Close (mobile only) */}
          <button
            type="button"
            onClick={onClose}
            className="ml-1 -mr-1 w-8 h-8 flex items-center justify-center rounded-lg text-secondary hover:text-cyan lg:hidden"
            aria-label="Close navigation"
          >
            <IconX size={18} />
          </button>
        </div>

        {/* Groups */}
        <nav className="flex-1 overflow-y-auto scrollbar-thin py-5 px-3 flex flex-col gap-5">
          {NAV_GROUPS.map((group) => (
            <div key={group.title}>
              <div className="px-3 mb-2 text-[10px] font-semibold uppercase tracking-[0.2em] text-label">
                {group.title}
              </div>
              <div className="flex flex-col gap-0.5">
                {group.items.map((item) => (
                  <NavRailItem key={item.to} item={item} onNavigate={onClose} />
                ))}
              </div>
            </div>
          ))}
        </nav>

        {/* Footer */}
        <div className="shrink-0 px-3 py-3" style={{ borderTop: line }}>
          <button
            type="button"
            className="w-full flex items-center gap-3 h-9 px-3 rounded-lg text-sm text-secondary hover:bg-white/[0.03] transition-colors cursor-pointer"
          >
            <IconSettings size={18} stroke={1.75} />
            <span>Settings</span>
          </button>
        </div>
      </aside>
    </>
  )
}
