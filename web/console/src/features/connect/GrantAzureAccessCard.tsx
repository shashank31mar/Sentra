import { useState } from 'react'
import { IconInfoCircle, IconPlugConnected, IconLoader2, IconAlertTriangle } from '@tabler/icons-react'
import { Card } from '../../components/ui/Card'
import { Button } from '../../components/ui/Button'
import { CodeBlock } from '../../components/ui/CodeBlock'
import { buildAzureSetup } from './cloudCatalog'
import { useSetAzureCredentials, useTestConnection } from '../../lib/query/useConnections'
import { ApiException } from '../../lib/http'
import { isAuthDegrade403 } from '../../lib/degrade'
import { useToast } from '../../components/ui/Toast'
import type { CloudConnection } from '../../types/api'

interface GrantAzureAccessCardProps {
  connection: CloudConnection
  /** G2.6: the SP probe/attach is a `connections.operate`/`write` action. */
  canOperate?: boolean
}

const GUID = /^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$/

interface FieldProps {
  id: string
  label: string
  value: string
  onChange: (v: string) => void
  placeholder: string
  mono?: boolean
}

function Field({ id, label, value, onChange, placeholder, mono = true }: FieldProps) {
  return (
    <div>
      <label htmlFor={id} className="text-[11px] font-medium text-secondary mb-1.5 flex items-center gap-1.5">
        {label} <span className="text-pink">*</span>
      </label>
      <input
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        spellCheck={false}
        className={`w-full h-10 px-3 rounded-xl ${mono ? 'font-mono' : ''} text-xs text-ink outline-none placeholder:text-faint`}
        style={{ background: '#05090E', border: '1px solid var(--color-line)' }}
      />
    </div>
  )
}

/**
 * Step 2 (Azure) — guided service-principal setup. Renders the read-only `az`
 * commands (the Azure analog of the AWS CloudFormation role), captures the SP
 * subscription/tenant/client ids + the vault secret reference, attaches them
 * (`PUT /connections/{id}` with `{azure}`) and runs a live SP probe
 * (`POST /connections/{id}/test`). The client-secret never enters the browser —
 * only its vault reference does.
 */
export function GrantAzureAccessCard({ connection, canOperate = true }: GrantAzureAccessCardProps) {
  const { error: toastError } = useToast()
  const [subscriptionId, setSubscriptionId] = useState(connection.azure_subscription_id ?? '')
  const [tenantId, setTenantId] = useState(connection.azure_tenant_id ?? '')
  const [clientId, setClientId] = useState(connection.azure_client_id ?? '')
  const [secretRef, setSecretRef] = useState('')

  const attach = useSetAzureCredentials(connection.id)
  const test = useTestConnection(connection.id)

  // The SP secret is never projected back (security), so on a reconnect the
  // field is blank but creds are already attached — allow a plain re-test
  // without forcing a re-paste + re-PUT.
  const credsAttached = Boolean(connection.azure_client_id)
  const guidsValid =
    GUID.test(subscriptionId.trim()) && GUID.test(tenantId.trim()) && GUID.test(clientId.trim())
  const hasSecret = secretRef.trim().length > 0
  const valid = guidsValid && (hasSecret || credsAttached)
  // Soft hint: IAM only grants aegion/azure/* — warn (don't block) on a name
  // outside that prefix so the operator isn't surprised by an AccessDenied.
  const secretPrefixWarn = hasSecret && !secretRef.trim().startsWith('aegion/azure/')

  const busy = attach.isPending || test.isPending
  const result = test.data
  const isConnected = connection.status === 'connected'

  // If the secret was re-pasted (or first attach), PUT then probe. If creds are
  // already attached and the field is untouched, skip the PUT and just re-test.
  const connect = () => {
    if (credsAttached && !hasSecret) {
      test.mutate(undefined)
      return
    }
    attach.mutate(
      {
        subscription_id: subscriptionId.trim(),
        tenant_id: tenantId.trim(),
        client_id: clientId.trim(),
        secret_ref: secretRef.trim(),
      },
      {
        onSuccess: () => test.mutate(undefined),
        // FXR-1: a 403 is surfaced once by the global bridge — skip the page toast.
        onError: (err) => {
          if (isAuthDegrade403(err)) return
          toastError(err instanceof ApiException ? err.message : 'Could not attach the service principal.')
        },
      },
    )
  }

  return (
    <Card className="overflow-hidden">
      <div
        className="px-5 py-3.5 flex items-center justify-between"
        style={{ borderBottom: '1px solid var(--color-line)' }}
      >
        <span className="text-xs font-semibold uppercase tracking-[0.18em] text-secondary">
          Grant access — read-only service principal
        </span>
        <span className="text-[10px] font-mono text-muted">Azure CLI</span>
      </div>

      <div className="p-5 space-y-5">
        <CodeBlock code={buildAzureSetup()} filename="aegion-connect-azure.sh" />

        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Field id="az-sub" label="Subscription ID" value={subscriptionId} onChange={setSubscriptionId}
            placeholder="cb2512df-2001-45e1-aea6-88e80fc00299" />
          <Field id="az-tenant" label="Tenant ID" value={tenantId} onChange={setTenantId}
            placeholder="1b700974-cfff-4516-b45f-f4f70af079dd" />
          <Field id="az-client" label="Client ID (appId)" value={clientId} onChange={setClientId}
            placeholder="d2a250a6-a748-4f29-b9e5-48f8e434da5c" />
          <div>
            <Field id="az-secret-ref" label="Secret reference (vault name)" value={secretRef} onChange={setSecretRef}
              placeholder={credsAttached ? '•••• stored — leave blank to keep' : 'aegion/azure/discovery-sp'} />
            {secretPrefixWarn && (
              <p className="mt-1 text-[10px] text-amber font-mono">
                Tip: store the secret under <span className="text-ink">aegion/azure/…</span> — that&apos;s the only prefix Aegion can read.
              </p>
            )}
          </div>
        </div>

        <p className="flex items-start gap-2 text-[11px] text-secondary">
          <IconInfoCircle size={15} className="text-cyan/70 mt-px shrink-0" />
          Run the commands above, then paste the SP&apos;s ids and the{' '}
          <span className="font-mono text-ink">vault secret name</span>. The client-secret stays in your
          vault — we store a reference only.
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
                {busy ? (
                  <span className="text-secondary">Probing service principal…</span>
                ) : result?.ok ? (
                  <span className="text-green flex items-center gap-1.5">{result.message}</span>
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
          {canOperate && (
            <Button variant="ghost" onClick={connect} disabled={!valid || busy} className="shrink-0">
              {busy ? <IconLoader2 size={14} className="animate-spin" /> : null}
              {isConnected ? 'Re-test' : 'Connect & test'}
            </Button>
          )}
        </div>
      </div>
    </Card>
  )
}
