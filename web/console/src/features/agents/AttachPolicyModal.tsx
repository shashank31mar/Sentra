import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Modal } from '../../components/ui/Modal'
import { Button } from '../../components/ui/Button'
import { usePolicies } from '../../lib/query/usePolicies'
import { useAttachPolicy } from '../../lib/query/useAgents'
import { useToast } from '../../components/ui/Toast'
import { policyNewPath } from '../../app/routes'
import type { PolicySummary } from '../../types/api'

interface AttachPolicyModalProps {
  open: boolean
  agentId: string
  agentName: string
  onClose: () => void
}

/**
 * Pick a policy to bind to an agent (agent-policy-management §6.1 Flow A).
 * Attach only writes THIS agent's binding — it never changes the policy or any
 * other agent. The policy whose `agent_id` matches is shown first; a mismatch
 * shows a non-blocking helper hint (allowed-tools may differ).
 */
export function AttachPolicyModal({ open, agentId, agentName, onClose }: AttachPolicyModalProps) {
  const navigate = useNavigate()
  const { success, error } = useToast()
  const policiesQuery = usePolicies({})
  const attach = useAttachPolicy(agentId)
  const [selected, setSelected] = useState<string | null>(null)

  const policies: PolicySummary[] = useMemo(() => {
    const all = policiesQuery.data?.pages.flatMap((p) => p.items) ?? []
    // Active first, then the policy authored for THIS agent surfaced to the top.
    return [...all].sort((a, b) => {
      const aMatch = a.agent_id === agentId ? 1 : 0
      const bMatch = b.agent_id === agentId ? 1 : 0
      if (aMatch !== bMatch) return bMatch - aMatch
      const aActive = a.status === 'active' ? 1 : 0
      const bActive = b.status === 'active' ? 1 : 0
      return bActive - aActive
    })
  }, [policiesQuery.data, agentId])

  // Pre-select the matching-agent policy when the list first loads.
  const effectiveSelected = selected ?? policies.find((p) => p.agent_id === agentId)?.policy_id ?? null
  const chosen = policies.find((p) => p.policy_id === effectiveSelected)
  const mismatch = chosen && chosen.agent_id && chosen.agent_id !== agentId

  const onConfirm = () => {
    if (!effectiveSelected) return
    attach.mutate(effectiveSelected, {
      onSuccess: () => {
        success(`${agentName} is now governed by ${chosen?.name ?? effectiveSelected}.`)
        onClose()
      },
      onError: () => error('Could not attach the policy. Please try again.'),
    })
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={`Attach a policy to ${agentName}`}
      footer={
        <>
          <Button variant="ghost" onClick={onClose} disabled={attach.isPending}>
            Cancel
          </Button>
          <Button variant="primary" onClick={onConfirm} disabled={!effectiveSelected || attach.isPending}>
            {attach.isPending ? 'Attaching…' : 'Attach Policy'}
          </Button>
        </>
      }
    >
      {policiesQuery.isLoading ? (
        <div className="text-xs text-muted">Loading policies…</div>
      ) : policies.length === 0 ? (
        <div className="space-y-3">
          <p>No policies exist yet.</p>
          <Button variant="primary" onClick={() => navigate(`${policyNewPath()}?agent_id=${encodeURIComponent(agentId)}&attach=1`)}>
            Create a policy for this agent
          </Button>
        </div>
      ) : (
        <div className="space-y-3">
          <div className="max-h-72 overflow-y-auto scrollbar-thin flex flex-col gap-1.5">
            {policies.map((p) => {
              const isSel = p.policy_id === effectiveSelected
              return (
                <button
                  key={p.policy_id}
                  type="button"
                  onClick={() => setSelected(p.policy_id)}
                  className={`flex items-center justify-between gap-3 px-3 py-2 rounded-xl border text-left transition-colors ${
                    isSel ? 'border-cyan/40 bg-cyan/10' : 'border-line bg-surface-2 hover:bg-surface-1'
                  }`}
                  style={!isSel ? { borderColor: 'var(--color-line)' } : undefined}
                >
                  <div className="min-w-0">
                    <div className="font-semibold text-ink truncate">{p.name}</div>
                    <div className="text-[11px] font-mono text-muted truncate">{p.policy_id}</div>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {p.agent_id === agentId && (
                      <span className="text-[10px] font-bold uppercase tracking-wide text-cyan">match</span>
                    )}
                    <span className={`text-[10px] font-mono uppercase ${p.status === 'active' ? 'text-cyan' : 'text-muted'}`}>
                      {p.status}
                    </span>
                  </div>
                </button>
              )
            })}
          </div>

          {mismatch && (
            <p className="text-[11px] text-amber-400 leading-relaxed">
              Authored for <span className="font-mono">{chosen?.agent_id}</span> — its allowed tools may
              not match <span className="font-mono">{agentId}</span>. Cloud identity resolves from this
              agent, so cross-cloud rules stay correct.
            </p>
          )}

          <button
            type="button"
            onClick={() => navigate(`${policyNewPath()}?agent_id=${encodeURIComponent(agentId)}&attach=1`)}
            className="text-[11px] text-cyan hover:underline"
          >
            + Create a new policy for this agent
          </button>
        </div>
      )}
    </Modal>
  )
}
