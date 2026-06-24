import { useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { IconBuildingCommunity, IconCheck, IconChevronDown } from '@tabler/icons-react'
import { useMe } from '../../lib/query/useMe'
import { getActiveTenant, setActiveTenant } from '../../lib/tenant'

const chipBorder = { border: '1px solid var(--color-line)' }

/**
 * Active-tenant switcher for multi-membership operators (LLD-26 WS-C C1).
 *
 * Rendered ONLY when the operator belongs to more than one tenant (a partner /
 * Sentra admin). The chosen tenant rides the `X-Aegion-Tenant` header, which the
 * server validates against the membership set (403 if not a member) — so this is
 * a preference, never an authorization. On switch we reset the active tenant and
 * invalidate every query so all tenant-scoped views refetch under the new tenant.
 */
export function TenantSwitcher() {
  const { data: me } = useMe()
  const qc = useQueryClient()
  const [open, setOpen] = useState(false)

  const memberships = me?.memberships ?? []
  // Single-tenant operators don't need (and never see) the switcher.
  if (memberships.length <= 1) return null

  const active = getActiveTenant() ?? me?.tenant_id ?? memberships[0]?.tenant_id

  const choose = (tenantId: string) => {
    setOpen(false)
    if (tenantId === active) return
    setActiveTenant(tenantId)
    // Drop every cached tenant-scoped response so the new tenant's data loads.
    qc.invalidateQueries()
  }

  return (
    <div className="relative hidden md:block">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-2 px-3 h-9 rounded-xl text-xs font-mono cursor-pointer transition-all bg-surface-2 text-secondary hover:border-cyan/40"
        style={chipBorder}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Switch tenant"
      >
        <IconBuildingCommunity size={15} className="text-cyan" />
        <span className="max-w-[10rem] truncate">{active}</span>
        <IconChevronDown size={13} className="text-muted" />
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} aria-hidden />
          <ul
            role="listbox"
            className="absolute right-0 mt-2 z-40 min-w-[14rem] max-h-80 overflow-y-auto rounded-xl py-1 shadow-xl bg-surface-2 scrollbar-thin"
            style={chipBorder}
          >
            {memberships.map((m) => (
              <li key={m.tenant_id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={m.tenant_id === active}
                  onClick={() => choose(m.tenant_id)}
                  className="w-full flex items-center justify-between gap-3 px-3 py-2 text-xs font-mono text-secondary hover:text-cyan hover:bg-white/5 text-left"
                >
                  <span className="truncate">
                    {m.tenant_id}
                    <span className="ml-2 text-faint">{m.role}</span>
                  </span>
                  {m.tenant_id === active && <IconCheck size={14} className="text-cyan shrink-0" />}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}
