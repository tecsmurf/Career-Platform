import { useState, useEffect, useCallback, useRef } from 'react';
import { useAuth } from '../hooks/useAuth';
import { jobsAPI } from '../api';
import { useToast } from '../lib/toast';
import JobForm from '../components/JobForm';
import JobCard from '../components/JobCard';
import Modal from '../components/Modal';
import ConfirmDialog from '../components/ConfirmDialog';
import Pipeline from '../components/Pipeline';
import { JobsGridSkeleton } from '../components/Skeleton';
import { STATUSES } from '../constants';
import {
  Logo, Logout, Search, Plus, Mail, Briefcase, Check, Calendar, Sparkle, Close,
  Inbox, AlertCircle,
} from '../components/icons';

const PAGE_SIZE = 12;

const STAT_CARDS = [
  { key: 'total', label: 'Total', icon: Briefcase, color: 'var(--accent)', accent: true },
  { key: 'applied', label: 'Applied', icon: Check, color: 'var(--st-applied)' },
  { key: 'interview', label: 'Interview', icon: Calendar, color: 'var(--st-interview)' },
  { key: 'offer', label: 'Offers', icon: Sparkle, color: 'var(--st-offer)' },
  { key: 'rejected', label: 'Rejected', icon: Close, color: 'var(--st-rejected)' },
];

function initials(name) {
  if (!name) return '?';
  return name.trim().split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase()).join('');
}

