import type { Icon } from '@tabler/icons-react'
import {
  IconLayoutDashboard,
  IconAlertTriangle,
  IconRocket,
  IconRobot,
  IconSitemap,
  IconCloudDownload,
  IconCloudUpload,
  IconCloudComputing,
  IconShieldLock,
  IconLockExclamation,
  IconClockExclamation,
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
      { label: 'Topology', to: ROUTES.topology, icon: IconSitemap },
    ],
  },
  {
    title: 'Onboard',
    items: [
      { label: 'Connect Account', to: ROUTES.connect, icon: IconCloudComputing },
      { label: 'Import Agents', to: ROUTES.import, icon: IconCloudDownload },
      { label: 'Deploy Agent', to: ROUTES.deploy, icon: IconCloudUpload },
    ],
  },
  {
    title: 'Govern',
    items: [
      { label: 'Policies', to: ROUTES.policies, icon: IconShieldLock },
      { label: 'Quarantine', to: ROUTES.quarantine, icon: IconLockExclamation },
      { label: 'Residual Agents', to: ROUTES.residualAgents, icon: IconClockExclamation },
      { label: 'Audit Trail', to: ROUTES.audit, icon: IconListSearch },
    ],
  },
]

/** Flattened lookup for breadcrumb derivation. */
export const NAV_ITEMS: NavItem[] = NAV_GROUPS.flatMap((g) => g.items)
