import type { CSSProperties, ReactNode } from 'react'

export function Table({ children }: { children: ReactNode }) {
  return (
    <div className="overflow-x-auto scrollbar-thin">
      <table className="w-full text-left border-collapse text-sm">{children}</table>
    </div>
  )
}

export function THead({ children }: { children: ReactNode }) {
  return (
    <thead>
      <tr
        className="uppercase tracking-[0.18em] text-[10px] font-mono"
        style={{ color: '#51636E', background: 'rgba(0,0,0,0.25)', borderBottom: '1px solid var(--color-line)' }}
      >
        {children}
      </tr>
    </thead>
  )
}

export function Th({ children, className = '' }: { children?: ReactNode; className?: string }) {
  return <th className={`px-6 py-4 font-semibold ${className}`}>{children}</th>
}

export function TBody({ children }: { children: ReactNode }) {
  return <tbody className="divide-y divide-white/[0.04]">{children}</tbody>
}

export function Tr({
  children,
  onClick,
  id,
  className = '',
  style,
}: {
  children: ReactNode
  onClick?: () => void
  id?: string
  className?: string
  style?: CSSProperties
}) {
  return (
    <tr
      id={id}
      onClick={onClick}
      style={style}
      className={`transition-colors ${onClick ? 'cursor-pointer hover:bg-white/[0.025]' : ''} ${className}`}
    >
      {children}
    </tr>
  )
}

export function Td({
  children,
  className = '',
  style,
  colSpan,
}: {
  children?: ReactNode
  className?: string
  style?: CSSProperties
  colSpan?: number
}) {
  return (
    <td className={`px-6 py-4 align-middle ${className}`} style={style} colSpan={colSpan}>
      {children}
    </td>
  )
}
