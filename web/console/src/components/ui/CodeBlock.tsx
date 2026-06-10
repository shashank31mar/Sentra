import { useState } from 'react'
import { IconCheck, IconCopy } from '@tabler/icons-react'

interface CodeBlockProps {
  code: string
  /** Shown on the right of the toolbar, e.g. `policy.cedar`. */
  filename?: string
  /** Optional toolbar content rendered on the left (e.g. language tabs). */
  toolbar?: React.ReactNode
}

/** Read-only code viewer with a line-number gutter and copy-to-clipboard. */
export function CodeBlock({ code, filename, toolbar }: CodeBlockProps) {
  const [copied, setCopied] = useState(false)
  // Defensive: `code` is typed as string, but live data can hand us a non-string
  // (object/number). Coerce so `.split` and rendering never throw.
  const text = typeof code === 'string' ? code : String(code ?? '')
  const lines = text.split('\n')

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard unavailable — no-op */
    }
  }

  return (
    <div className="rounded-2xl overflow-hidden" style={{ background: '#05090D', border: '1px solid var(--color-line)' }}>
      {/* Toolbar */}
      <div
        className="flex h-11 items-center justify-between px-4"
        style={{ background: '#070E14', borderBottom: '1px solid var(--color-line)' }}
      >
        <div className="flex items-center gap-3 min-w-0">
          <div className="flex gap-1.5 pr-1">
            <span className="h-2 w-2 rounded-full bg-pink/80" />
            <span className="h-2 w-2 rounded-full bg-amber/80" />
            <span className="h-2 w-2 rounded-full bg-green/80" />
          </div>
          {toolbar}
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {filename && <span className="font-mono text-[10px] text-muted hidden sm:inline">{filename}</span>}
          <button
            type="button"
            onClick={handleCopy}
            title="Copy to clipboard"
            className="flex items-center gap-1.5 px-2 py-1 rounded-md text-[11px] font-mono text-secondary hover:text-cyan hover:bg-white/5 transition-colors cursor-pointer"
          >
            {copied ? <IconCheck size={14} className="text-green" /> : <IconCopy size={14} />}
            {copied ? 'Copied' : 'Copy'}
          </button>
        </div>
      </div>

      {/* Code body */}
      <div className="overflow-auto scrollbar-thin" style={{ background: '#030708', maxHeight: '60vh' }}>
        <div className="flex min-w-max font-mono text-[13px] leading-relaxed">
          <div
            className="select-none text-right py-4 pr-3 pl-4 shrink-0"
            style={{ color: '#34454F', background: 'rgba(0,0,0,0.25)' }}
            aria-hidden
          >
            {lines.map((_, i) => (
              <div key={i}>{i + 1}</div>
            ))}
          </div>
          <pre className="py-4 px-4 text-secondary whitespace-pre">{text}</pre>
        </div>
      </div>
    </div>
  )
}
