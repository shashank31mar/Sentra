import { useEffect, useRef, useState } from 'react'
import {
  IconBuilding,
  IconChevronDown,
  IconFingerprint,
  IconLogout,
  IconShieldCheck,
  IconSwitchHorizontal,
  IconUserShield,
} from '@tabler/icons-react'
import { useCurrentUser } from '../../lib/query/useCurrentUser'
import { displayName, initials, primaryRole, signOut, tenantLabelForDisplay } from '../../lib/auth'

const lineBorder = { border: '1px solid var(--color-line)' }

/**
 * Profile control in the TopBar: shows the logged-in operator (dynamic, from
 * the `/whoami` claims) and a dropdown with Switch account + Sign out. Logout is
 * a top-level navigation — see lib/auth.signOut().
 */
export function AccountMenu() {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const { data: user, isLoading } = useCurrentUser()

  useEffect(() => {
    if (!open) return
    const onPointer = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointer)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onPointer)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  const name = displayName(user)
  const role = primaryRole(user)
  const tenant = tenantLabelForDisplay(user)
  const monogram = initials(user)
  const email = user?.email ?? null

  return (
    <div className="relative" ref={ref}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Account menu"
        className="flex items-center gap-2 pl-1 sm:pl-2 pr-1 py-1 rounded-xl bg-surface-2 cursor-pointer transition-colors"
        style={lineBorder}
      >
        <div className="text-right leading-tight hidden sm:block max-w-[140px]">
          <div className="text-xs font-medium text-white truncate">
            {isLoading ? 'Loading…' : name}
          </div>
          <div className="text-[10px] font-mono text-muted truncate">{role}</div>
        </div>
        <span
          className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0 text-[11px] font-bold font-display text-white"
          style={{
            background: 'linear-gradient(140deg, rgba(15,255,255,0.18), rgba(255,0,128,0.18))',
            border: '1px solid rgba(15,255,255,0.3)',
          }}
        >
          {monogram ?? <IconUserShield size={16} className="text-cyan" />}
        </span>
        <IconChevronDown
          size={13}
          className={`text-muted hidden sm:block transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && (
        <div
          role="menu"
          aria-label="Account"
          className="absolute right-0 top-[calc(100%+10px)] w-80 max-w-[calc(100vw-1.5rem)] rounded-2xl overflow-hidden z-50"
          style={{
            background: 'var(--color-surface-2)',
            border: '1px solid var(--color-line)',
            boxShadow: '0 24px 70px rgba(0,0,0,0.65)',
          }}
        >
          <span
            className="absolute -top-1.5 right-6 h-3 w-3 rotate-45"
            style={{
              background: '#13202B',
              borderLeft: '1px solid var(--color-line)',
              borderTop: '1px solid var(--color-line)',
            }}
          />

          {/* Identity header */}
          <div
            className="relative p-4 pb-5"
            style={{
              background: 'linear-gradient(135deg, #13202B, #0B141C)',
              borderBottom: '1px solid var(--color-line)',
            }}
          >
            <div
              className="absolute inset-0 opacity-30 pointer-events-none"
              style={{ background: 'radial-gradient(120px 80px at 85% 0%, rgba(255,0,128,0.25), transparent 70%)' }}
            />
            <div className="relative flex items-center gap-3">
              <span
                className="h-12 w-12 rounded-xl grid place-items-center text-base font-bold font-display text-white shrink-0"
                style={{ background: 'linear-gradient(140deg, #FF0080, #7A0140)', border: '1px solid rgba(255,255,255,0.15)' }}
              >
                {monogram ?? <IconUserShield size={20} />}
              </span>
              <div className="min-w-0">
                <div className="text-[15px] font-semibold font-display truncate text-white">{name}</div>
                <div className="text-[11px] text-secondary truncate font-mono">
                  {email ?? 'identity unavailable'}
                </div>
              </div>
            </div>
            <div className="relative mt-3 flex items-center gap-2 flex-wrap">
              <span
                className="inline-flex items-center gap-1 text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded text-cyan"
                style={{ background: 'rgba(15,255,255,0.1)', border: '1px solid rgba(15,255,255,0.2)' }}
              >
                <IconShieldCheck size={11} /> {role}
              </span>
              {tenant && (
                <span
                  className="inline-flex items-center gap-1 text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded text-secondary bg-surface-2"
                  style={lineBorder}
                >
                  <IconBuilding size={11} /> {tenant}
                </span>
              )}
            </div>
          </div>

          {/* Session facts */}
          <div
            className="px-4 py-3 grid grid-cols-2 gap-3 text-[11px]"
            style={{ borderBottom: '1px solid var(--color-line)' }}
          >
            <div>
              <div className="text-[9px] uppercase tracking-wider text-faint mb-0.5">Auth method</div>
              <div className="text-secondary font-mono flex items-center gap-1">
                <IconFingerprint size={12} className="text-cyan/70" /> Cognito SSO
              </div>
            </div>
            <div>
              <div className="text-[9px] uppercase tracking-wider text-faint mb-0.5">Session</div>
              <div className="text-secondary font-mono flex items-center gap-1">
                <span
                  className="h-1.5 w-1.5 rounded-full"
                  style={{ background: '#22E58B', boxShadow: '0 0 6px #22E58B' }}
                />
                Active
              </div>
            </div>
          </div>

          {/* Actions */}
          <div className="p-1.5">
            <button
              role="menuitem"
              type="button"
              onClick={signOut}
              className="w-full flex items-center gap-3 px-2.5 py-2 rounded-lg text-sm text-secondary hover:bg-white/5 transition-colors cursor-pointer"
            >
              <IconSwitchHorizontal size={16} className="text-muted" /> Switch account
            </button>
          </div>

          <div className="p-3 pt-1.5">
            <button
              role="menuitem"
              type="button"
              onClick={signOut}
              className="w-full h-10 inline-flex items-center justify-center gap-2 rounded-xl text-sm font-bold text-white transition-all cursor-pointer"
              style={{ background: '#FF0080', boxShadow: '0 8px 24px rgba(255,0,128,0.25)' }}
            >
              <IconLogout size={16} /> Sign out
            </button>
            <p className="mt-2 text-center text-[10px] text-faint font-mono">
              Ends this session · redirects to login
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
