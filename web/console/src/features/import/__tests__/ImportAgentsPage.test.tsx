import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { can } from '../../../lib/rbac'
import type { TenantRole, DiscoveredAgent } from '../../../types/api'

let role: TenantRole = 'viewer'
vi.mock('../../../lib/query/useMe', () => ({
  useCan: () => (cap: Parameters<typeof can>[1]) => can(role, cap),
}))

const DISCOVERED: DiscoveredAgent = {
  id: 'disc_1',
  agent_id: null,
  native_resource_id: 'arn:aws:...:agent/1',
  name: 'Unmanaged Agent',
  cloud_provider: 'aws',
  framework: 'bedrock',
  first_seen: '2026-07-01T00:00:00Z',
  risk: 'med',
  status: 'not_imported',
}

const infinite = <T,>(items: T[]) => ({
  data: { pages: [{ items, total: items.length, next_token: null }] },
  isLoading: false,
  isError: false,
  error: null,
  refetch: vi.fn(),
})

vi.mock('../../../lib/query/useDiscovery', () => ({
  useDiscoverySummary: () => ({ data: { detected: 1, unmanaged: 1, new_24h: 0, providers_connected: 1, providers_total: 3, last_scan: null }, isLoading: false }),
  useDiscoveryPlatforms: () => ({ data: null }),
  useDiscoveredAgents: () => infinite([DISCOVERED]),
  useImportAgents: () => ({ mutate: vi.fn(), isPending: false }),
}))
vi.mock('../../../lib/query/useConnections', () => ({
  useConnection: () => ({ data: null }),
}))

import { ImportAgentsPage } from '../ImportAgentsPage'

describe('ImportAgentsPage import gating (G2.5)', () => {
  beforeEach(() => {
    role = 'viewer'
  })

  it('editor sees the Import action', () => {
    role = 'editor'
    renderWithProviders(<ImportAgentsPage />)
    expect(screen.getByRole('button', { name: /Import/i })).toBeInTheDocument()
  })

  it('viewer sees no Import action but the discovery table renders', () => {
    role = 'viewer'
    renderWithProviders(<ImportAgentsPage />)
    expect(screen.queryByRole('button', { name: /^Import/i })).not.toBeInTheDocument()
    expect(screen.getByText('Unmanaged Agent')).toBeInTheDocument()
  })
})
