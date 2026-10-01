import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { getErrorMessage } from '../api';
import AuthShell from '../components/AuthShell';
import { AlertCircle, Eye, EyeOff, Mail } from '../components/icons';

export default function RegisterPage() {
  const [form, setForm] = useState({ full_name: '', email: '', password: '' });
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);
  const { register } = useAuth();
  const navigate = useNavigate();

  const update = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (form.password.length < 6) {
      setError('Password must be at least 6 characters.');
      return;
    }
    setLoading(true);
    try {
      await register(form.email, form.password, form.full_name);
      navigate('/dashboard');
    } catch (err) {
      setError(getErrorMessage(err, 'Registration failed. Please try again.'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthShell>
      <h1>Create your account</h1>
      <p className="sub">Start tracking your job search in minutes.</p>

      <form onSubmit={handleSubmit} className="auth-form" noValidate>
        {error && <div className="alert alert-error" role="alert"><AlertCircle /><span>{error}</span></div>}

        <div className="field">
          <label htmlFor="full_name">Full name</label>
          <input id="full_name" className="input" type="text" autoComplete="name"
            value={form.full_name} onChange={update('full_name')} placeholder="Alice Johnson" required />
        </div>

        <div className="field">
          <label htmlFor="email">Email</label>
          <div className="input-wrap">
            <span className="lead-icon"><Mail /></span>
            <input id="email" className="input" type="email" autoComplete="email"
              value={form.email} onChange={update('email')} placeholder="you@example.com" required />
          </div>
        </div>

        <div className="field">
          <label htmlFor="password">Password</label>
          <div className="input-wrap">
            <input id="password" className="input" type={showPw ? 'text' : 'password'} autoComplete="new-password"
              value={form.password} onChange={update('password')} placeholder="At least 6 characters" required minLength={6}
              style={{ paddingLeft: 13 }} />
            <button type="button" className="toggle" onClick={() => setShowPw((v) => !v)}
              aria-label={showPw ? 'Hide password' : 'Show password'}>
              {showPw ? <EyeOff /> : <Eye />}
            </button>
          </div>
        </div>

        <button type="submit" className="btn btn-primary btn-block btn-lg" disabled={loading}>
          {loading ? <><span className="spinner" /> Creating account…</> : 'Create account'}
        </button>
      </form>

      <p className="auth-alt">Already have an account? <Link to="/login">Sign in</Link></p>
    </AuthShell>
  );
}
