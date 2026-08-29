import { useState, useEffect } from 'react';
import { useAuth } from '../hooks/useAuth';
import { jobsAPI, emailAPI, authAPI } from '../api';
import JobForm from '../components/JobForm';
import JobCard from '../components/JobCard';

const STATUS_OPTIONS = ['all', 'applied', 'interviewing', 'offer', 'rejected', 'withdrawn'];

export default function DashboardPage() {
  const { user, logout } = useAuth();
  const [jobs, setJobs] = useState([]);
  const [stats, setStats] = useState({});
  const [filter, setFilter] = useState('all');
  const [search, setSearch] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [editingJob, setEditingJob] = useState(null);
  const [loading, setLoading] = useState(true);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState(null);

  // Email settings state
  const [showEmailSettings, setShowEmailSettings] = useState(false);
  const [emailSettings, setEmailSettings] = useState({ email_user: '', email_app_password: '', email_host: 'imap.gmail.com' });
  const [emailConfigured, setEmailConfigured] = useState(false);
  const [savingEmail, setSavingEmail] = useState(false);
  const [emailMsg, setEmailMsg] = useState('');

  const fetchJobs = async () => {
    setLoading(true);
    try {
      const params = { page, limit: 12 };
      if (filter !== 'all') params.status = filter;
      if (search) params.search = search;
      const res = await jobsAPI.list(params);
      setJobs(res.data.data);
      setTotalPages(res.data.pages);
    } catch (err) {
      console.error('Failed to load jobs', err);
    } finally {
      setLoading(false);
    }
  };

  const fetchStats = async () => {
    try {
      const res = await jobsAPI.stats();
      setStats(res.data);
    } catch (err) {
      console.error('Failed to load stats', err);
    }
  };

  const fetchEmailSettings = async () => {
    try {
      const res = await authAPI.getEmailSettings();
      setEmailConfigured(res.data.is_configured);
      if (res.data.email_user) {
        setEmailSettings(prev => ({ ...prev, email_user: res.data.email_user, email_host: res.data.email_host }));
      }
    } catch (err) {
      console.error('Failed to load email settings', err);
    }
  };

  useEffect(() => { fetchJobs(); }, [filter, search, page]);
  useEffect(() => { fetchStats(); fetchEmailSettings(); }, []);

  const handleCreate = async (data) => {
    await jobsAPI.create(data);
    setShowForm(false);
    fetchJobs();
    fetchStats();
  };

  const handleUpdate = async (data) => {
    await jobsAPI.update(editingJob.id, data);
    setEditingJob(null);
    fetchJobs();
    fetchStats();
  };

  const handleDelete = async (id) => {
    if (!confirm('Delete this job application?')) return;
    await jobsAPI.delete(id);
    fetchJobs();
    fetchStats();
  };

  const handleEmailSync = async () => {
    if (!emailConfigured) {
      setShowEmailSettings(true);
      return;
    }
    setSyncing(true);
    setSyncResult(null);
    try {
      const res = await emailAPI.sync({ days_back: 7, max_emails: 50 });
      setSyncResult(res.data);
      if (res.data.updates_made?.length > 0) {
        fetchJobs();
        fetchStats();
      }
    } catch (err) {
      setSyncResult({ message: err.response?.data?.detail || 'Sync failed. Check email settings.' });
    } finally {
      setSyncing(false);
    }
  };

  const handleSaveEmailSettings = async (e) => {
    e.preventDefault();
    setSavingEmail(true);
    setEmailMsg('');
    try {
      await authAPI.saveEmailSettings(emailSettings);
      setEmailConfigured(true);
      setEmailMsg('✅ Email connected successfully!');
      setTimeout(() => { setShowEmailSettings(false); setEmailMsg(''); }, 1500);
    } catch (err) {
      setEmailMsg('❌ ' + (err.response?.data?.detail || 'Failed to save settings'));
    } finally {
      setSavingEmail(false);
    }
  };

  return (
    <div className="dashboard">
      {/* Header */}
      <header className="dashboard-header">
        <div className="header-left">
          <h1>🚀 Career Platform</h1>
        </div>
        <div className="header-right">
          <span className="user-name">{user?.full_name}</span>
          <button onClick={() => setShowEmailSettings(true)} className="btn btn-ghost" title="Email Settings">
            ⚙️
          </button>
          <button onClick={logout} className="btn btn-ghost">Logout</button>
        </div>
      </header>

      {/* Stats Cards */}
      <div className="stats-grid">
        {[
          { label: 'Total', value: stats.total || 0, color: '#6366f1' },
          { label: 'Applied', value: stats.applied || 0, color: '#3b82f6' },
          { label: 'Interviewing', value: stats.interviewing || 0, color: '#f59e0b' },
          { label: 'Offers', value: stats.offer || 0, color: '#10b981' },
          { label: 'Rejected', value: stats.rejected || 0, color: '#ef4444' },
        ].map(s => (
          <div key={s.label} className="stat-card" style={{ borderTop: `3px solid ${s.color}` }}>
            <div className="stat-value">{s.value}</div>
            <div className="stat-label">{s.label}</div>
          </div>
        ))}
      </div>

      {/* Toolbar */}
      <div className="toolbar">
        <div className="toolbar-left">
          <input
            type="text"
            placeholder="Search company or position..."
            value={search}
            onChange={(e) => { setSearch(e.target.value); setPage(1); }}
            className="search-input"
          />
          <div className="filter-pills">
            {STATUS_OPTIONS.map(s => (
              <button
                key={s}
                className={`pill ${filter === s ? 'pill-active' : ''}`}
                onClick={() => { setFilter(s); setPage(1); }}
              >
                {s.charAt(0).toUpperCase() + s.slice(1)}
              </button>
            ))}
          </div>
        </div>
        <div className="toolbar-buttons">
          <button onClick={handleEmailSync} className="btn btn-ghost" disabled={syncing}>
            {syncing ? '📧 Syncing...' : emailConfigured ? '📧 Sync Emails' : '📧 Connect Email'}
          </button>
          <button onClick={() => { setShowForm(true); setEditingJob(null); }} className="btn btn-primary">
            + Add Job
          </button>
        </div>
      </div>

      {/* Email Sync Result Notification */}
      {syncResult && (
        <div className={`sync-banner ${syncResult.updates_made?.length > 0 ? 'sync-success' : 'sync-info'}`}>
          <span>{syncResult.message}</span>
          {syncResult.updates_made?.length > 0 && (
            <ul className="sync-updates">
              {syncResult.updates_made.map((u, i) => (
                <li key={i}>
                  {u.company} — {u.position}: <strong>{u.old_status}</strong> → <strong>{u.new_status}</strong>
                </li>
              ))}
            </ul>
          )}
          <button onClick={() => setSyncResult(null)} className="btn-icon">✕</button>
        </div>
      )}

      {/* Email Settings Modal */}
      {showEmailSettings && (
        <div className="modal-overlay" onClick={() => { setShowEmailSettings(false); setEmailMsg(''); }}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>📧 Email Settings</h2>
            <p style={{ color: '#94a3b8', fontSize: '0.9rem', marginBottom: '1rem' }}>
              Connect your Gmail to auto-sync job application updates.
              Each user connects their own email — your credentials are stored securely.
            </p>

            <div style={{ background: '#1e293b', borderRadius: '8px', padding: '1rem', marginBottom: '1.5rem', fontSize: '0.85rem', color: '#94a3b8' }}>
              <strong style={{ color: '#f59e0b' }}>How to get a Gmail App Password:</strong>
              <ol style={{ margin: '0.5rem 0 0 1.2rem', lineHeight: '1.8' }}>
                <li>Go to <a href="https://myaccount.google.com/security" target="_blank" rel="noreferrer" style={{ color: '#818cf8' }}>myaccount.google.com → Security</a></li>
                <li>Enable <strong>2-Step Verification</strong></li>
                <li>Search for <strong>"App Passwords"</strong> and generate one</li>
                <li>Paste the 16-character password below</li>
              </ol>
            </div>

            <form onSubmit={handleSaveEmailSettings}>
              <div className="form-group">
                <label>Gmail Address</label>
                <input
                  type="email"
                  value={emailSettings.email_user}
                  onChange={(e) => setEmailSettings({ ...emailSettings, email_user: e.target.value })}
                  placeholder="your-email@gmail.com"
                  required
                />
              </div>
              <div className="form-group">
                <label>App Password</label>
                <input
                  type="password"
                  value={emailSettings.email_app_password}
                  onChange={(e) => setEmailSettings({ ...emailSettings, email_app_password: e.target.value })}
                  placeholder="xxxx xxxx xxxx xxxx"
                  required
                />
              </div>
              {emailMsg && (
                <div style={{ padding: '0.75rem', borderRadius: '6px', marginBottom: '1rem', background: emailMsg.startsWith('✅') ? '#065f4620' : '#7f1d1d20', color: emailMsg.startsWith('✅') ? '#10b981' : '#ef4444' }}>
                  {emailMsg}
                </div>
              )}
              <div className="form-actions">
                <button type="button" onClick={() => { setShowEmailSettings(false); setEmailMsg(''); }} className="btn btn-ghost">Cancel</button>
                <button type="submit" className="btn btn-primary" disabled={savingEmail}>
                  {savingEmail ? 'Saving...' : emailConfigured ? 'Update Settings' : 'Connect Gmail'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Job Form Modal */}
      {(showForm || editingJob) && (
        <div className="modal-overlay" onClick={() => { setShowForm(false); setEditingJob(null); }}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>{editingJob ? 'Edit Job' : 'Add Job Application'}</h2>
            <JobForm
              initialData={editingJob}
              onSubmit={editingJob ? handleUpdate : handleCreate}
              onCancel={() => { setShowForm(false); setEditingJob(null); }}
            />
          </div>
        </div>
      )}

      {/* Jobs Grid */}
      {loading ? (
        <div className="loading">Loading...</div>
      ) : jobs.length === 0 ? (
        <div className="empty-state">
          <p>No job applications yet.</p>
          <button onClick={() => setShowForm(true)} className="btn btn-primary">Add your first job</button>
        </div>
      ) : (
        <>
          <div className="jobs-grid">
            {jobs.map(job => (
              <JobCard
                key={job.id}
                job={job}
                onEdit={() => setEditingJob(job)}
                onDelete={() => handleDelete(job.id)}
              />
            ))}
          </div>
          {totalPages > 1 && (
            <div className="pagination">
              <button disabled={page <= 1} onClick={() => setPage(p => p - 1)} className="btn btn-ghost">← Prev</button>
              <span>Page {page} of {totalPages}</span>
              <button disabled={page >= totalPages} onClick={() => setPage(p => p + 1)} className="btn btn-ghost">Next →</button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
