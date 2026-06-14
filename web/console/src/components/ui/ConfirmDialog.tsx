import type { ReactNode } from 'react'
import { Modal } from './Modal'
import { Button } from './Button'

interface ConfirmDialogProps {
  open: boolean
  title: ReactNode
  /** Body copy — usually the fail-secure / blast-radius message (§2.5). */
  message: ReactNode
  confirmLabel?: string
  cancelLabel?: string
  /** `danger` = destructive (detach/disable/delete); `primary` otherwise. */
  variant?: 'danger' | 'primary'
  /** Disable the confirm button + show busy state while the mutation runs. */
  busy?: boolean
  onConfirm: () => void
  onCancel: () => void
}

/** A focused confirm/cancel dialog over Modal (agent-policy-management T40/T42). */
export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  variant = 'danger',
  busy = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  return (
    <Modal
      open={open}
      onClose={onCancel}
      title={title}
      footer={
        <>
          <Button variant="ghost" onClick={onCancel} disabled={busy}>
            {cancelLabel}
          </Button>
          <Button variant={variant} onClick={onConfirm} disabled={busy}>
            {busy ? 'Working…' : confirmLabel}
          </Button>
        </>
      }
    >
      <div className="leading-relaxed">{message}</div>
    </Modal>
  )
}
