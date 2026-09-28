import { createContext, useContext, useState, useCallback } from 'react';
import { CheckCircle, AlertCircle, Sparkle, Close } from '../components/icons';

const ToastCtx = createContext(null);
const ICONS = { success: CheckCircle, error: AlertCircle, info: Sparkle };

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const dismiss = useCallback((id) => {
    setToasts((t) => t.filter((x) => x.id !== id));
  }, []);

  const toast = useCallback((message, type = 'info', ttl = 4000) => {
    const id = Math.random().toString(36).slice(2);
    setToasts((t) => [...t, { id, message, type }]);
    if (ttl) setTimeout(() => dismiss(id), ttl);
  }, [dismiss]);

  return (
    <ToastCtx.Provider value={{ toast }}>
      {children}
      <div className="toasts" role="region" aria-live="polite" aria-label="Notifications">
        {toasts.map((t) => {
          const Icon = ICONS[t.type] || Sparkle;
          return (
            <div key={t.id} className={`toast toast--${t.type}`} role="status">
              <span className="tic"><Icon /></span>
              <span>{t.message}</span>
              <button className="toast__close" onClick={() => dismiss(t.id)} aria-label="Dismiss">
                <Close />
              </button>
            </div>
          );
        })}
      </div>
    </ToastCtx.Provider>
  );
}

export function useToast() {
  const ctx = useContext(ToastCtx);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx;
}
