import { useState } from 'react';
import Modal from '../Modal';
import { emailAPI, getErrorMessage } from '../../api';
import { AlertCircle, Eye, EyeOff, Lock, Mail, Server } from '../icons';

const PROVIDERS = [
  { id: 'gmail', name: 'Gmail', sub: 'Gmail & Google Workspace', icon: Mail },
  { id: 'imap', name: 'Other provider', sub: 'Any IMAP mailbox (Fastmail, Zoho, iCloud…)', icon: Server },
];

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const HOST_RE = /^(?=.{3,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/i;

export default function ConnectEmailModal({ initialProvider = 'gmail', initialEmail = '', reconnect = false, onClose, onConnected }) {
  const [provider, setProvider] = useState(initialProvider);
  const [email, setEmail] = useState(initialEmail);
  const [password, setPassword] = useState('');
  const [host, setHost] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  const isGmail = provider === 'gmail';

  const validate = () => {
    if (!EMAIL_RE.test(email.trim())) return 'Enter a valid email address.';
    if (!password.trim()) return isGmail ? 'Paste your 16-letter Gmail App Password.' : 'Enter your password.';
    if (isGmail && !/^[a-zA-Z]{16}$/.test(password.replace(/\s+/g, ''))) {
      return 'That doesn’t look like a Gmail App Password — it should be 16 letters.';
    }
    if (!isGmail && !HOST_RE.test(host.trim())) return 'Enter your provider’s IMAP host, e.g. imap.fastmail.com.';
    return '';
  };

  const submit = async (e) => {
    e.preventDefault();
    const problem = validate();
    if (problem) { setError(problem); return; }
    setError('');
    setBusy(true);
    try {
      const res = await emailAPI.connect({
        provider,
        email: email.trim(),
        password,
        host: isGmail ? null : host.trim(),
      });
      setPassword('');
      onConnected(res.data);
    } catch (err) {
      setError(getErrorMessage(err, 'We couldn’t connect to your mailbox. Please try again.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title={reconnect ? 'Reconnect your email' : 'Connect your email'} onClose={busy ? () => {} : onClose}>
      <form className="auth-form" onSubmit={submit} noValidate>
        <fieldset className="provider-cards" disabled={busy}>
          <legend className="sr-only">Email provider</legend>
          {PROVIDERS.map((p) => (
            <label key={p.id} className={`provider-card ${provider === p.id ? 'is-selected' : ''}`}>
              <input type="radio" name="provider" value={p.id} checked={provider === p.id}
                onChange={() => { setProvider(p.id); setError(''); }} />
              <span className="provider-card__ic"><p.icon /></span>
              <span>
                <span className="provider-card__name">{p.name}</span>
                <span className="provider-card__sub">{p.sub}</span>
              </span>
            </label>
          ))}
        </fieldset>

        {isGmail ? (
          <div className="help-box">
            <strong>Use a Gmail App Password — never your Google password.</strong>
            <ol>
              <li>Turn on 2-Step Verification for your Google account.</li>
              <li>Create an App Password at{' '}
                <a href="https://myaccount.google.com/apppasswords" target="_blank" rel="noopener noreferrer">myaccount.google.com/apppasswords</a>.</li>
              <li>Paste the 16-letter code below. Make sure IMAP is enabled in Gmail settings.</li>
            </ol>
          </div>
        ) : (
          <div className="help-box">
            <strong>Use your provider’s IMAP details.</strong>
            <p>We connect over SSL/TLS on port 993. Many providers (iCloud, Yahoo, Fastmail) require an app-specific password for IMAP.</p>
          </div>
        )}

        {error && <div className="alert alert-error" role="alert"><AlertCircle /><span>{error}</span></div>}

        <div className="field">
          <label htmlFor="ce-email">Email address</label>
          <input id="ce-email" className="input" type="email" autoComplete="email" value={email}
            onChange={(e) => setEmail(e.target.value)} placeholder={isGmail ? 'you@gmail.com' : 'you@example.com'}
            disabled={busy} required />
        </div>

        {!isGmail && (
          <div className="field">
            <label htmlFor="ce-host">IMAP host</label>
            <input id="ce-host" className="input" value={host} onChange={(e) => setHost(e.target.value)}
              placeholder="imap.example.com" autoCapitalize="none" autoCorrect="off" spellCheck={false} disabled={busy} required />
          </div>
        )}

        <div className="field">
          <label htmlFor="ce-password">{isGmail ? 'App Password' : 'Password or app password'}</label>
          <div className="input-wrap">
            <input id="ce-password" className="input" type={showPw ? 'text' : 'password'} autoComplete="off"
              value={password} onChange={(e) => setPassword(e.target.value)}
              placeholder={isGmail ? 'abcd efgh ijkl mnop' : '••••••••'} style={{ paddingLeft: 13 }} disabled={busy} required />
            <button type="button" className="toggle" onClick={() => setShowPw((v) => !v)}
              aria-label={showPw ? 'Hide password' : 'Show password'}>
              {showPw ? <EyeOff /> : <Eye />}
            </button>
          </div>
        </div>

        <p className="fine-print"><Lock /> Verified before saving, then encrypted. Read-only access: we never send, delete, or mark mail as read.</p>

        <div className="form-actions">
          <button type="button" className="btn btn-ghost" onClick={onClose} disabled={busy}>Cancel</button>
          <button type="submit" className="btn btn-primary" disabled={busy}>
            {busy ? <><span className="spinner" /> Verifying credentials…</> : 'Connect & verify'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
