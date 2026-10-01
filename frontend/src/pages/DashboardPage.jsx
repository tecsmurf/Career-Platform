import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../hooks/useAuth';
import { jobsAPI } from '../api';
import { useToast } from '../lib/toast';
import JobForm from '../components/JobForm';
import JobCard from '../components/JobCard';
import Modal from '../components/Modal';
import ConfirmDialog from '../components/ConfirmDialog';
import Pipeline from '../components/Pipeline';
import EmailPanel from '../components/email/EmailPanel';
import { JobsGridSkeleton } from '../components/Skeleton';
import { BubbleBackground, FloatingBubbleField, ParallaxScene } from '../components/bubbles';
import { STATUSES } from '../constants';
import { HERO_BUBBLES, EMPTY_BUBBLES } from '../lib/companies';
import {
  Logo, Logout, Search, Plus, Briefcase, Calendar, Sparkle, Bookmark, AlertCircle,
} from '../components/icons';

const PAGE_SIZE = 12;

// Headline numbers in the hero; the pipeline below shows every stage.
const STAT_CARDS = [
  { key: 'total', label: 'Applications', icon: Briefcase, color: 'var(--sky-deep)', accent: true },
  { key: 'interview', label: 'Interviews', icon: Calendar, color: 'var(--st-interview)' },
  { key: 'offer', label: 'Offers', icon: Sparkle, color: 'var(--st-offer)' },
  { key: 'saved', label: 'Saved', icon: Bookmark, color: 'var(--text-dim)' },
];

function initials(name) {
  if (!name) return '?';
  return name.trim().split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase()).join('');
}

function greeting(date = new Date()) {
  const h = date.getHours();
  if (h >= 5 && h < 12) return 'Good morning';
  if (h >= 12 && h < 18) return 'Good afternoon';
  return 'Good evening';
}

function firstName(fullName) {
  return fullName?.trim().split(/\s+/)[0] || 'there';
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
      <BubbleBackground />

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
        {/* Hero: greeting + headline stats, with a few bubbles in their own corner */}
        <section className="hero" data-bubble-pass="" aria-labelledby="hero-title">
          <div className="hero__copy">
            <p className="hero__eyebrow">{new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' })}</p>
            <h1 id="hero-title">{greeting()}, {firstName(user?.full_name)}</h1>
            <p className="hero__sub">Your career pipeline at a glance.</p>
            <div className="hero__actions">
              <button className="btn btn-primary btn-lg" onClick={() => { setEditingJob(null); setShowForm(true); }}>
                <Plus /> Add application
              </button>
            </div>
          </div>

          <ParallaxScene className="hero__scene">
            <FloatingBubbleField companies={HERO_BUBBLES} density="dense" />
          </ParallaxScene>

          <div className="hero__stats">
            {STAT_CARDS.map((c) => (
              <div key={c.key} className={`stat ${c.accent ? 'stat--accent' : ''}`}>
                <div className="stat__top">
                  <span className="stat__ic" style={{ '--st': c.color }}><c.icon /></span>
                  <span className="stat__label">{c.label}</span>
                </div>
                <div className="stat__val">{stats[c.key] || 0}</div>
              </div>
            ))}
          </div>
        </section>

        {/* Pipeline */}
        <Pipeline stats={stats} />

        {/* Email intelligence (connect, sync, review) */}
        <EmailPanel onJobsChanged={refresh} />

        {/* Toolbar */}
        <div className="toolbar">
          <div className="toolbar__left">
            <h2 className="section-title">Applications</h2>
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
            <div className="empty" data-bubble-pass="">
              <ParallaxScene className="empty__scene">
                <FloatingBubbleField companies={EMPTY_BUBBLES} density="dense" />
              </ParallaxScene>
              <div className="empty__copy">
                <h3>{hasAnyJobs ? 'Nothing here yet' : 'No applications yet'}</h3>
                <p>Start tracking your career journey — add a role you’ve applied to or want to save for later.</p>
                <button className="btn btn-primary btn-lg" onClick={() => { setEditingJob(null); setShowForm(true); }}>
                  <Plus /> Add application
                </button>
              </div>
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
