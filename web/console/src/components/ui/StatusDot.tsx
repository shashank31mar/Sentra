interface StatusDotProps {
  color: string
  pulse?: boolean
  size?: number
}

export function StatusDot({ color, pulse = false, size = 8 }: StatusDotProps) {
  return (
    <span
      className={`inline-block rounded-full shrink-0 ${pulse ? 'live-dot' : ''}`}
      style={{ width: size, height: size, background: color, boxShadow: `0 0 8px ${color}` }}
    />
  )
}
