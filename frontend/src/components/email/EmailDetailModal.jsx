import { useEffect, useState } from 'react';
import Modal from '../Modal';
import { emailAPI, getErrorMessage } from '../../api';
import { AlertCircle, Shield } from '../icons';
import { categoryInfo, confidenceInfo, formatDateTime } from '../../lib/emailUi';

/**
 * Shows an imported email as PLAIN TEXT only. The backend never stores HTML;
 * React escapes the text, links are not auto-linked and no remote content
 * (images, tracking pixels) is ever loaded.
 */
export default function EmailDetailModal({ emailId, onClose }) {
  const [state, setState] = useState({ loading: true, error: '', email: null });

  useEffect(() => {
    let alive = true;
    emailAPI.getMessage(emailId)
      .then((res) => alive && setState({ loading: false, error: '', email: res.data }))
      .catch((err) => alive && setState({ loading: false, error: getErrorMessage(err, 'Could not load this email.'), email: null }));
    return () => { alive = false; };
  }, [emailId]);

  const e = state.email;
  const cat = e ? categoryInfo(e.category) : null;

  return (
    <Modal title="Email" onClose={onClose}>
      {state.loading && <div className="email-loading"><span className="spinner" /> Loading email…</div>}
      {state.error && <div className="alert alert-error"><AlertCircle /><span>{state.error}</span></div>}
      {e && (
        <div className="email-detail">
          <h3 className="email-detail__subject">{e.subject || '(no subject)'}</h3>
          <div className="email-detail__meta">
            <span><b>{e.sender_name || e.sender_email}</b>{e.sender_name && e.sender_email ? <span className="dim"> &lt;{e.sender_email}&gt;</span> : null}</span>
            <span className="dim">{formatDateTime(e.received_at)}</span>
          </div>
          <div className="email-detail__tags">
            <span className="badge" style={{ '--badge-color': cat.color }}>{cat.label}</span>
            {e.confidence != null && <span className={`conf conf--${confidenceInfo(e.confidence).level}`}>{confidenceInfo(e.confidence).label}</span>}
          </div>
          <div className="email-body" tabIndex={0} aria-label="Email text">{e.body_text || e.snippet || '(This email has no text content.)'}</div>
          <p className="fine-print"><Shield /> Shown as plain text. Links, images and scripts from emails are never loaded.</p>
        </div>
      )}
    </Modal>
  );
}
