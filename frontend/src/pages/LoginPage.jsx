import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { getErrorMessage } from '../api';
import AuthShell from '../components/AuthShell';
import { AlertCircle, Eye, EyeOff, Mail } from '../components/icons';

export default function LoginPage() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { login } = useAuth();
  const navigate = useNavigate();

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setLoading(true);
    try {
      await login(email, password);
      navigate('/dashboard');
    } catch (err) {
      setError(getErrorMessage(err, 'Login failed. Please try again.'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthShell>
      <h1>Welcome back</h1>
      <p className="sub">Sign in to manage your job applications.</p>

      <form onSubmit={handleSubmit} className="auth-form" noValidate>
        {error && <div className="alert alert-error"><AlertCircle /><span>{error}</span></div>}

        <div className="field">
          <label htmlFor="email">Email</label>
          <div className="input-wrap">
            <span className="lead-icon"><Mail /></span>
            <input id="email" className="input" type="email" autoComplete="email"
              value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@example.com" required />
          </div>
        </div>

        <div className="field">
          <label htmlFor="password">Password</label>
          <div className="input-wrap">
            <input id="password" className="input" type={showPw ? 'text' : 'password'} autoComplete="current-password"
              value={password} onChange={(e) => setPassword(e.target.value)} placeholder="••••••••" required style={{ paddingLeft: 13 }} />
            <button type="button" className="toggle" onClick={() => setShowPw((v) => !v)}
              aria-label={showPw ? 'Hide password' : 'Show password'}>
              {showPw ? <EyeOff /> : <Eye />}
            </button>
          </div>
        </div>

        <button type="submit" className="btn btn-primary btn-block" disabled={loading}>
          {loading ? <span className="spinner" /> : 'Sign in'}
        </button>
      </form>

      <p className="auth-alt">Don’t have an account? <Link to="/register">Create one</Link></p>
    </AuthShell>
  );
}
