import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { applyAPI, getErrorMessage } from '../../api';
import { useToast } from '../../lib/toast';
import {
  AlertCircle, AlertTriangle, Briefcase, CheckCircle, Clock, Inbox, LinkIcon, MapPin, Plus, Search, Sparkle,
} from '../../components/icons';
import { FitRing, Loading, ToneLabel } from './parts';

const PAGE_SIZE = 12;
const SOURCE_LABEL = { manual: 'Pasted', url: 'Link', greenhouse: 'Greenhouse', lever: 'Lever', ashby: 'Ashby' };

function Overview({ data }) {
  if (!data) return null;
  const tiles = [
    { label: 'Saved postings', value: data.postings, icon: Search, accent: true },
    { label: 'Needs review', value: data.packages.ready_for_review, icon: Clock },
    { label: 'Approved', value: data.packages.approved, icon: CheckCircle },
    { label: 'Sent', value: data.packages.sent, icon: Briefcase },
  ];
  return (
    <>
      <div className="stat-row">
        {tiles.map((t) => (
          <div key={t.label} className={`stat ${t.accent ? 'stat--accent' : ''}`}>
            <div className="stat__top">
              <span className="stat__ic"><t.icon /></span>
              <span className="stat__label">{t.label}</span>
            </div>
            <div className="stat__val">{t.value}</div>
          </div>
        ))}
      </div>
      {(!data.has_resume || !data.has_profile) && (
        <section className="panel">
          <h2 className="panel__title"><Sparkle /> Get set up (2 minutes)</h2>
          <div className="setup-list">
            <div className={`setup-item ${data.has_resume ? 'done' : 'todo'}`}>
              <CheckCircle /> <span>Add your resume — fit scores and drafts use only what it says. </span>
              {!data.has_resume && <Link to="/apply/profile">Add resume</Link>}
            </div>
            <div className={`setup-item ${data.has_profile ? 'done' : 'todo'}`}>
              <CheckCircle /> <span>Add a headline and the roles you’re targeting. </span>
              {!data.has_profile && <Link to="/apply/profile">Edit profile</Link>}
            </div>
          </div>
        </section>
      )}
    </>
  );
}

