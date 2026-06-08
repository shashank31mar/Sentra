import { IconAlertTriangle, IconInbox, IconLoader2 } from '@tabler/icons-react'
import type { ReactNode } from 'react'
import { ApiException } from '../../lib/http'

export function LoadingState({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-secondary">
      <IconLoader2 size={26} className="animate-spin text-cyan" />
      <span className="text-sm font-mono">{label}</span>
    </div>
  )
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message =
    error instanceof ApiException
      ? `${error.message}${error.errorCode ? ` (${error.errorCode})` : ''}`
      : 'Something went wrong.'
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-center">
      <IconAlertTriangle size={26} className="text-pink" />
      <span className="text-sm text-secondary max-w-sm">{message}</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-1 px-3 h-8 rounded-lg text-xs font-medium text-cyan bg-cyan/10 hover:bg-cyan/20 transition-colors cursor-pointer"
        >
          Retry
        </button>
      )}
    </div>
  )
}

export function EmptyState({ label = 'Nothing here yet.', icon }: { label?: string; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16 text-secondary">
      {icon ?? <IconInbox size={26} className="text-faint" />}
      <span className="text-sm font-mono">{label}</span>
    </div>
  )
}

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse rounded-md bg-white/5 ${className}`} />
}
