import { useEffect, useRef, type ReactNode } from 'react'

interface ModalProps {
  open: boolean
  onClose: () => void
  title: ReactNode
  children: ReactNode
  /** Footer actions (buttons). Rendered right-aligned. */
  footer?: ReactNode
  /** Max-width utility (default narrow dialog). */
  widthClass?: string
}

/**
 * Accessible modal dialog (agent-policy-management T40): focus-trap, ESC to
 * close, backdrop click to close, `role="dialog"` + `aria-modal`. Restores focus
 * to the previously-focused element on unmount.
 */
export function Modal({ open, onClose, title, children, footer, widthClass = 'max-w-lg' }: ModalProps) {
  const panelRef = useRef<HTMLDivElement>(null)
  const restoreRef = useRef<HTMLElement | null>(null)

  useEffect(() => {
    if (!open) return
    restoreRef.current = document.activeElement as HTMLElement | null

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation()
        onClose()
        return
      }
      if (e.key === 'Tab') {
        const focusables = panelRef.current?.querySelectorAll<HTMLElement>(
          'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])',
        )
        if (!focusables || focusables.length === 0) return
        const first = focusables[0]
        const last = focusables[focusables.length - 1]
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault()
          last.focus()
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault()
          first.focus()
        }
      }
    }
    document.addEventListener('keydown', onKey, true)
    // Focus the first focusable element in the panel.
    requestAnimationFrame(() => {
      panelRef.current
        ?.querySelector<HTMLElement>('button:not([disabled]), input, textarea, select, a[href]')
        ?.focus()
    })
    return () => {
      document.removeEventListener('keydown', onKey, true)
      restoreRef.current?.focus?.()
    }
  }, [open, onClose])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      // backdrop
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose()
      }}
    >
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" aria-hidden="true" />
      <div
        ref={panelRef}
        role="dialog"
        aria-modal="true"
        aria-label={typeof title === 'string' ? title : undefined}
        className={`relative w-full ${widthClass} rounded-2xl border bg-surface-1 shadow-2xl`}
        style={{ borderColor: 'var(--color-line)' }}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b" style={{ borderColor: 'var(--color-line)' }}>
          <h2 className="text-sm font-bold text-ink">{title}</h2>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="text-secondary hover:text-ink text-lg leading-none cursor-pointer"
          >
            ×
          </button>
        </div>
        <div className="px-5 py-4 text-sm text-secondary max-h-[70vh] overflow-y-auto scrollbar-thin">
          {children}
        </div>
        {footer && (
          <div className="flex items-center justify-end gap-2 px-5 py-4 border-t" style={{ borderColor: 'var(--color-line)' }}>
            {footer}
          </div>
        )}
      </div>
    </div>
  )
}
