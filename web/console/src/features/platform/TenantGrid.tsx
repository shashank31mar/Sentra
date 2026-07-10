import { useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { useVirtualizer } from '@tanstack/react-virtual'
import { Table, TBody, Td, Th, THead, Tr } from '../../components/ui/Table'
import { platformTenantDetailPath } from '../../app/routes'
import { formatNumber } from '../../lib/format'
import { metricsPresent } from './fleetRank'
import type { PlatformTenantRow } from '../../types/api'

const IDENTITY_MODE_COLOR: Record<string, string> = {
  enforce: '#22E58B',
  shadow: '#4F86D6',
  off: '#6B7E9E',
}

function ConsentPill({ granted }: { granted?: boolean }) {
  // FX-3.5 → ws-g-fix-backend FXB-1.2: the list route (`platform_list_tenants`) now
  // PROJECTS `platform_read_consent` per row, so `granted` is normally a real
  // true/false. The `undefined`→"unknown" branch is retained as defense-in-depth
  // (an older controller that predates FXB-1.2) — a governance console must never
  // falsely show "required" for a tenant whose state it doesn't actually know.
  if (granted === undefined) {
    return (
      <span className="text-[11px] font-mono text-muted" title="consent state not in the list — open the tenant to see it">
        unknown
      </span>
    )
  }
  if (granted) {
    return <span className="text-[11px] font-mono text-green">granted</span>
  }
  return (
    <span className="text-[11px] font-mono text-amber" title="platform-read consent not granted">
      required
    </span>
  )
}

/**
 * Fleet tenant grid (G4.3). Ships the Ranked-Table 6-col shape FIRST (Tenant · Plan
 * · Identity mode · Status · Created · Consent), read-only, rows-as-links. When the
 * optional metric fields arrive (PRE-G4-a) the metric columns light up. Rows are
 * virtualized (`useVirtualizer`) when the server sends a `cursor` (PRE-G4-b, paged
 * set); otherwise the small unpaged set renders directly. NO mutation control —
 * rows are links only (read-only invariant).
 */
export function TenantGrid({
  rows,
  virtualized = false,
}: {
  rows: PlatformTenantRow[]
  /** True once server paging (cursor) lands — enables row windowing. */
  virtualized?: boolean
}) {
  const navigate = useNavigate()
  const showMetrics = metricsPresent(rows)

  const scrollRef = useRef<HTMLDivElement>(null)
  const rowVirtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: () => 52,
    overscan: 8,
    // Seed the viewport so windowing works even before/without real layout
    // measurement (jsdom reports 0-height rects) — the real ResizeObserver
    // corrects it in the browser.
    initialRect: { width: 960, height: 480 },
  })

  const renderRow = (t: PlatformTenantRow) => (
    <Tr key={t.tenant_id} onClick={() => navigate(platformTenantDetailPath(t.tenant_id))}>
      <Td>
        <div className="font-display font-bold text-white">{t.display_name}</div>
        <div className="text-[11px] font-mono text-muted">{t.tenant_id}</div>
      </Td>
      <Td className="font-mono text-xs text-secondary capitalize">{t.plan}</Td>
      <Td>
        <span
          className="text-xs font-mono capitalize"
          style={{ color: IDENTITY_MODE_COLOR[t.identity_mode] ?? '#6B7E9E' }}
        >
          {t.identity_mode}
        </span>
      </Td>
      <Td className="font-mono text-xs text-secondary capitalize">{t.status}</Td>
      <Td className="font-mono text-xs text-muted">{t.created_at}</Td>
      <Td>
        <ConsentPill granted={t.platform_read_consent} />
      </Td>
      {showMetrics && (
        <>
          <Td className="text-right font-mono text-pink">{formatNumber(t.blocks_24h ?? null)}</Td>
          <Td className="text-right font-mono text-secondary">{formatNumber(t.agents ?? null)}</Td>
        </>
      )}
    </Tr>
  )

  // Virtualized path (paged set): window the rows inside a fixed-height scroller so
  // useVirtualizer measures real DOM (a mis-set container collapses it to 0 rows).
  if (virtualized) {
    const items = rowVirtualizer.getVirtualItems()
    return (
      <div
        ref={scrollRef}
        data-testid="tenant-grid-virtual"
        className="overflow-y-auto scrollbar-thin"
        style={{ height: 480 }}
      >
        <div style={{ height: rowVirtualizer.getTotalSize(), position: 'relative' }}>
          {items.map((vi) => {
            const t = rows[vi.index]
            return (
              <div
                key={t.tenant_id}
                data-testid="tenant-grid-row"
                onClick={() => navigate(platformTenantDetailPath(t.tenant_id))}
                className="absolute left-0 right-0 flex items-center gap-4 px-6 cursor-pointer hover:bg-white/[0.025] border-b border-white/[0.04]"
                style={{ transform: `translateY(${vi.start}px)`, height: 52 }}
              >
                <div className="flex-1 min-w-0">
                  <div className="font-display font-bold text-white truncate">{t.display_name}</div>
                  <div className="text-[11px] font-mono text-muted truncate">{t.tenant_id}</div>
                </div>
                <span className="font-mono text-xs text-secondary capitalize w-24">{t.plan}</span>
                <span
                  className="font-mono text-xs capitalize w-20"
                  style={{ color: IDENTITY_MODE_COLOR[t.identity_mode] ?? '#6B7E9E' }}
                >
                  {t.identity_mode}
                </span>
                <span className="font-mono text-xs text-secondary capitalize w-20">{t.status}</span>
                <ConsentPill granted={t.platform_read_consent} />
              </div>
            )
          })}
        </div>
      </div>
    )
  }

  return (
    <Table>
      <THead>
        <Th>Tenant</Th>
        <Th>Plan</Th>
        <Th>Identity mode</Th>
        <Th>Status</Th>
        <Th>Created</Th>
        <Th>Consent</Th>
        {showMetrics && <Th className="text-right">Blocks 24h</Th>}
        {showMetrics && <Th className="text-right">Agents</Th>}
      </THead>
      <TBody>{rows.map(renderRow)}</TBody>
    </Table>
  )
}
