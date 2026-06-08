import { isRouteErrorResponse, useRouteError } from 'react-router-dom'
import { IconAlertTriangle } from '@tabler/icons-react'

/** Catches render/loader errors so a data quirk degrades gracefully instead of white-screening. */
export function RouteErrorBoundary() {
  const error = useRouteError()
  const message = isRouteErrorResponse(error)
    ? `${error.status} ${error.statusText}`
    : error instanceof Error
      ? error.message
      : 'An unexpected error occurred.'

  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-bg text-ink p-8 text-center">
      <span className="font-mono text-xs uppercase tracking-[0.3em] text-cyan">Aegion SOC</span>
      <IconAlertTriangle size={34} className="text-pink" />
      <h1 className="font-display text-2xl font-bold">Something went wrong</h1>
      <p className="max-w-md text-sm font-mono text-secondary break-words">{message}</p>
      <button
        type="button"
        onClick={() => window.location.assign('/')}
        className="mt-1 px-4 h-9 rounded-xl text-xs font-bold text-cyan bg-cyan/10 border border-cyan/20 hover:bg-cyan/20 cursor-pointer"
      >
        Back to Overview
      </button>
    </div>
  )
}
