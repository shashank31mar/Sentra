import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  IconCheck,
  IconLock,
  IconShieldLock,
  IconArrowRight,
  IconLoader2,
  IconX,
  IconCloudCheck,
} from '@tabler/icons-react'
import { PageHeader } from '../../components/ui/PageHeader'
import { Card } from '../../components/ui/Card'
import { Button } from '../../components/ui/Button'
import { ErrorState } from '../../components/ui/states'
import { useToast } from '../../components/ui/Toast'
import { AZURE_DEFAULT_SCOPES, CLOUD_OPTIONS } from './cloudCatalog'
import { GrantAccessCard } from './GrantAccessCard'
import { GrantAzureAccessCard } from './GrantAzureAccessCard'
import {
  useConnection,
  useConnections,
  useCreateConnection,
  useRemoveConnection,
  useScanConnection,
} from '../../lib/query/useConnections'
import { useCan } from '../../lib/query/useMe'
import { ApiException } from '../../lib/http'
import { importPath } from '../../app/routes'
import type { CloudProvider } from '../../types/enums'
import type { CloudConnection } from '../../types/api'

type StepId = 1 | 2 | 3
const STEPS: { id: StepId; label: string }[] = [
  { id: 1, label: 'Choose cloud' },
  { id: 2, label: 'Grant access' },
  { id: 3, label: 'Test & scan' },
]

function Stepper({ current }: { current: StepId }) {
  return (
    <div className="flex items-center gap-3 mb-7 flex-wrap">
      {STEPS.map((s, i) => {
        const done = s.id < current
        const active = s.id === current
        return (
          <div key={s.id} className="flex items-center gap-3">
            <div className="flex items-center gap-2.5">
              <span
                className="h-7 w-7 rounded-full grid place-items-center text-xs font-bold font-display"
                style={
                  done
                    ? { background: '#22E58B', color: '#010B13' }
                    : active
                      ? { background: '#0FFFFF', color: '#010B13' }
                      : { border: '1px solid var(--color-line)', color: '#8DA2AE' }
                }
              >
                {done ? <IconCheck size={14} /> : s.id}
              </span>
              <span className={`text-sm font-medium ${active || done ? 'text-ink' : 'text-secondary'}`}>
                {s.label}
              </span>
            </div>
            {i < STEPS.length - 1 && (
              <span
                className="h-px w-10 hidden sm:block"
                style={{ background: s.id < current ? 'rgba(15,255,255,0.4)' : 'var(--color-line)' }}
              />
            )}
          </div>
        )
      })}
    </div>
  )
}

/**
 * Connect Account wizard (feature.md §13, connections-api-spec §6): pick a cloud
 * → deploy a read-only cross-account role → test → scan, then hand off to the
 * Import review (`/import?connection=…`). v1 ships AWS; Azure/GCP are previewed.
 */