export default function DashboardPage() {
  const { user, logout } = useAuth();
  const { toast } = useToast();

  const [jobs, setJobs] = useState([]);
  const [stats, setStats] = useState({});
  const [filter, setFilter] = useState('all');
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);

  const [showForm, setShowForm] = useState(false);
  const [editingJob, setEditingJob] = useState(null);
  const [confirmJob, setConfirmJob] = useState(null);

  // Debounce the search box → one request after typing settles.
  useEffect(() => {
    const t = setTimeout(() => { setSearch(searchInput); setPage(1); }, 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  const fetchStats = useCallback(async () => {
    try {
      const res = await jobsAPI.stats();
      setStats(res.data);
    } catch { /* stats are non-critical; leave prior values */ }
  }, []);

  const fetchJobs = useCallback(async () => {
    setLoading(true);
    setError(false);
    try {
      const params = { page, limit: PAGE_SIZE };
      if (filter !== 'all') params.status = filter;
      if (search) params.search = search;
      const res = await jobsAPI.list(params);
      setJobs(res.data.data);
      setTotalPages(res.data.pages || 1);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [page, filter, search]);

  useEffect(() => { fetchJobs(); }, [fetchJobs]);
  useEffect(() => { fetchStats(); }, [fetchStats]);

  const refresh = () => { fetchJobs(); fetchStats(); };

  const handleCreate = async (data) => {
    await jobsAPI.create(data);
    setShowForm(false);
    toast('Application added.', 'success');
    refresh();
  };

  const handleUpdate = async (data) => {
    await jobsAPI.update(editingJob.id, data);
    setEditingJob(null);
    toast('Changes saved.', 'success');
    refresh();
  };

  const handleDelete = async () => {
    const job = confirmJob;
    try {
      await jobsAPI.delete(job.id);
      setConfirmJob(null);
      toast('Application deleted.', 'success');
      // If we just removed the last item on a page, step back a page.
      if (jobs.length === 1 && page > 1) setPage((p) => p - 1);
      else refresh();
    } catch {
      setConfirmJob(null);
      toast('Could not delete that application.', 'error');
    }
  };

  const filtersActive = filter !== 'all' || !!search;
  const hasAnyJobs = (stats.total || 0) > 0;

  return (
    <>
      <nav className="nav">
        <div className="brand">
          <span className="brand__mark"><Logo /></span>
          <span className="brand__name">Career<b>Platform</b></span>
        </div>
        <div className="nav__right">
          <div className="nav__user">
            <span className="avatar" aria-hidden="true">{initials(user?.full_name)}</span>
            <span className="who"><b>{user?.full_name}</b>{user?.email}</span>
          </div>
          <button className="btn btn-ghost" onClick={logout}><Logout /> Logout</button>
        </div>
      </nav>

      <div className="page">
        <div className="page__head">
          <div>
            <h1>Your applications</h1>
            <p>Track where every opportunity stands, from saved to offer.</p>
          </div>
          <button className="btn btn-primary" onClick={() => { setEditingJob(null); setShowForm(true); }}>
            <Plus /> Add application
          </button>
        </div>

        {/* Stats */}
        <div className="stats">
          {STAT_CARDS.map((c) => (
            <div key={c.key} className={`stat ${c.accent ? 'stat--accent' : ''}`}>
              <div className="stat__top">
                <span className="stat__ic" style={{ '--st': c.color }}><c.icon /></span>
              </div>
              <div className="stat__val">{stats[c.key] || 0}</div>
              <div className="stat__label">{c.label}</div>
            </div>
          ))}
        </div>

        {/* Pipeline */}
        <Pipeline stats={stats} />

        {/* Toolbar */}
        <div className="toolbar">
          <div className="toolbar__left">
            <div className="input-wrap search">
              <span className="lead-icon"><Search /></span>
              <input
                className="input"
                type="search"
                placeholder="Search company or position…"
                value={searchInput}
                onChange={(e) => setSearchInput(e.target.value)}
                aria-label="Search applications"
              />
            </div>
            <div className="filters" role="group" aria-label="Filter by status">
              <button className="pill" aria-pressed={filter === 'all'} onClick={() => { setFilter('all'); setPage(1); }}>
                All <span className="count">{stats.total || 0}</span>
              </button>
              {STATUSES.map((s) => (
                <button key={s.value} className="pill" aria-pressed={filter === s.value}
                  onClick={() => { setFilter(s.value); setPage(1); }}>
                  {s.label} <span className="count">{stats[s.value] || 0}</span>
                </button>
              ))}
            </div>
          </div>
          <div className="toolbar__right">
            <button className="btn btn-soon" onClick={() => toast('Email sync is being reworked and isn’t available yet.', 'info')}>
              <Mail /> Email sync <span className="tag">Soon</span>
            </button>
          </div>
        </div>

        {/* Content states */}
        {loading ? (
          <JobsGridSkeleton count={6} />
        ) : error ? (
          <div className="center-state">
            <div className="ic"><AlertCircle /></div>
            <h3>Couldn’t load your applications</h3>
            <p>Something went wrong reaching the server. Check your connection and try again.</p>
            <button className="btn btn-primary" onClick={refresh}>Retry</button>
          </div>
        ) : jobs.length === 0 ? (
          filtersActive ? (
            <div className="center-state">
              <div className="ic"><Search /></div>
              <h3>No matching applications</h3>
              <p>Try a different search term or clear your filters.</p>
              <button className="btn btn-ghost" onClick={() => { setFilter('all'); setSearchInput(''); }}>Clear filters</button>
            </div>
          ) : (
            <div className="center-state">
              <div className="ic"><Inbox /></div>
              <h3>{hasAnyJobs ? 'Nothing here yet' : 'Add your first application'}</h3>
              <p>Start tracking a role you’ve applied to or want to save for later.</p>
              <button className="btn btn-primary" onClick={() => { setEditingJob(null); setShowForm(true); }}>
                <Plus /> Add application
              </button>
            </div>
          )
        ) : (
          <>
            <div className="jobs">
              {jobs.map((job) => (
                <JobCard
                  key={job.id}
                  job={job}
                  onEdit={() => { setEditingJob(job); setShowForm(false); }}
                  onDelete={() => setConfirmJob(job)}
                />
              ))}
            </div>
            {totalPages > 1 && (
              <div className="pagination">
                <button className="btn btn-ghost" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>← Prev</button>
                <span>Page {page} of {totalPages}</span>
                <button className="btn btn-ghost" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>Next →</button>
              </div>
            )}
          </>
        )}
      </div>

      {/* Add / Edit modal */}
      {(showForm || editingJob) && (
        <Modal
          title={editingJob ? 'Edit application' : 'Add application'}
          onClose={() => { setShowForm(false); setEditingJob(null); }}
        >
          <JobForm
            initialData={editingJob}
            onSubmit={editingJob ? handleUpdate : handleCreate}
            onCancel={() => { setShowForm(false); setEditingJob(null); }}
          />
        </Modal>
      )}

      {/* Delete confirmation */}
      {confirmJob && (
        <ConfirmDialog
          title="Delete this application?"
          message={`“${confirmJob.position} at ${confirmJob.company}” will be permanently removed. This can’t be undone.`}
          confirmLabel="Delete"
          onConfirm={handleDelete}
          onCancel={() => setConfirmJob(null)}
        />
      )}
    </>
  );
}
