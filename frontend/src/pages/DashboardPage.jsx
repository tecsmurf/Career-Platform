import { useState, useEffect, useCallback } from 'react';
import { useAuth } from '../hooks/useAuth';
import { jobsAPI } from '../api';
import { useToast } from '../lib/toast';
import JobForm from '../components/JobForm';
import JobCard, { BoardCard } from '../components/JobCard';
import Modal from '../components/Modal';
import ConfirmDialog from '../components/ConfirmDialog';
import Pipeline from '../components/Pipeline';
import EmailPanel from '../components/email/EmailPanel';
import AppShell from '../components/AppShell';
import { JobsGridSkeleton } from '../components/Skeleton';
import SceneMount from '../components/three/SceneMount';
import { CountUp, Reveal, Tilt, stagger, rise, EASE_OUT_EXPO } from '../components/motion';
import { motion } from 'framer-motion';
import { STATUSES, STATUS_LABEL } from '../constants';
import { Search, Plus, AlertCircle, Briefcase, Close } from '../components/icons';

const PAGE_SIZE = 12;
const BOARD_LIMIT = 100; // API maximum per request
const VIEW_KEY = 'tracker:view';

function greeting(date = new Date()) {
  const h = date.getHours();
  if (h >= 5 && h < 12) return 'Good morning';
  if (h >= 12 && h < 18) return 'Good afternoon';
  return 'Good evening';
}

function firstName(fullName) {
  return fullName?.trim().split(/\s+/)[0] || 'there';
}

function readView() {
  try { return localStorage.getItem(VIEW_KEY) === 'board' ? 'board' : 'list'; } catch { return 'list'; }
}

const ListIcon = (p) => (
  <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true" {...p}>
    <path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" />
  </svg>
);
const BoardIcon = (p) => (
  <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" aria-hidden="true" {...p}>
    <rect x="3" y="4" width="5" height="16" rx="1.5" /><rect x="10" y="4" width="5" height="11" rx="1.5" /><rect x="17" y="4" width="4" height="7" rx="1.5" />
  </svg>
);

/** Headline numbers. Response rate = applications that heard back / applications sent. */
function Kpis({ stats }) {
  const total = stats.total || 0;
  const sent = total - (stats.saved || 0);
  const heard = (stats.interview || 0) + (stats.offer || 0) + (stats.rejected || 0);
  const active = (stats.applied || 0) + (stats.interview || 0);
  const items = [
    { label: 'Total tracked', value: total },
    { label: 'In progress', value: active, hint: 'Applied or interviewing' },
    { label: 'Interviews', value: stats.interview || 0 },
    { label: 'Offers', value: stats.offer || 0, tone: 'good' },
    { label: 'Response rate', value: sent ? `${Math.round((heard / sent) * 100)}%` : '—', hint: sent ? `${heard} of ${sent} heard back` : 'No applications sent yet' },
  ];
  return (
    <dl className="kpis">
      {items.map((k) => (
        <div key={k.label} className={`kpi ${k.tone ? `kpi--${k.tone}` : ''}`}>
          <dt>{k.label}</dt>
          <dd><CountUp value={k.value} /></dd>
          {k.hint && <span className="kpi__hint">{k.hint}</span>}
        </div>
      ))}
    </dl>
  );
}

