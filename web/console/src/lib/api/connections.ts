import { http } from '../http'
import type { CloudProvider } from '../../types/enums'
import type {
  CloudConnection,
  ConnectionTestResult,
  ScanResult,
} from '../../types/api'

/**
 * Cloud-account connections (connections-api-spec). Powers the Connect Account
 * wizard. Secrets never touch the browser — the connection carries a vault
 * reference + the minted external_id only.
 */
export const connectionsApi = {
  list: () => http.get<{ connections: CloudConnection[] }>('/connections'),

  get: (id: string) => http.get<CloudConnection>(`/connections/${encodeURIComponent(id)}`),

  /** Create a connection; the server mints `external_id` + `aegion_principal_arn`. */
  create: (cloudProvider: CloudProvider) =>
    http.post<CloudConnection>('/connections', { cloud_provider: cloudProvider }),

  /** Attach/replace the cross-account role reference after the stack is deployed. */
  setRole: (id: string, roleArn: string) =>
    http.put<CloudConnection>(`/connections/${encodeURIComponent(id)}`, { role_arn: roleArn }),

  /** Live AssumeRole probe. `ok:false` is a successful test with a rejecting role (not an HTTP error). */
  test: (id: string, roleArn?: string) =>
    http.post<ConnectionTestResult>(
      `/connections/${encodeURIComponent(id)}/test`,
      roleArn ? { role_arn: roleArn } : undefined,
    ),

  /** Trigger discovery for this connection (async). */
  scan: (id: string) =>
    http.post<ScanResult>(`/connections/${encodeURIComponent(id)}/scan`),

  remove: (id: string) => http.del<void>(`/connections/${encodeURIComponent(id)}`),
}