export function ConnectAccountPage() {
  const navigate = useNavigate()
  const { error: toastError } = useToast()
  const connections = useConnections()
  // G2.6: create/edit/delete a connection is admin (connections.write); the
  // test/scan probes are editor (connections.operate). Read/preview stays visible.
  const can = useCan()
  const canWrite = can('connections.write')
  const canOperate = can('connections.operate')

  const [connectionId, setConnectionId] = useState<string | null>(null)
  const create = useCreateConnection()
  const scan = useScanConnection(connectionId ?? '')
  const remove = useRemoveConnection()

  // Live connection object (reflects test/scan writes); falls back to the
  // create response before the first detail fetch resolves.
  const connectionQuery = useConnection(connectionId ?? undefined)
  const connection = connectionQuery.data ?? create.data ?? null

  const current: StepId = !connection ? 1 : connection.status === 'connected' ? 3 : 2

  // Connected accounts keyed by provider — drives the per-tile "Connected"
  // badge and the resume-to-review shortcut (bug: a connected Bedrock account
  // showed no status on the picker).
  const connectedByProvider = useMemo(() => {
    const map = new Map<CloudProvider, CloudConnection>()
    for (const c of connections.data?.connections ?? []) {
      if (c.status === 'connected') map.set(c.cloud_provider, c)
    }
    return map
  }, [connections.data])

  // (Re)choose the cloud in the wizard. Switching clouds abandons the
  // half-set-up record so the picker never gets stuck on the first choice
  // (bug: couldn't pick Azure after AWS and vice versa). A fully-connected
  // account is kept — switching just clears the local selection.
  const chooseCloud = (provider: CloudProvider) => {
    if (create.isPending || remove.isPending) return
    if (connection?.cloud_provider === provider) return // already selected
    const abandoned = connectionId
    const wasConnected = connection?.status === 'connected'
    setConnectionId(null)
    create.reset()
    if (abandoned && !wasConnected) remove.mutate(abandoned)
    create.mutate(provider, {
      onSuccess: (conn) => setConnectionId(conn.id),
      onError: (err) =>
        toastError(err instanceof ApiException ? err.message : 'Could not start a connection.'),
    })
  }

  // Tile click: resume an already-connected account (→ review), else (re)choose
  // the cloud in the wizard.
  const onChooseTile = (provider: CloudProvider) => {
    const connected = connectedByProvider.get(provider)
    if (connected && connected.id !== connection?.id) {
      navigate(importPath(connected.id))
      return
    }
    chooseCloud(provider)
  }

  const connectAndScan = () => {
    if (!connection || connection.status !== 'connected') return
    scan.mutate(undefined, {
      onSuccess: () => navigate(importPath(connection.id)),
      onError: (err) =>
        toastError(err instanceof ApiException ? err.message : 'Scan could not be started.'),
    })
  }

  // Abandon the in-progress connection and re-enable the cloud picker. Deletes
  // the half-set-up record so retries don't leave orphaned 'connecting' rows.
  const startOver = () => {
    const abandoned = connectionId
    setConnectionId(null)
    create.reset()
    if (abandoned) remove.mutate(abandoned)
  }

  // Surface an already-connected account so operators can jump straight to review.
  const existingConnected = connections.data?.connections.find(
    (c) => c.status === 'connected' && c.id !== connection?.id,
  )

  // Least-privilege scopes for the reassurance panel — live values once a
  // connection exists, else the per-provider defaults the credential will request.
  const scopes =
    connection?.scopes ??
    (connection?.cloud_provider === 'azure'
      ? AZURE_DEFAULT_SCOPES
      : ['bedrock:ListAgents', 'bedrock:GetAgent', 'lambda:GetFunction'])

  return (
    <div className="p-4 sm:p-6 lg:p-8">
      <PageHeader
        title="Connect a cloud account"
        subtitle="Grant Aegion read-only access to discover the AI agents in your account. Nothing is modified — we only list agents and introspect their tools."
        actions={
          <span className="inline-flex items-center gap-1.5 text-[11px] font-mono text-secondary">
            <IconLock size={14} className="text-cyan/70" /> Read-only · least-privilege
          </span>
        }
      />

      {existingConnected && !connection && (
        <Card className="px-5 py-3.5 mb-6 flex items-center justify-between gap-3 flex-wrap">
          <span className="flex items-center gap-2.5 text-sm text-secondary">
            <IconCloudCheck size={18} className="text-green" />
            <span className="text-ink font-medium">{existingConnected.account_ref ?? existingConnected.id}</span>
            is already connected.
          </span>
          <Button variant="ghost" onClick={() => navigate(importPath(existingConnected.id))}>
            Review agents <IconArrowRight size={14} />
          </Button>
        </Card>
      )}

      <Stepper current={current} />

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          {/* Step 1 — cloud picker */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            {CLOUD_OPTIONS.map((opt) => {
              const selected = connection?.cloud_provider === opt.provider
              const isConnected = connectedByProvider.has(opt.provider)
              const Icon = opt.icon
              return (
                <button
                  key={opt.provider}
                  type="button"
                  // Only disabled while a create/abandon is in flight, the
                  // provider isn't shipped yet, or the operator lacks write. A
                  // connected tile is still clickable (navigation to review), but
                  // starting a NEW connection requires connections.write.
                  disabled={
                    !opt.available ||
                    create.isPending ||
                    remove.isPending ||
                    (!canWrite && !connectedByProvider.has(opt.provider))
                  }
                  onClick={() => onChooseTile(opt.provider)}
                  className="relative text-left p-4 rounded-2xl transition-colors disabled:cursor-not-allowed enabled:hover:border-cyan/40 enabled:cursor-pointer"
                  style={{
                    background: selected ? 'rgba(15,255,255,0.06)' : 'var(--color-surface-2)',
                    border: `1px solid ${
                      selected
                        ? 'rgba(15,255,255,0.4)'
                        : isConnected
                          ? 'rgba(34,229,139,0.4)'
                          : 'var(--color-line)'
                    }`,
                    opacity: opt.available ? 1 : 0.55,
                  }}
                >
                  {(selected || isConnected) && (
                    <span
                      className="absolute top-3 right-3 h-5 w-5 rounded-full grid place-items-center"
                      style={{ background: selected ? '#0FFFFF' : '#22E58B' }}
                    >
                      <IconCheck size={12} className="text-[#010B13]" />
                    </span>
                  )}
                  <Icon size={26} style={{ color: opt.color }} />
                  <div className="mt-3 text-sm font-semibold text-ink">{opt.name}</div>
                  <div className="text-[11px] text-secondary mt-0.5">{opt.detail}</div>
                  <span
                    className="mt-2 inline-block text-[9px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded font-mono"
                    style={
                      isConnected
                        ? { color: '#22E58B', background: 'rgba(34,229,139,0.16)', border: '1px solid rgba(34,229,139,0.4)' }
                        : opt.available
                          ? { color: '#22E58B', background: 'rgba(34,229,139,0.1)', border: '1px solid rgba(34,229,139,0.25)' }
                          : { color: '#8DA2AE', background: 'rgba(255,255,255,0.04)', border: '1px solid var(--color-line)' }
                    }
                  >
                    {isConnected ? 'Connected' : opt.available ? 'Available' : 'Coming soon'}
                  </span>
                </button>
              )
            })}
          </div>

          {/* Step 2 — grant access */}
          {create.isPending && (
            <Card className="p-8 flex items-center justify-center gap-3 text-secondary">
              <IconLoader2 size={20} className="animate-spin text-cyan" />
              <span className="text-sm font-mono">Preparing your connection…</span>
            </Card>
          )}
          {connectionQuery.isError && (
            <Card className="p-2">
              <ErrorState error={connectionQuery.error} onRetry={() => connectionQuery.refetch()} />
            </Card>
          )}
          {connection &&
            (connection.cloud_provider === 'azure' ? (
              <GrantAzureAccessCard connection={connection} canOperate={canOperate} />
            ) : (
              <GrantAccessCard connection={connection} canOperate={canOperate} />
            ))}

          {/* Step 3 — connect & scan. The combined button triggers a scan but only
              makes sense after a create, so it requires connections.write — an
              operate-only editor would hit a server 403 on the create it can't do. */}
          {connection && (
            <div className="flex items-center justify-between gap-3">
              <Button variant="ghost" onClick={startOver} disabled={scan.isPending}>
                Use a different account
              </Button>
              {canWrite && (
                <Button
                  onClick={connectAndScan}
                  disabled={connection.status !== 'connected' || scan.isPending}
                >
                  {scan.isPending ? <IconLoader2 size={14} className="animate-spin" /> : null}
                  Connect &amp; scan <IconArrowRight size={14} />
                </Button>
              )}
            </div>
          )}
        </div>

        {/* Reassurance sidebar */}
        <aside className="space-y-4">
          <Card className="p-5">
            <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.18em] text-secondary mb-4">
              <IconShieldLock size={16} className="text-cyan" /> What we can access
            </div>
            <ul className="space-y-3 text-xs">
              {scopes.map((scope) => (
                <li key={scope} className="flex items-start gap-2.5">
                  <IconCheck size={15} className="text-green mt-px shrink-0" />
                  <span className="text-secondary font-mono">{scope}</span>
                </li>
              ))}
              <li className="flex items-start gap-2.5">
                <IconX size={15} className="text-pink mt-px shrink-0" />
                <span className="text-secondary">No write, invoke, or data-plane access</span>
              </li>
              <li className="flex items-start gap-2.5">
                <IconX size={15} className="text-pink mt-px shrink-0" />
                <span className="text-secondary">No changes to your agents or runtime</span>
              </li>
            </ul>
          </Card>

          <Card className="p-5">
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-secondary mb-3">
              How import works
            </div>
            <ol className="space-y-3 text-xs text-secondary">
              <li className="flex gap-2.5"><span className="font-mono text-cyan">1</span> Connect &amp; scan (read-only)</li>
              <li className="flex gap-2.5"><span className="font-mono text-cyan">2</span> Review discovered agents + tools</li>
              <li className="flex gap-2.5"><span className="font-mono text-cyan">3</span> Import → canonical id + seeded policy</li>
              <li className="flex gap-2.5"><span className="font-mono text-pink">4</span> Deploy SDK → governed (validate seen)</li>
            </ol>
            <p
              className="mt-4 pt-3 text-[11px] text-muted font-mono"
              style={{ borderTop: '1px solid var(--color-line)' }}
            >
              Secrets stay in your vault · we keep a reference only.
            </p>
          </Card>
        </aside>
      </div>
    </div>
  )
}