export default function DashboardPage() {
  const { user } = useAuth();
  const { toast } = useToast();

  const [jobs, setJobs] = useState([]);
  const [stats, setStats] = useState({});
  const [filter, setFilter] = useState('all');
  const [searchInput, setSearchInput] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const [totalShown, setTotalShown] = useState(0);
  const [view, setView] = useState(readView);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(false);
  const [busyId, setBusyId] = useState(null);

  const [showForm, setShowForm] = useState(false);
  const [editingJob, setEditingJob] = useState(null);
  const [confirmJob, setConfirmJob] = useState(null);

  // Debounce the search box → one request after typing settles.
  useEffect(() => {
    const t = setTimeout(() => { setSearch(searchInput.trim()); setPage(1); }, 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  const changeView = (v) => {
    setView(v);
    setPage(1);
    try { localStorage.setItem(VIEW_KEY, v); } catch { /* preference only */ }
  };

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
      // The board shows every stage side by side, so it loads one large page
      // and ignores the stage filter; the list pages through the filtered set.
      const params = view === 'board' ? { page: 1, limit: BOARD_LIMIT } : { page, limit: PAGE_SIZE };
      if (view === 'list' && filter !== 'all') params.status = filter;
      if (search) params.search = search;
      const res = await jobsAPI.list(params);
      setJobs(res.data.data);
      setTotalPages(res.data.pages || 1);
      setTotalShown(res.data.total || 0);
    } catch {
      setError(true);
    } finally {
      setLoading(false);
    }
  }, [page, filter, search, view]);

  useEffect(() => { fetchJobs(); }, [fetchJobs]);
  useEffect(() => { fetchStats(); }, [fetchStats]);

  const refresh = () => { fetchJobs(); fetchStats(); };
  const openAdd = () => { setEditingJob(null); setShowForm(true); };

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

  // Inline status change: update the row right away, then confirm with the server.
  const handleStatusChange = async (job, status) => {
    if (status === job.status) return;
    const prev = jobs;
    setBusyId(job.id);
    setJobs((list) => list.map((j) => (j.id === job.id ? { ...j, status } : j)));
    try {
      await jobsAPI.update(job.id, { status });
      toast(`Moved to ${STATUS_LABEL[status]}.`, 'success', 2500);
      fetchStats();
      // In a filtered list the row no longer belongs; reload that page.
      if (view === 'list' && filter !== 'all') fetchJobs();
    } catch {
      setJobs(prev);
      toast('Could not update the status. Please try again.', 'error');
    } finally {
      setBusyId(null);
    }
  };

  const handleDelete = async () => {
    const job = confirmJob;
    try {
      await jobsAPI.delete(job.id);
      setConfirmJob(null);
      toast('Application deleted.', 'success');
      // If we just removed the last item on a page, step back a page.
      if (view === 'list' && jobs.length === 1 && page > 1) setPage((p) => p - 1);
      else refresh();
    } catch {
      setConfirmJob(null);
      toast('Could not delete that application.', 'error');
    }
  };

  const selectFilter = (value) => { setFilter(value); setPage(1); if (value !== 'all' && view === 'board') changeView('list'); };
  const clearFilters = () => { setFilter('all'); setSearchInput(''); setSearch(''); setPage(1); };
  const filtersActive = (view === 'list' && filter !== 'all') || !!search;
  const hasAnyJobs = (stats.total || 0) > 0;
  const today = new Date().toLocaleDateString(undefined, { weekday: 'long', month: 'long', day: 'numeric' });

  return (
    <AppShell>
      <div className="page">
        <header className="hero3d">
          <SceneMount className="hero3d__scene" />
          <motion.div className="hero3d__copy" initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.9, ease: EASE_OUT_EXPO }}>
            <p className="eyebrow">{today}</p>
            <h1>{greeting()}, <span className="hero3d__name">{firstName(user?.full_name)}</span></h1>
            <p className="hero3d__sub">
              {hasAnyJobs
                ? `You have ${(stats.applied || 0) + (stats.interview || 0)} applications in progress and ${stats.interview || 0} at interview stage.`
                : 'Track every application, interview and offer in one place.'}
            </p>
            <button className="btn btn-primary btn-lg" onClick={openAdd}><Plus /> Add application</button>
          </motion.div>
        </header>

        <Reveal as="section" className="card overview" aria-label="Overview">
          <Kpis stats={stats} />
          <Pipeline stats={stats} active={view === 'list' ? filter : 'all'} onSelect={selectFilter} />
        </Reveal>

        <Reveal as="section" delay={0.08} className="card tracker" aria-labelledby="apps-title">
          <div className="tracker__head">
            <h2 id="apps-title" className="section-title">
              Applications {!loading && <span className="count-badge">{totalShown}</span>}
            </h2>
            <div className="tracker__tools">
              <div className="input-wrap search">
                <span className="lead-icon"><Search /></span>
                <input
                  className="input"
                  type="search"
                  placeholder="Search company or role"
                  value={searchInput}
                  onChange={(e) => setSearchInput(e.target.value)}
                  aria-label="Search applications"
                />
              </div>
              <div className="seg seg--icons" role="group" aria-label="Layout">
                <button type="button" aria-pressed={view === 'list'} onClick={() => changeView('list')}><ListIcon /> <span>List</span></button>
                <button type="button" aria-pressed={view === 'board'} onClick={() => changeView('board')}><BoardIcon /> <span>Board</span></button>
              </div>
            </div>
          </div>

          {view === 'list' && (
            <div className="tabs" role="group" aria-label="Filter by status">
              <button className="tab" aria-pressed={filter === 'all'} onClick={() => selectFilter('all')}>
                All <span className="count">{stats.total || 0}</span>
              </button>
              {STATUSES.map((s) => (
                <button key={s.value} className="tab" aria-pressed={filter === s.value} onClick={() => selectFilter(s.value)}>
                  {s.label} <span className="count">{stats[s.value] || 0}</span>
                </button>
              ))}
            </div>
          )}

          {loading ? (
            <JobsGridSkeleton count={5} />
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
                <button className="btn btn-ghost" onClick={clearFilters}><Close /> Clear filters</button>
              </div>
            ) : (
              <div className="center-state">
                <div className="ic"><Briefcase /></div>
                <h3>{hasAnyJobs ? 'Nothing here yet' : 'Add your first application'}</h3>
                <p>Save roles you’re interested in, then move them from Applied to Interview to Offer as things progress.</p>
                <button className="btn btn-primary" onClick={openAdd}><Plus /> Add application</button>
              </div>
            )
          ) : view === 'board' ? (
            <div className="board">
              {STATUSES.map((s) => {
                const col = jobs.filter((j) => j.status === s.value);
                return (
                  <section key={s.value} className="board__col" aria-label={`${s.label}, ${col.length}`}>
                    <header className="board__head">
                      <span className="legend-dot" style={{ background: s.color }} />
                      <h3>{s.label}</h3>
                      <span className="count">{col.length}</span>
                    </header>
                    <div className="board__items">
                      {col.length === 0
                        ? <p className="board__empty">No applications</p>
                        : col.map((job) => (
                          <motion.div key={job.id} layout="position" variants={rise} initial="hidden" animate="show">
                            <Tilt max={6}>
                              <BoardCard job={job} busy={busyId === job.id}
                                onEdit={() => { setEditingJob(job); setShowForm(false); }}
                                onStatusChange={(st) => handleStatusChange(job, st)} />
                            </Tilt>
                          </motion.div>
                        ))}
                    </div>
                  </section>
                );
              })}
            </div>
          ) : (
            <>
              <motion.div className="job-list" variants={stagger} initial="hidden" animate="show" key={`${filter}-${page}-${search}`}>
                {jobs.map((job) => (
                  <JobCard
                    key={job.id}
                    job={job}
                    busy={busyId === job.id}
                    onEdit={() => { setEditingJob(job); setShowForm(false); }}
                    onDelete={() => setConfirmJob(job)}
                    onStatusChange={(st) => handleStatusChange(job, st)}
                  />
                ))}
              </motion.div>
              {totalPages > 1 && (
                <nav className="pagination" aria-label="Pages">
                  <button className="btn btn-ghost btn-sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</button>
                  <span>Page {page} of {totalPages}</span>
                  <button className="btn btn-ghost btn-sm" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>Next</button>
                </nav>
              )}
            </>
          )}
        </Reveal>

        {/* Email intelligence (connect, sync, review) */}
        <Reveal delay={0.12}><EmailPanel onJobsChanged={refresh} /></Reveal>
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
    </AppShell>
  );
}
