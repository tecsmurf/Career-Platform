import { createContext, useContext, useState, useCallback, useRef } from 'react';
import { CheckCircle, AlertCircle, Sparkle, Close, Clock } from '../components/icons';

const ToastCtx = createContext(null);
const ICONS = { success: CheckCircle, error: AlertCircle, info: Sparkle, warn: Clock };

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);
  const timers = useRef(new Map());

  const dismiss = useCallback((id) => {
    clearTimeout(timers.current.get(id));
    timers.current.delete(id);
    setToasts((t) => t.filter((x) => x.id !== id));
  }, []);

  // `options.key`: a toast with the same key replaces the previous one instead
  // of stacking (e.g. repeated rate-limit notices), and its timer restarts.
  const toast = useCallback((message, type = 'info', ttl = 4000, options = {}) => {
    const id = options.key ? `k:${options.key}` : Math.random().toString(36).slice(2);
    clearTimeout(timers.current.get(id));
    setToasts((t) => [...t.filter((x) => x.id !== id), { id, message, type }]);
    if (ttl) timers.current.set(id, setTimeout(() => dismiss(id), ttl));
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
