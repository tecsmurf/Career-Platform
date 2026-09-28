import { useEffect, useRef } from 'react';
import { Close } from './icons';

/**
 * Accessible modal: Esc to close, overlay click to close, focus moves in on
 * open and returns to the trigger on close, basic focus trapping.
 */
export default function Modal({ title, onClose, children, size }) {
  const ref = useRef(null);
  const prevFocus = useRef(null);

  useEffect(() => {
    prevFocus.current = document.activeElement;
    const el = ref.current;
    // focus first focusable element (or the dialog)
    const focusable = el?.querySelector(
      'input, select, textarea, button, [href], [tabindex]:not([tabindex="-1"])'
    );
    (focusable || el)?.focus();

    const onKey = (e) => {
      if (e.key === 'Escape') { e.stopPropagation(); onClose(); return; }
      if (e.key === 'Tab') {
        const items = el.querySelectorAll(
          'input, select, textarea, button:not([disabled]), [href], [tabindex]:not([tabindex="-1"])'
        );
        if (!items.length) return;
        const first = items[0];
        const last = items[items.length - 1];
        if (e.shiftKey && document.activeElement === first) { e.preventDefault(); last.focus(); }
        else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first.focus(); }
      }
    };
    document.addEventListener('keydown', onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', onKey);
      document.body.style.overflow = prevOverflow;
      prevFocus.current?.focus?.();
    };
  }, [onClose]);

  return (
    <div className="overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div
        className={`modal ${size === 'sm' ? 'modal--sm' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        ref={ref}
        tabIndex={-1}
      >
        {title && (
          <div className="modal__head">
            <h2>{title}</h2>
            <button className="icon-btn" onClick={onClose} aria-label="Close dialog"><Close /></button>
          </div>
        )}
        <div className="modal__body">{children}</div>
      </div>
    </div>
  );
}