function Intake({ onAdded }) {
  const { toast } = useToast();
  const [mode, setMode] = useState('link');
  const [url, setUrl] = useState('');
  const [text, setText] = useState('');
  const [title, setTitle] = useState('');
  const [company, setCompany] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    const body = mode === 'link'
      ? { url: url.trim() }
      : { text: text.trim(), title: title.trim() || null, company: company.trim() || null };
    if (mode === 'link' && !body.url) return setError('Paste the job posting link.');
    if (mode === 'text' && body.text.length < 100) return setError('Paste the full job description (at least a few sentences).');
    setBusy(true);
    try {
      const res = await applyAPI.addPosting(body);
      const { created, posting } = res.data;
      toast(created ? 'Posting analysed.' : 'You already saved this posting — opening it.', created ? 'success' : 'info');
      setUrl(''); setText(''); setTitle(''); setCompany('');
      onAdded(posting);
    } catch (err) {
      setError(getErrorMessage(err, 'Could not add that posting.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel">
      <div className="panel__head">
        <h2 className="panel__title"><Plus /> Add a job posting</h2>
        <div className="seg" role="group" aria-label="How to add">
          <button type="button" aria-pressed={mode === 'link'} onClick={() => setMode('link')}>Paste link</button>
          <button type="button" aria-pressed={mode === 'text'} onClick={() => setMode('text')}>Paste description</button>
        </div>
      </div>
      <form className="intake" onSubmit={submit}>
        {mode === 'link' ? (
          <div className="field">
            <label htmlFor="posting-url">Job posting link</label>
            <div className="input-wrap">
              <span className="lead-icon"><LinkIcon /></span>
              <input id="posting-url" className="input" type="url" inputMode="url" placeholder="https://jobs.example.com/roles/123"
                value={url} onChange={(e) => setUrl(e.target.value)} />
            </div>
          </div>
        ) : (
          <>
            <div className="field">
              <label htmlFor="posting-text">Job description</label>
              <textarea id="posting-text" className="textarea" rows={7} placeholder="Paste the full job description…"
                value={text} onChange={(e) => setText(e.target.value)} maxLength={100000} />
            </div>
            <div className="form-row">
              <div className="field">
                <label htmlFor="posting-title">Job title <span className="dim">(optional)</span></label>
                <input id="posting-title" className="input" value={title} onChange={(e) => setTitle(e.target.value)} maxLength={300} />
              </div>
              <div className="field">
                <label htmlFor="posting-company">Company <span className="dim">(optional)</span></label>
                <input id="posting-company" className="input" value={company} onChange={(e) => setCompany(e.target.value)} maxLength={300} />
              </div>
            </div>
          </>
        )}
        {error && <div className="alert alert-error" role="alert"><AlertCircle /><span>{error}</span></div>}
        <div className="intake__actions">
          <button className="btn btn-primary" type="submit" disabled={busy}>
            {busy ? <><span className="spinner" /> Analysing…</> : <><Sparkle /> Analyse posting</>}
          </button>
          <span className="fine-print">
            {mode === 'link'
              ? 'Public https links only. If a site blocks reading, paste the description instead.'
              : 'Your text is analysed on our server; nothing is sent to the employer.'}
          </span>
        </div>
      </form>
    </section>
  );
}

function PostingCard({ p }) {
  return (
    <Link to={`/apply/postings/${p.id}`} className="posting-card">
      <FitRing score={p.fit_score} />
      <div style={{ minWidth: 0 }}>
        <div className="posting-card__title">{p.title}</div>
        <div className="posting-card__co">{p.company}</div>
        <div className="posting-card__meta">
          {p.location && <span className="row"><MapPin /> {p.location}</span>}
          {p.location_type && <span className="chip">{p.location_type}</span>}
          <span className="chip">{SOURCE_LABEL[p.source_type] || p.source_type}</span>
          {p.tracked_job_id && <span className="chip chip--sky">In tracker</span>}
          {p.flagged && <span className="chip chip--warn"><AlertTriangle width={12} height={12} />&nbsp;Suspicious text</span>}
        </div>
      </div>
      <div className="posting-card__right">
        <ToneLabel score={p.fit_score} />
      </div>
    </Link>
  );
}

export default function PostingsPage() {
  const navigate = useNavigate();
  const [overview, setOverview] = useState(null);
  const [rows, setRows] = useState([]);
  const [total, setTotal] = useState(0);
  const [pages, setPages] = useState(1);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState('fit');
  const [archived, setArchived] = useState(false);
  const [qInput, setQInput] = useState('');
  const [q, setQ] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    const t = setTimeout(() => { setQ(qInput.trim()); setPage(1); }, 300);
    return () => clearTimeout(t);
  }, [qInput]);

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const params = { sort, page, limit: PAGE_SIZE, status: archived ? 'archived' : 'active' };
      if (q) params.q = q;
      const [list, ov] = await Promise.all([applyAPI.listPostings(params), applyAPI.overview()]);
      setRows(list.data.data);
      setTotal(list.data.total);
      setPages(list.data.pages);
      setOverview(ov.data);
    } catch (err) {
      setError(getErrorMessage(err, 'Could not load your postings.'));
    } finally {
      setLoading(false);
    }
  }, [sort, page, archived, q]);

  useEffect(() => { load(); }, [load]);

  return (
    <>
      <Overview data={overview} />
      <Intake onAdded={(p) => navigate(`/apply/postings/${p.id}`)} />

      <div className="toolbar">
        <div className="toolbar__left">
          <h2 className="section-title">{archived ? 'Archived postings' : 'Your postings'} <span className="count-badge">{total}</span></h2>
          <div className="input-wrap search">
            <span className="lead-icon"><Search /></span>
            <input className="input" type="search" placeholder="Search title or company…" value={qInput}
              onChange={(e) => setQInput(e.target.value)} aria-label="Search postings" />
          </div>
          <div className="filters" role="group" aria-label="Sort and filter">
            <button className="pill" aria-pressed={sort === 'fit'} onClick={() => { setSort('fit'); setPage(1); }}>Best fit</button>
            <button className="pill" aria-pressed={sort === 'recent'} onClick={() => { setSort('recent'); setPage(1); }}>Newest</button>
            <button className="pill" aria-pressed={archived} onClick={() => { setArchived((a) => !a); setPage(1); }}>Archived</button>
          </div>
        </div>
      </div>

      {loading ? <Loading label="Loading postings…" /> : error ? (
        <div className="center-state">
          <div className="ic"><AlertCircle /></div>
          <h3>Couldn’t load postings</h3>
          <p>{error}</p>
          <button className="btn btn-primary" onClick={load}>Retry</button>
        </div>
      ) : rows.length === 0 ? (
        <div className="center-state">
          <div className="ic"><Search /></div>
          <h3>{q || archived ? 'Nothing matches' : 'No postings yet'}</h3>
          <p>{q || archived ? 'Try a different search.' : 'Paste a job link or description above, or follow a company’s job board.'}</p>
          {!q && !archived && <Link className="btn btn-ghost" to="/apply/boards"><Inbox /> Follow a job board</Link>}
        </div>
      ) : (
        <>
          <div className="posting-list">{rows.map((p) => <PostingCard key={p.id} p={p} />)}</div>
          {pages > 1 && (
            <div className="pagination">
              <button className="btn btn-ghost btn-sm" disabled={page <= 1} onClick={() => setPage((x) => x - 1)}>Previous</button>
              <span>Page {page} of {pages}</span>
              <button className="btn btn-ghost btn-sm" disabled={page >= pages} onClick={() => setPage((x) => x + 1)}>Next</button>
            </div>
          )}
        </>
      )}
    </>
  );
}

