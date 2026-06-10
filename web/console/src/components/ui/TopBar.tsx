import { Link, useLocation } from 'react-router-dom'
import {
  IconBell,
  IconChevronDown,
  IconChevronRight,
  IconCloud,
  IconMenu2,
  IconSearch,
} from '@tabler/icons-react'
import { NAV_ITEMS } from '../../app/navConfig'
import { AccountMenu } from './AccountMenu'

interface Crumb {
  label: string
  to?: string
}

function useBreadcrumbs(): Crumb[] {
  const { pathname } = useLocation()
  const crumbs: Crumb[] = [{ label: 'Aegion', to: '/' }]

  if (pathname === '/') {
    crumbs.push({ label: 'Overview' })
    return crumbs
  }

  const match = NAV_ITEMS.find((i) => i.to !== '/' && pathname.startsWith(i.to))
  if (match) crumbs.push({ label: match.label, to: match.to })

  const detail = pathname.match(/^\/agents\/([^/]+)$/)
  if (detail) crumbs.push({ label: detail[1] })

  return crumbs
}

const chipBorder = { border: '1px solid var(--color-line)' }

export function TopBar({ onMenuClick }: { onMenuClick: () => void }) {
  const crumbs = useBreadcrumbs()

  return (
    <header
      className="h-14 shrink-0 flex items-center justify-between gap-3 px-4 sm:px-6 z-20"
      style={{
        background: 'rgba(6,16,26,0.82)',
        backdropFilter: 'blur(12px)',
        borderBottom: '1px solid var(--color-line)',
      }}
    >
      <div className="flex items-center gap-2 min-w-0">
        {/* Hamburger (mobile only) */}
        <button
          type="button"
          onClick={onMenuClick}
          className="lg:hidden w-9 h-9 -ml-1 flex items-center justify-center rounded-xl text-secondary hover:text-cyan shrink-0"
          aria-label="Open navigation"
        >
          <IconMenu2 size={20} />
        </button>

        {/* Breadcrumb */}
        <nav className="flex items-center gap-2 text-sm min-w-0">
          <span
            className="w-1.5 h-1.5 rounded-full mr-1 shrink-0"
            style={{ background: '#22E58B', boxShadow: '0 0 8px #22E58B' }}
          />
          {crumbs.map((crumb, idx) => (
            <span key={`${crumb.label}-${idx}`} className="flex items-center gap-2 min-w-0">
              {idx > 0 && <IconChevronRight size={13} className="shrink-0 text-faint" />}
              {crumb.to && idx < crumbs.length - 1 ? (
                <Link
                  to={crumb.to}
                  className="truncate text-secondary hover:text-cyan transition-colors hidden sm:inline"
                >
                  {crumb.label}
                </Link>
              ) : (
                <span className="truncate font-medium text-white">{crumb.label}</span>
              )}
            </span>
          ))}
        </nav>
      </div>

      {/* Right cluster */}
      <div className="flex items-center gap-2 sm:gap-2.5 shrink-0">
        {/* Search — icon-only on mobile */}
        <button
          type="button"
          className="flex items-center gap-2 px-2.5 sm:px-3 h-9 rounded-xl text-xs font-mono cursor-pointer transition-all bg-surface-2 text-secondary hover:border-cyan/40"
          style={chipBorder}
          aria-label="Search"
        >
          <IconSearch size={15} />
          <span className="hidden sm:inline">Search</span>
          <span
            className="hidden sm:inline px-1.5 py-0.5 rounded text-muted"
            style={{ background: 'rgba(255,255,255,0.06)' }}
          >
            ⌘K
          </span>
        </button>

        {/* Cloud selector — hidden on small screens */}
        <button
          type="button"
          className="hidden md:flex items-center gap-2 px-3 h-9 rounded-xl text-xs font-mono cursor-pointer transition-all bg-surface-2 text-secondary hover:border-cyan/40"
          style={chipBorder}
        >
          <IconCloud size={15} className="text-cyan" />
          global-prod-01
          <IconChevronDown size={13} className="text-muted" />
        </button>

        <button
          type="button"
          className="relative w-9 h-9 flex items-center justify-center rounded-xl bg-surface-2 text-secondary cursor-pointer shrink-0"
          style={chipBorder}
          aria-label="Notifications"
        >
          <IconBell size={18} />
          <span
            className="absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full"
            style={{ background: '#FF0080' }}
          />
        </button>

        <AccountMenu />
      </div>
    </header>
  )
}
