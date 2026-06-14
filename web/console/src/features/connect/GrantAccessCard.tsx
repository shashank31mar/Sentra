import { useState } from 'react'
import { IconInfoCircle, IconPlugConnected, IconLoader2, IconAlertTriangle } from '@tabler/icons-react'
import { Card } from '../../components/ui/Card'
import { Button } from '../../components/ui/Button'
import { CodeBlock } from '../../components/ui/CodeBlock'
import { StatusDot } from '../../components/ui/StatusDot'
import { CopyField } from './CopyField'
import { buildRoleTemplate } from './cloudCatalog'
import { useTestConnection } from '../../lib/query/useConnections'
import type { CloudConnection } from '../../types/api'

interface GrantAccessCardProps {
  connection: CloudConnection
}

/**
 * Step 2 — guided cross-account role setup. Renders the CloudFormation trust
 * policy (with the minted ExternalId), captures the resulting Role ARN, and runs
 * a live AssumeRole probe (`POST /connections/{id}/test`).
 */
export function GrantAccessCard({ connection }: GrantAccessCardProps) {
  const [roleArn, setRoleArn] = useState(connection.role_arn ?? '')
  const test = useTestConnection(connection.id)
  const template = buildRoleTemplate({
    externalId: connection.external_id,
    principalArn: connection.aegion_principal_arn,
    scopes: connection.scopes,
  })

  const result = test.data
  const isConnected = connection.status === 'connected'

  return (
    <Card className="overflow-hidden">
      <div
        className="px-5 py-3.5 flex items-center justify-between"
        style={{ borderBottom: '1px solid var(--color-line)' }}
      >
        <span className="text-xs font-semibold uppercase tracking-[0.18em] text-secondary">
          Grant access — cross-account IAM role
        </span>
        <span className="text-[10px] font-mono text-muted">CloudFormation</span>
      </div>

      <div className="p-5 space-y-5">
        <CodeBlock code={template} filename="aegion-connect-role.yaml" />

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <CopyField label="External ID" hint="(enforced)" value={connection.external_id} />
          <div>
            <label
              htmlFor="role-arn"
              className="text-[11px] font-medium text-secondary mb-1.5 flex items-center gap-1.5"
            >
              Role ARN <span className="text-pink">*</span>
            </label>
            <input
              id="role-arn"
              value={roleArn}
              onChange={(e) => setRoleArn(e.target.value)}
              placeholder="arn:aws:iam::5311…:role/AegionDiscoveryRole"
              spellCheck={false}
              className="w-full h-10 px-3 rounded-xl font-mono text-xs text-ink outline-none placeholder:text-faint"
              style={{ background: '#05090E', border: '1px solid var(--color-line)' }}
            />
          </div>
        </div>

        <p className="flex items-start gap-2 text-[11px] text-secondary">
          <IconInfoCircle size={15} className="text-cyan/70 mt-px shrink-0" />
          Deploy the stack in your account, then paste the created role&apos;s ARN above. The{' '}
          <span className="font-mono text-ink">ExternalId</span> blocks the confused-deputy attack.
        </p>

        {/* Test result */}
        <div
          className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between rounded-xl px-4 py-3.5"
          style={{ background: '#05090E', border: '1px solid var(--color-line)' }}
        >
          <div className="flex items-center gap-3 min-w-0">
            <span
              className="h-9 w-9 rounded-lg grid place-items-center shrink-0"
              style={{ background: 'rgba(34,229,139,0.1)', border: '1px solid rgba(34,229,139,0.25)' }}
            >
              <IconPlugConnected size={18} className="text-green" />
            </span>
            <div className="min-w-0">
              <div className="text-sm font-medium text-ink">Test connection</div>
              <div className="text-[11px] font-mono truncate flex items-center gap-1.5">
                {test.isPending ? (
                  <span className="text-secondary">Probing AssumeRole…</span>
                ) : result?.ok ? (
                  <span className="text-green flex items-center gap-1.5">
                    <StatusDot color="#22E58B" /> {result.message}
                  </span>
                ) : result && !result.ok ? (
                  <span className="text-pink flex items-center gap-1.5">
                    <IconAlertTriangle size={12} /> {result.message}
                  </span>
                ) : (
                  <span className="text-muted">Not tested yet</span>
                )}
              </div>
            </div>
          </div>
          <Button
            variant="ghost"
            onClick={() => test.mutate(roleArn.trim())}
            disabled={!roleArn.trim() || test.isPending}
            className="shrink-0"
          >
            {test.isPending ? <IconLoader2 size={14} className="animate-spin" /> : null}
            {isConnected ? 'Re-test' : 'Test connection'}
          </Button>
        </div>
      </div>
    </Card>
  )
}
