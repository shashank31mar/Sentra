import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import { NavRail } from '../components/ui/NavRail'
import { TopBar } from '../components/ui/TopBar'
import { ToastProvider } from '../components/ui/Toast'
import { RequireBoundTenant } from './RequireBoundTenant'
import { RequireCustomerRoot } from './RequireCustomerRoot'

/** Root chrome: NavRail (off-canvas drawer on mobile) + TopBar + scrollable content. */
export function AppLayout() {
  const [navOpen, setNavOpen] = useState(false)

  return (
    <ToastProvider>
      {/* FX-2.5: a platform operator is redirected to /platform BEFORE the customer
          shell mounts — they never see customer tenant chrome (symmetric root-split). */}
      <RequireCustomerRoot>
        <div className="flex min-h-screen bg-bg text-ink">
          {/* NavRail closes itself on item click + backdrop tap (see NavRail). */}
          <NavRail open={navOpen} onClose={() => setNavOpen(false)} />
          <div className="flex-1 min-w-0 flex flex-col h-screen overflow-hidden">
            <TopBar onMenuClick={() => setNavOpen(true)} />
            <main className="flex-1 overflow-y-auto scrollbar-thin">
              {/* G2.12: multi-membership operator with no bound tenant → org page. */}
              <RequireBoundTenant>
                <Outlet />
              </RequireBoundTenant>
            </main>
          </div>
        </div>
      </RequireCustomerRoot>
    </ToastProvider>
  )
}
