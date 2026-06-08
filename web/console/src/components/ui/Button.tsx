import type { ButtonHTMLAttributes, ReactNode } from 'react'

type Variant = 'primary' | 'ghost' | 'danger'

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  children: ReactNode
}

const VARIANTS: Record<Variant, string> = {
  primary: 'text-cyan bg-cyan/10 border border-cyan/20 hover:bg-cyan/20',
  ghost: 'text-secondary bg-surface-2 hover:text-cyan',
  danger: 'text-pink bg-pink/10 border border-pink/20 hover:bg-pink/20',
}

export function Button({ variant = 'primary', children, className = '', style, ...rest }: ButtonProps) {
  return (
    <button
      type="button"
      className={`inline-flex items-center justify-center gap-2 px-4 h-9 rounded-xl text-xs font-bold transition-all cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed ${VARIANTS[variant]} ${className}`}
      style={variant === 'ghost' ? { border: '1px solid var(--color-line)', ...style } : style}
      {...rest}
    >
      {children}
    </button>
  )
}
