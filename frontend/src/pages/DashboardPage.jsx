import { useState, useEffect } from 'react';
import { useAuth } from '../hooks/useAuth';
import { jobsAPI, emailAPI } from '../api';
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

  useEffect(() => { fetchJobs(); }, [filter, search, page]);
  useEffect(() => { fetchStats(); }, []);

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
      setSyncResult({ message: err.response?.data?.detail || 'Sync failed. Check email settings in .env' });
    } finally {
      setSyncing(false);
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
            {syncing ? '📧 Syncing...' : '📧 Sync Emails'}
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
