import type { Icon } from '@tabler/icons-react'
import {
  IconLayoutDashboard,
  IconAlertTriangle,
  IconRocket,
  IconRobot,
  IconRadar2,
  IconCloudDownload,
  IconCloudUpload,
  IconShieldLock,
  IconListSearch,
} from '@tabler/icons-react'
import { ROUTES } from './routes'

export interface NavItem {
  label: string
  to: string
  icon: Icon
}

export interface NavGroup {
  title: string
  items: NavItem[]
}

/** Mirrors the canvas NavRail (Monitor / Assets / Onboard / Govern). */
export const NAV_GROUPS: NavGroup[] = [
  {
    title: 'Monitor',
    items: [
      { label: 'Overview', to: ROUTES.overview, icon: IconLayoutDashboard },
      { label: 'Threats', to: ROUTES.threats, icon: IconAlertTriangle },
      { label: 'Deployments', to: ROUTES.deployments, icon: IconRocket },
    ],
  },
  {
    title: 'Assets',
    items: [
      { label: 'Agent Inventory', to: ROUTES.agents, icon: IconRobot },
      { label: 'Discovery', to: ROUTES.discovery, icon: IconRadar2 },
    ],
  },
  {
    title: 'Onboard',
    items: [
      { label: 'Import Agents', to: ROUTES.import, icon: IconCloudDownload },
      { label: 'Deploy Agent', to: ROUTES.deploy, icon: IconCloudUpload },
    ],
  },
  {
    title: 'Govern',
    items: [
      { label: 'Policies', to: ROUTES.policies, icon: IconShieldLock },
      { label: 'Audit Trail', to: ROUTES.audit, icon: IconListSearch },
    ],
  },
]

/** Flattened lookup for breadcrumb derivation. */
export const NAV_ITEMS: NavItem[] = NAV_GROUPS.flatMap((g) => g.items)
