import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { connectionsApi } from '../api/connections'
import { queryKeys } from '../queryKeys'
import type { CloudProvider } from '../../types/enums'
import type { CloudConnection } from '../../types/api'

export function useConnections() {
  return useQuery({
    queryKey: queryKeys.connections.list(),
    queryFn: () => connectionsApi.list(),
  })
}

export function useConnection(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.connections.detail(id ?? ''),
    queryFn: () => connectionsApi.get(id as string),
    enabled: Boolean(id),
  })
}

/** Seed the per-connection cache so detail reads are instant after a write. */
function cacheConnection(qc: ReturnType<typeof useQueryClient>, conn: CloudConnection) {
  qc.setQueryData(queryKeys.connections.detail(conn.id), conn)
}

export function useCreateConnection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (cloudProvider: CloudProvider) => connectionsApi.create(cloudProvider),
    onSuccess: (conn) => {
      cacheConnection(qc, conn)
      qc.invalidateQueries({ queryKey: queryKeys.connections.list() })
    },
  })
}

export function useTestConnection(id: string) {
  const qc = useQueryClient()
  return useMutation({
    // Set the role + probe in one call (spec §4.5 convenience body).
    mutationFn: (roleArn: string) => connectionsApi.test(id, roleArn),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.connections.detail(id) })
      qc.invalidateQueries({ queryKey: queryKeys.connections.list() })
    },
  })
}

export function useScanConnection(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: () => connectionsApi.scan(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.connections.detail(id) })
      qc.invalidateQueries({ queryKey: ['discovery'] })
    },
  })
}

export function useRemoveConnection() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => connectionsApi.remove(id),
    onSuccess: (_res, id) => {
      qc.removeQueries({ queryKey: queryKeys.connections.detail(id) })
      qc.invalidateQueries({ queryKey: queryKeys.connections.list() })
    },
  })
}
