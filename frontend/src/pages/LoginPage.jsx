import { useEffect, useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { getErrorMessage } from '../api';
import { useToast } from '../lib/toast';
import { RATE_LIMIT_MESSAGE, loginFailureKind, retryAfterSeconds } from '../lib/loginErrors';
import AuthShell from '../components/AuthShell';
import { AlertCircle, Check, Clock, Eye, EyeOff, Mail } from '../components/icons';

/*
 * States: idle → submitting → success
 *                           → invalid       (wrong email/password: inline error)
 *                           → rate_limited  (429: one toast + a short cooldown;
 *                                            never retried automatically)
 *                           → error         (network / server)
 */
export default function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [state, setState] = useState('idle');
  const [error, setError] = useState('');
  const [cooldown, setCooldown] = useState(0);
  const { login } = useAuth();
  const { toast } = useToast();
  const navigate = useNavigate();

  // Count the Retry-After window down; the button re-enables at zero. The user
  // decides when to try again — nothing is resent automatically.
  useEffect(() => {
    if (cooldown <= 0) return undefined;
    const t = setTimeout(() => setCooldown((s) => s - 1), 1000);
    return () => clearTimeout(t);
  }, [cooldown]);

  const submitting = state === 'submitting' || state === 'success';
  const blocked = submitting || cooldown > 0;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (blocked) return;
    setError('');
    setState('submitting');
    try {
      await login(email, password);
      setState('success');
      navigate('/dashboard');
    } catch (err) {
      const kind = loginFailureKind(err);
      setState(kind);
      if (kind === 'rate_limited') {
        setCooldown(retryAfterSeconds(err));
        toast(RATE_LIMIT_MESSAGE, 'warn', 6000, { key: 'login-rate-limit' });
      } else {
        setError(getErrorMessage(err, kind === 'invalid' ? 'Incorrect email or password.' : 'Login failed. Please try again.'));
      }
    }
  };

  let label = 'Sign in';
  if (state === 'submitting') label = <><span className="spinner" /> Signing in…</>;
  else if (state === 'success') label = <><Check /> Signed in</>;
  else if (cooldown > 0) label = <><Clock /> Try again in {cooldown}s</>;

  return (
    <AuthShell>
      <h1>Welcome back</h1>
      <p className="sub">Sign in to manage your job applications.</p>

      <form onSubmit={handleSubmit} className="auth-form" noValidate aria-busy={submitting || undefined}>
        {error && <div className="alert alert-error" role="alert"><AlertCircle /><span>{error}</span></div>}

        <div className="field">
          <label htmlFor="email">Email</label>
          <div className="input-wrap">
            <span className="lead-icon"><Mail /></span>
            <input id="email" className="input" type="email" autoComplete="email"
              value={email} onChange={(e) => { setEmail(e.target.value); if (state === 'invalid') setState('idle'); }} placeholder="you@example.com" required
              aria-invalid={state === 'invalid' || undefined} />
          </div>
        </div>

        <div className="field">
          <label htmlFor="password">Password</label>
          <div className="input-wrap">
            <input id="password" className="input" type={showPw ? 'text' : 'password'} autoComplete="current-password"
              value={password} onChange={(e) => { setPassword(e.target.value); if (state === 'invalid') setState('idle'); }} placeholder="••••••••" required style={{ paddingLeft: 13 }}
              aria-invalid={state === 'invalid' || undefined} />
            <button type="button" className="toggle" onClick={() => setShowPw((v) => !v)}
              aria-label={showPw ? 'Hide password' : 'Show password'}>
              {showPw ? <EyeOff /> : <Eye />}
            </button>
          </div>
        </div>

        <button type="submit" className="btn btn-primary btn-block btn-lg" disabled={blocked}>
          {label}
        </button>
      </form>

      <p className="auth-alt">Don’t have an account? <Link to="/register">Create one</Link></p>
    </AuthShell>
  );
}
