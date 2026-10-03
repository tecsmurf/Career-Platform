import { useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { authAPI, getErrorCode, getErrorMessage } from '../api';
import { useAuth } from '../hooks/useAuth';
import { useAuthConfig } from '../hooks/useAuthConfig';
import { useCountdown } from '../hooks/useCountdown';
import { useToast } from '../lib/toast';
import { formatCountdown, isCompleteCode, normalizeCode, retryAfterFrom } from '../lib/authCodes';
import AuthShell from '../components/AuthShell';
import { AlertCircle, Check, Mail } from '../components/icons';

/*
 * Reached from sign-up (code just sent) or from a sign-in with an unverified
 * address. Router state carries { email, sent, message, ticket }; the ticket
 * proves the password was just entered and is required by the server. Without
 * it (page opened directly, or the step expired) the user signs in again,
 * which emails a fresh code.
 */
export default function VerifyEmailPage() {
  const location = useLocation();
  const initial = location.state || {};
  const ticket = initial.ticket || '';
  const email = initial.email || '';
  const [code, setCode] = useState('');
  const [state, setState] = useState('idle'); // idle | submitting | success
  const [error, setError] = useState('');
  const [expired, setExpired] = useState(false);
  const [notice, setNotice] = useState(initial.message || '');
  const [sending, setSending] = useState(false);
  const config = useAuthConfig();
  const [left, startCountdown] = useCountdown(initial.sent ? config.resend_seconds : 0);
  const { loginWithToken } = useAuth();
  const { toast } = useToast();
  const navigate = useNavigate();

  const notNeeded = config.loaded && !config.failed && !config.email_verification;
  const busy = state !== 'idle';

  const handleError = (err, fallback) => {
    if (getErrorCode(err) === 'verification_expired') setExpired(true);
    setError(getErrorMessage(err, fallback));
  };

  const submit = async (e) => {
    e.preventDefault();
    if (busy || expired) return;
    setError('');
    if (!isCompleteCode(code)) { setError('Enter the 6-digit code from the email.'); return; }
    setState('submitting');
    try {
      const res = await authAPI.verifyEmail(ticket, code);
      setState('success');
      await loginWithToken(res.data.access_token);
      toast('Email verified. You’re signed in.', 'success');
      navigate('/dashboard', { replace: true });
    } catch (err) {
      setState('idle');
      setCode('');
      handleError(err, 'That code didn’t work. Please try again.');
    }
  };

  const resend = async () => {
    if (left > 0 || sending || expired) return;
    setError('');
    setSending(true);
    try {
      const res = await authAPI.resendVerification(ticket);
      setNotice(res.data.message);
      startCountdown(res.data.resend_after);
    } catch (err) {
      if (err?.response?.status === 429) startCountdown(retryAfterFrom(err));
      handleError(err, 'We couldn’t send a new code. Please try again.');
    } finally {
      setSending(false);
    }
  };

  if (notNeeded) {
    return (
      <AuthShell>
        <h1>No verification needed</h1>
        <p className="sub">This server doesn’t ask for email codes. You can sign in with your password.</p>
        <Link to="/login" className="btn btn-primary btn-block btn-lg">Go to sign in</Link>
      </AuthShell>
    );
  }

  if (!ticket) {
    return (
      <AuthShell>
        <h1>Verify your email</h1>
        <p className="sub">Sign in with your email and password — we’ll email you a 6-digit code to confirm your address.</p>
        <Link to="/login" className="btn btn-primary btn-block btn-lg">Go to sign in</Link>
        <p className="auth-alt">Forgot your password? <Link to="/forgot-password">Reset it</Link></p>
      </AuthShell>
    );
  }

  let label = 'Verify email';
  if (state === 'submitting') label = <><span className="spinner" /> Verifying…</>;
  else if (state === 'success') label = <><Check /> Verified</>;

  return (
    <AuthShell>
      <h1>Check your email</h1>
      <p className="sub">Enter the 6-digit code we sent to <span className="auth-sent-to">{email}</span>.</p>

      <form onSubmit={submit} className="auth-form" noValidate aria-busy={busy || undefined}>
        {notice && !error && <div className="alert alert-info" role="status"><Mail /><span>{notice}</span></div>}
        {error && (
          <div className="alert alert-error" role="alert"><AlertCircle />
            <span>{error}{expired && <> <Link to="/login" state={{ email }}>Sign in again</Link></>}</span>
          </div>
        )}

        <div className="field">
          <label htmlFor="code">Verification code</label>
          <input id="code" className="input input-code" type="text" inputMode="numeric" pattern="[0-9]*"
            autoComplete="one-time-code" value={code} placeholder="000000" disabled={expired}
            onChange={(e) => setCode(normalizeCode(e.target.value))} aria-describedby="code-hint" autoFocus required />
          <span id="code-hint" className="field-hint">Codes expire after {config.code_ttl_minutes} minutes and work once.</span>
        </div>

        <button type="submit" className="btn btn-primary btn-block btn-lg" disabled={busy || expired}>{label}</button>

        <div className="auth-resend">
          <span>Didn’t get it?</span>
          <button type="button" className="link-btn" onClick={resend} disabled={left > 0 || sending || expired}>
            {sending ? 'Sending…' : left > 0 ? `Resend code in ${formatCountdown(left)}` : 'Resend code'}
          </button>
        </div>
        <div className="auth-resend">
          <span>Wrong address?</span>
          <Link to="/register" className="link-btn">Sign up with the right one</Link>
        </div>
      </form>

      <p className="auth-alt"><Link to="/login">Back to sign in</Link></p>
    </AuthShell>
  );
}
