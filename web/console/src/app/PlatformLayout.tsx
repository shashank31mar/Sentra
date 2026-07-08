import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { IconWorld } from '@tabler/icons-react'
import { PlatformNavRail } from '../components/ui/PlatformNavRail'
import { AccountMenu } from '../components/ui/AccountMenu'
import { ToastProvider } from '../components/ui/Toast'

/**
 * Platform (cross-tenant) chrome (G4.1). Mirrors `AppLayout`'s shell but mounts the
 * platform NavRail and a header with a non-interactive `PLATFORM · ALL TENANTS`
 * pill — NO `TopBar` tenant controls, NO `TenantSwitcher`, NO tenant selector (the
 * "no tenant selector" invariant, G4.8). Reachable only when `RequirePlatform`
 * passes (`is_platform === true`).
 */
export function PlatformLayout() {
  const [navOpen, setNavOpen] = useState(false)

  return (
    <ToastProvider>
      <div className="flex min-h-screen bg-bg text-ink">
        <PlatformNavRail open={navOpen} onClose={() => setNavOpen(false)} />
        <div className="flex-1 min-w-0 flex flex-col h-screen overflow-hidden">
          <header
            className="h-14 shrink-0 flex items-center justify-between gap-3 px-4 sm:px-6 z-20"
            style={{
              background: 'rgba(10,20,40,0.82)',
              backdropFilter: 'blur(12px)',
              borderBottom: '1px solid var(--color-line)',
            }}
          >
            <div className="flex items-center gap-2 min-w-0">
              <button
                type="button"
                onClick={() => setNavOpen(true)}
                className="lg:hidden w-9 h-9 -ml-1 flex items-center justify-center rounded-xl text-secondary hover:text-blue shrink-0"
                aria-label="Open navigation"
              >
                <IconWorld size={20} />
              </button>
              <span
                className="inline-flex items-center gap-2 px-3 h-8 rounded-xl text-[11px] font-mono font-bold uppercase tracking-wider text-white"
                style={{
                  background: 'linear-gradient(140deg,#2E5FB0,#01153D)',
                  border: '1px solid rgba(79,134,214,0.4)',
                }}
              >
                <IconWorld size={14} /> Platform · All tenants
              </span>
            </div>
            <div className="flex items-center gap-2 sm:gap-2.5 shrink-0">
              <AccountMenu />
            </div>
          </header>
          <main className="flex-1 overflow-y-auto scrollbar-thin">
            <Outlet />
          </main>
        </div>
      </div>
    </ToastProvider>
  )
}
