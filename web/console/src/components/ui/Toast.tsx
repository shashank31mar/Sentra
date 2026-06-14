import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react'

type ToastKind = 'success' | 'error' | 'info'

interface ToastItem {
  id: number
  kind: ToastKind
  message: string
}

interface ToastApi {
  toast: (message: string, kind?: ToastKind) => void
  success: (message: string) => void
  error: (message: string) => void
}

const ToastContext = createContext<ToastApi | null>(null)

/** Imperative toast access: `const { success, error } = useToast()`. */
// eslint-disable-next-line react-refresh/only-export-components
export function useToast(): ToastApi {
  const ctx = useContext(ToastContext)
  if (!ctx) throw new Error('useToast must be used within <ToastProvider>')
  return ctx
}

const KIND_STYLE: Record<ToastKind, string> = {
  success: 'border-cyan/30 text-cyan',
  error: 'border-pink/30 text-pink',
  info: 'border-line text-secondary',
}

/** Mounts the toast region + provides the imperative API (agent-policy-management
 *  T40). Toasts auto-dismiss after 4s and stack bottom-right. */
export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const seq = useRef(0)

  const remove = useCallback((id: number) => {
    setItems((cur) => cur.filter((t) => t.id !== id))
  }, [])

  const toast = useCallback(
    (message: string, kind: ToastKind = 'info') => {
      const id = ++seq.current
      setItems((cur) => [...cur, { id, kind, message }])
      window.setTimeout(() => remove(id), 4000)
    },
    [remove],
  )

  const api: ToastApi = {
    toast,
    success: (m) => toast(m, 'success'),
    error: (m) => toast(m, 'error'),
  }

  return (
    <ToastContext.Provider value={api}>
      {children}
      <div className="fixed bottom-4 right-4 z-[60] flex flex-col gap-2" aria-live="polite" aria-atomic="true">
        {items.map((t) => (
          <div
            key={t.id}
            role="status"
            className={`min-w-[240px] max-w-sm rounded-xl border bg-surface-1 px-4 py-3 text-xs font-semibold shadow-2xl ${KIND_STYLE[t.kind]}`}
            onClick={() => remove(t.id)}
          >
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  )
}
