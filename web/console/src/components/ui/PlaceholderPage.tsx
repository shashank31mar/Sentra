interface PlaceholderPageProps {
  title: string
}

/** Temporary stand-in until each screen is implemented in M4. */
export function PlaceholderPage({ title }: PlaceholderPageProps) {
  return (
    <div className="flex h-[70vh] flex-col items-center justify-center gap-2 text-center">
      <span className="font-mono text-xs uppercase tracking-[0.3em] text-cyan">Aegion SOC</span>
      <h1 className="font-display text-2xl font-bold text-ink">{title}</h1>
      <p className="text-sm text-secondary">Screen coming up in Milestone 4.</p>
    </div>
  )
}
