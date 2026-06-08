interface SegmentedControlProps<T extends string> {
  options: readonly { value: T; label: string }[]
  value: T
  onChange: (value: T) => void
}

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
}: SegmentedControlProps<T>) {
  return (
    <div
      className="flex items-center p-1 rounded-xl text-xs font-medium bg-surface-2"
      style={{ border: '1px solid var(--color-line)' }}
    >
      {options.map((opt) => {
        const active = opt.value === value
        return (
          <button
            key={opt.value}
            type="button"
            onClick={() => onChange(opt.value)}
            className="px-3 py-1.5 rounded-lg cursor-pointer transition-colors"
            style={active ? { background: 'rgba(15,255,255,0.12)', color: '#0FFFFF' } : { color: '#8DA2AE' }}
          >
            {opt.label}
          </button>
        )
      })}
    </div>
  )
}
