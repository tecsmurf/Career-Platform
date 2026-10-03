import { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { authAPI, getErrorCode, getErrorMessage } from '../api';
import { useAuth } from '../hooks/useAuth';
import { useAuthConfig } from '../hooks/useAuthConfig';
import { useCountdown } from '../hooks/useCountdown';
import { useToast } from '../lib/toast';
import {
  formatCountdown, isCompleteCode, looksLikeEmail, normalizeCode, passwordProblem, retryAfterFrom,
} from '../lib/authCodes';
import AuthShell from '../components/AuthShell';
import { AlertCircle, Check, Eye, EyeOff, Mail } from '../components/icons';

/*
 * Two steps: "request" (email → a reset code is emailed) and "reset"
 * (code + new password → signed in; every other session ends).
 * The server binds codes to the reset ticket it returns, so the ticket is
 * kept (also in the history entry, so a reload keeps it) and sent back
 * with every resend and with the new password.
 */
export default function ForgotPasswordPage() {
  const location = useLocation();
  const saved = location.state || {};
  const [step, setStep] = useState(saved.ticket ? 'reset' : 'request');
  const [email, setEmail] = useState(saved.email || '');
  const [ticket, setTicket] = useState(saved.ticket || '');
  const [ticketEmail, setTicketEmail] = useState(saved.ticket ? (saved.email || '') : '');
  const [code, setCode] = useState('');
  const [password, setPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [state, setState] = useState('idle'); // idle | submitting | success
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const config = useAuthConfig();
  const [left, startCountdown] = useCountdown(0);
  const { loginWithToken } = useAuth();
  const { toast } = useToast();
  const navigate = useNavigate();

  const unavailable = config.loaded && !config.failed && !config.password_reset;
  const busy = state !== 'idle';

  const sendCode = async () => {
    setError('');
    if (!looksLikeEmail(email)) { setError('Enter the email address of your account.'); return false; }
    setState('submitting');
    const address = email.trim();
    try {
      const res = await authAPI.forgotPassword(address, ticketEmail === address ? ticket : undefined);
      setNotice(res.data.message);
      startCountdown(res.data.resend_after);
      setTicket(res.data.reset_ticket);
      setTicketEmail(address);
      navigate(location.pathname, { replace: true, state: { email: address, ticket: res.data.reset_ticket } });
      return true;
    } catch (err) {
      if (err?.response?.status === 429) startCountdown(retryAfterFrom(err));
      setError(getErrorMessage(err, 'We couldn’t send a reset code. Please try again.'));
      return false;
    } finally {
      setState('idle');
    }
  };

  const request = async (e) => {
    e.preventDefault();
    if (busy) return;
    if (await sendCode()) setStep('reset');
  };

  const resend = async () => {
    if (left > 0 || busy) return;
    await sendCode();
  };

  const reset = async (e) => {
    e.preventDefault();
    if (busy) return;
    setError('');
    if (!isCompleteCode(code)) { setError('Enter the 6-digit code from the email.'); return; }
    const problem = passwordProblem(password, confirm);
    if (problem) { setError(problem); return; }
    setState('submitting');
    try {
      const res = await authAPI.resetPassword(ticket, code, password);
      setState('success');
      await loginWithToken(res.data.access_token);
      toast('Password updated. You’re signed in, and other sessions were signed out.', 'success', 6000);
      navigate('/dashboard', { replace: true });
    } catch (err) {
      setState('idle');
      if (getErrorCode(err) === 'reset_expired') {
        setTicket('');
        setTicketEmail('');
        setStep('request');
        navigate(location.pathname, { replace: true, state: { email: email.trim() } });
      }
      setError(getErrorMessage(err, 'That didn’t work. Please try again.'));
    }
  };

  if (unavailable) {
    return (
      <AuthShell>
        <h1>Reset your password</h1>
        <p className="sub">Password reset by email isn’t set up on this server yet.</p>
        <div className="alert alert-info" role="status"><Mail />
          <span>Ask the site administrator to reset your password, or sign in if you remember it.</span>
        </div>
        <p className="auth-alt"><Link to="/login">Back to sign in</Link></p>
      </AuthShell>
    );
  }

  const alerts = (
    <>
      {notice && !error && <div className="alert alert-info" role="status"><Mail /><span>{notice}</span></div>}
      {error && <div className="alert alert-error" role="alert"><AlertCircle /><span>{error}</span></div>}
    </>
  );

  if (step === 'request') {
    return (
      <AuthShell>
        <h1>Reset your password</h1>
        <p className="sub">Enter your account email and we’ll send you a 6-digit code.</p>
        <form onSubmit={request} className="auth-form" noValidate aria-busy={busy || undefined}>
          {alerts}
          <div className="field">
            <label htmlFor="email">Email</label>
            <div className="input-wrap">
              <span className="lead-icon"><Mail /></span>
              <input id="email" className="input" type="email" autoComplete="email" value={email} autoFocus
                onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" required />
            </div>
          </div>
          <button type="submit" className="btn btn-primary btn-block btn-lg" disabled={busy || left > 0}>
            {busy ? <><span className="spinner" /> Sending…</> : left > 0 ? `Try again in ${formatCountdown(left)}` : 'Send reset code'}
          </button>
          {ticket && ticketEmail === email.trim() && (
            <div className="auth-resend">
              <span>Already have a code?</span>
              <button type="button" className="link-btn" onClick={() => { setError(''); setNotice(''); setStep('reset'); }}>
                Enter it
              </button>
            </div>
          )}
        </form>
        <p className="auth-alt">Remembered it? <Link to="/login">Sign in</Link></p>
      </AuthShell>
    );
  }

  let label = 'Set new password';
  if (state === 'submitting') label = <><span className="spinner" /> Saving…</>;
  else if (state === 'success') label = <><Check /> Password updated</>;

  return (
    <AuthShell>
      <h1>Choose a new password</h1>
      <p className="sub">Enter the code we sent to <span className="auth-sent-to">{ticketEmail || email.trim()}</span> and your new password.</p>

      <form onSubmit={reset} className="auth-form" noValidate aria-busy={busy || undefined}>
        {alerts}
        <div className="field">
          <label htmlFor="code">Reset code</label>
          <input id="code" className="input input-code" type="text" inputMode="numeric" pattern="[0-9]*"
            autoComplete="one-time-code" value={code} placeholder="000000" autoFocus
            onChange={(e) => setCode(normalizeCode(e.target.value))} aria-describedby="code-hint" required />
          <span id="code-hint" className="field-hint">Codes expire after {config.code_ttl_minutes} minutes and work once.</span>
        </div>

        <div className="field">
          <label htmlFor="new_password">New password</label>
          <div className="input-wrap">
            <input id="new_password" className="input" type={showPw ? 'text' : 'password'} autoComplete="new-password"
              value={password} onChange={(e) => setPassword(e.target.value)} placeholder="At least 6 characters"
              required minLength={6} style={{ paddingLeft: 13 }} />
            <button type="button" className="toggle" onClick={() => setShowPw((v) => !v)}
              aria-label={showPw ? 'Hide password' : 'Show password'}>
              {showPw ? <EyeOff /> : <Eye />}
            </button>
          </div>
        </div>

        <div className="field">
          <label htmlFor="confirm_password">Confirm new password</label>
          <input id="confirm_password" className="input" type={showPw ? 'text' : 'password'} autoComplete="new-password"
            value={confirm} onChange={(e) => setConfirm(e.target.value)} placeholder="Type it again" required />
        </div>

        <button type="submit" className="btn btn-primary btn-block btn-lg" disabled={busy}>{label}</button>

        <div className="auth-resend">
          <span>Didn’t get it?</span>
          <button type="button" className="link-btn" onClick={resend} disabled={left > 0 || busy}>
            {left > 0 ? `Resend code in ${formatCountdown(left)}` : 'Resend code'}
          </button>
        </div>
        <div className="auth-resend">
          <span>Wrong address?</span>
          <button type="button" className="link-btn"
            onClick={() => { setStep('request'); setCode(''); setError(''); setNotice(''); startCountdown(0); }}>
            Use a different email
          </button>
        </div>
      </form>

      <p className="auth-alt"><Link to="/login">Back to sign in</Link></p>
    </AuthShell>
  );
}
