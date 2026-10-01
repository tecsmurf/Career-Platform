import { useState } from 'react';
import Modal from './Modal';
import { AlertTriangle } from './icons';

export default function ConfirmDialog({
  title = 'Are you sure?',
  message,
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  onConfirm,
  onCancel,
  children,
}) {
  const [busy, setBusy] = useState(false);

  const handleConfirm = async () => {
    setBusy(true);
    try {
      await onConfirm();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal onClose={busy ? () => {} : onCancel} size="sm">
      <div className="confirm__ic"><AlertTriangle /></div>
      <h2 style={{ fontSize: 18 }}>{title}</h2>
      {message && <p className="confirm__msg">{message}</p>}
      {children}
      <div className="form-actions" style={{ marginTop: 22 }}>
        <button className="btn btn-ghost" onClick={onCancel} disabled={busy}>{cancelLabel}</button>
        <button className="btn btn-danger" onClick={handleConfirm} disabled={busy}>
          {busy ? <span className="spinner" /> : confirmLabel}
        </button>
      </div>
    </Modal>
  );
}
