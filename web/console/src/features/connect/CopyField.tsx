import { useState } from 'react'
import { IconCheck, IconCopy } from '@tabler/icons-react'

interface CopyFieldProps {
  value: string
  label?: string
  hint?: string
}

/** Read-only mono field with a copy-to-clipboard affordance (external id, ARN). */
export function CopyField({ value, label, hint }: CopyFieldProps) {
  const [copied, setCopied] = useState(false)

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard unavailable — no-op */
    }
  }

  return (
    <div>
      {label && (
        <label className="text-[11px] font-medium text-secondary mb-1.5 flex items-center gap-1.5">
          {label}
          {hint && <span className="text-muted">{hint}</span>}
        </label>
      )}
      <div
        className="flex items-center gap-2 h-10 px-3 rounded-xl font-mono text-xs text-secondary"
        style={{ background: '#05090E', border: '1px solid var(--color-line)' }}
      >
        <span className="truncate">{value}</span>
        <button
          type="button"
          onClick={copy}
          aria-label={`Copy ${label ?? 'value'}`}
          className="ml-auto shrink-0 text-muted hover:text-cyan transition-colors cursor-pointer"
        >
          {copied ? <IconCheck size={15} className="text-green" /> : <IconCopy size={15} />}
        </button>
      </div>
    </div>
  )
}
