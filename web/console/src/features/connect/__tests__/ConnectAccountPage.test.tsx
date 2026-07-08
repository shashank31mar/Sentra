import { describe, it, expect, vi, beforeEach } from 'vitest'
import { screen } from '@testing-library/react'
import { renderWithProviders } from '../../../test/renderWithProviders'
import { can } from '../../../lib/rbac'
import type { TenantRole } from '../../../types/api'

let role: TenantRole = 'viewer'
vi.mock('../../../lib/query/useMe', () => ({
  useCan: () => (cap: Parameters<typeof can>[1]) => can(role, cap),
}))

// No connection selected → wizard is on step 1 (cloud picker), no grant card.
vi.mock('../../../lib/query/useConnections', () => ({
  useConnections: () => ({ data: { connections: [] } }),
  useConnection: () => ({ data: null, isError: false }),
  useCreateConnection: () => ({ mutate: vi.fn(), reset: vi.fn(), isPending: false, data: null }),
  useScanConnection: () => ({ mutate: vi.fn(), isPending: false }),
  useRemoveConnection: () => ({ mutate: vi.fn(), isPending: false }),
  useTestConnection: () => ({ mutate: vi.fn(), isPending: false, data: undefined }),
  useSetAzureCredentials: () => ({ mutate: vi.fn(), isPending: false }),
}))

import { ConnectAccountPage } from '../ConnectAccountPage'

// The AWS cloud tile is the "create" entry point; disabled when the operator
// lacks connections.write (and no existing connection for that provider).
function awsTile(): HTMLButtonElement {
  return screen.getByRole('button', { name: /AWS|Bedrock/i }) as HTMLButtonElement
}

describe('ConnectAccountPage connection gating (G2.6)', () => {
  beforeEach(() => {
    role = 'viewer'
  })

  it('admin can start a connection (create tile enabled)', () => {
    role = 'admin'
    renderWithProviders(<ConnectAccountPage />)
    expect(awsTile()).not.toBeDisabled()
  })

  it('viewer cannot start a connection (create tile disabled)', () => {
    role = 'viewer'
    renderWithProviders(<ConnectAccountPage />)
    expect(awsTile()).toBeDisabled()
  })

  it('editor (operate-only) also cannot start a NEW connection', () => {
    role = 'editor'
    renderWithProviders(<ConnectAccountPage />)
    // editor lacks connections.write (admin) → create tile disabled.
    expect(awsTile()).toBeDisabled()
  })
})
