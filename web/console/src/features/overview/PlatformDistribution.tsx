import { IconBrandAws, IconBrandAzure, IconBrandGoogle, IconCloud } from '@tabler/icons-react'
import type { ComponentType } from 'react'
import { Card } from '../../components/ui/Card'
import { formatNumber } from '../../lib/format'
import type { PlatformDistribution as PlatformDistributionData } from '../../types/api'
import type { CloudProvider } from '../../types/enums'

type IconMeta = { icon: ComponentType<{ size?: number; color?: string }>; color: string }

const ICONS: Partial<Record<CloudProvider, IconMeta>> = {
  aws: { icon: IconBrandAws, color: '#FF9900' },
  gcp: { icon: IconBrandGoogle, color: '#4285F4' },
  azure: { icon: IconBrandAzure, color: '#37A0E8' },
}

// Fallback for any cloud_provider value not in the known set (live data can carry
// platform-derived or null providers — LLD-21 §10.1).
const FALLBACK_ICON: IconMeta = { icon: IconCloud, color: '#8DA2AE' }

export function PlatformDistribution({ data }: { data: PlatformDistributionData }) {
  return (
    <Card className="p-6 mb-5">
      <div className="flex items-center justify-between mb-5">
        <span className="text-sm font-medium uppercase tracking-[0.2em] text-secondary">Platform Distribution</span>
        <span className="text-xs font-mono text-muted">{formatNumber(data.total_nodes)} active nodes globally</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-6 sm:gap-10">
        {(data.providers ?? []).map((p) => {
          const { icon: Icon, color } = ICONS[p.cloud_provider] ?? FALLBACK_ICON
          return (
            <div key={p.cloud_provider}>
              <div className="flex items-center justify-between text-xs mb-3 font-mono">
                <span className="flex items-center gap-2.5 text-ink uppercase">
                  <Icon size={16} color={color} /> {p.label}
                </span>
                <span className="text-secondary">{formatNumber(p.count)}</span>
              </div>
              <div className="h-2 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.06)' }}>
                <div className="h-full rounded-full" style={{ width: `${p.pct}%`, background: '#0FFFFF', boxShadow: '0 0 10px #0FFFFF' }} />
              </div>
            </div>
          )
        })}
      </div>
    </Card>
  )
}
