import type { ReactNode } from 'react'

interface PageHeaderProps {
  title: string
  subtitle?: string
  actions?: ReactNode
}

export function PageHeader({ title, subtitle, actions }: PageHeaderProps) {
  return (
    <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between mb-7">
      <div className="min-w-0">
        <h1 className="font-display text-2xl sm:text-3xl font-bold tracking-tight">{title}</h1>
        {subtitle && <p className="text-sm mt-1 text-secondary">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-3 shrink-0 flex-wrap">{actions}</div>}
    </div>
  )
}
