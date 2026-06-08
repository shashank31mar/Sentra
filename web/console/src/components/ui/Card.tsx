import type { HTMLAttributes, ReactNode } from 'react'

interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode
  /** Accent border color (e.g. for danger cards). */
  accent?: 'default' | 'danger'
  glow?: boolean
}

const accentBorder: Record<NonNullable<CardProps['accent']>, string> = {
  default: '1px solid var(--color-line)',
  danger: '1px solid rgba(255,0,128,0.18)',
}

/** Panel card matching the canvas surface (#0B141C, rounded-2xl, hairline border). */
export function Card({ children, className = '', accent = 'default', glow = false, style, ...rest }: CardProps) {
  return (
    <div
      className={`rounded-2xl bg-surface-2 ${className}`}
      style={{
        border: accentBorder[accent],
        ...(glow ? { boxShadow: '0 0 60px -30px rgba(255,0,128,.5)' } : {}),
        ...style,
      }}
      {...rest}
    >
      {children}
    </div>
  )
}
