import { Fragment, useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { applyAPI, getErrorCode, getErrorMessage } from '../../api';
import { useToast } from '../../lib/toast';
import { formatDate } from '../../lib/applyUi';
import {
  AlertCircle, AlertTriangle, Briefcase, ChevronLeft, LinkIcon, Mail, MapPin, Refresh, Shield, Sparkle, Trash,
  BarChart, Activity, Bookmark,
} from '../../components/icons';
import { FitRing, Loading, StatusPill, ToneLabel } from './parts';

const COMPONENT_LABEL = {
  required_skills: 'Required skills',
  preferred_skills: 'Nice-to-have skills',
  experience: 'Experience',
  title: 'Role / title',
  location: 'Location',
};

function FitPanel({ match, score }) {
  if (!match) return null;
  return (
    <section className="panel">
      <h2 className="panel__title"><BarChart /> How well you fit</h2>
      <div className="fit-summary">
        <FitRing score={score} large />
        <div>
          <h3><ToneLabel score={score} /></h3>
          {match.recommendation === 'needs_profile' ? (
            <p className="muted" style={{ marginTop: 4 }}>Add your resume to score this posting. <Link to="/apply/profile">Add resume</Link></p>
          ) : (
            <p className="muted" style={{ marginTop: 4, fontSize: 13.5 }}>
              Confidence: {match.confidence}. Computed from your resume and profile only — no guesses.
            </p>
          )}
        </div>
      </div>
      {match.components?.length > 0 && (
        <div className="bars">
          {match.components.map((c) => (
            <div key={c.name}>
              <div className="bar__top"><b>{COMPONENT_LABEL[c.name] || c.name}</b><span>{Math.round(c.score * 100)}%</span></div>
              <div className="bar__track"><i style={{ '--w': `${Math.round(c.score * 100)}%` }} /></div>
              <div className="bar__why">{c.explanation}</div>
            </div>
          ))}
        </div>
      )}
      {(match.matched_required?.length > 0 || match.missing_required?.length > 0) && (
        <>
          <h3 className="subhead" style={{ marginTop: 18 }}>Skills the posting asks for</h3>
          <div className="chips">
            {match.matched_required.map((s) => <span key={s} className="chip chip--ok">{s}</span>)}
            {match.missing_required.map((s) => <span key={s} className="chip chip--warn">{s}</span>)}
          </div>
          {match.missing_required.length > 0 && (
            <p className="fine-print" style={{ marginTop: 8 }}>
              <AlertCircle /> Amber skills aren’t in your resume. They are never added to your drafts — add them to your resume only if they’re true.
            </p>
          )}
        </>
      )}
      {match.matched_preferred?.length + match.missing_preferred?.length > 0 && (
        <>
          <h3 className="subhead">Nice to have</h3>
          <div className="chips">
            {match.matched_preferred.map((s) => <span key={s} className="chip chip--ok">{s}</span>)}
            {match.missing_preferred.map((s) => <span key={s} className="chip">{s}</span>)}
          </div>
        </>
      )}
    </section>
  );
}

function RolePanel({ a }) {
  if (!a) return null;
  const facts = [
    ['Seniority', a.seniority],
    ['Experience', a.min_years_experience != null ? `${a.min_years_experience}+ years` : null],
    ['Employment', a.employment_type?.replace('_', ' ')],
    ['Pay', a.salary ? `${a.salary.currency || ''} ${a.salary.min?.toLocaleString()}–${a.salary.max?.toLocaleString()} / ${a.salary.period}` : null],
    ['Education', a.education],
  ].filter(([, v]) => v);
  return (
    <section className="panel">
      <h2 className="panel__title"><Briefcase /> The role</h2>
      {facts.length > 0 && <dl className="kv">{facts.map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd>{v}</dd></Fragment>)}</dl>}
      {a.responsibilities?.length > 0 && (<><h3 className="subhead">What you’ll do</h3><ul className="list">{a.responsibilities.map((r) => <li key={r}>{r}</li>)}</ul></>)}
      {a.qualifications?.length > 0 && (<><h3 className="subhead">What they ask for</h3><ul className="list">{a.qualifications.map((r) => <li key={r}>{r}</li>)}</ul></>)}
      {a.benefits?.length > 0 && (<><h3 className="subhead">Benefits mentioned</h3><ul className="list">{a.benefits.map((r) => <li key={r}>{r}</li>)}</ul></>)}
    </section>
  );
}

function ResearchPanel({ r }) {
  if (!r) return null;
  return (
    <section className="panel">
      <h2 className="panel__title"><Activity /> Company research</h2>
      <h3 className="subhead">Verified facts</h3>
      {r.verified_facts.length === 0 && <p className="muted" style={{ fontSize: 13.5 }}>No verifiable facts found.</p>}
      {r.verified_facts.map((f, i) => (
        <div className="fact" key={i}>
          <div className="fact__label">{f.label}</div>
          <div className="fact__value">{f.value}</div>
          <div className="fact__src">
            Source: {f.source}
            {f.source_url && <a href={f.source_url} target="_blank" rel="noopener noreferrer nofollow">open</a>}
          </div>
        </div>
      ))}
      {r.interpretation?.length > 0 && (
        <div className="interpretation">
          <h3 className="subhead" style={{ marginTop: 12 }}>Interpretation</h3>
          <ul className="list">{r.interpretation.map((t) => <li key={t}>{t}</li>)}</ul>
          <div className="interpretation__note">{r.interpretation_basis || 'Automatic interpretation — not verified.'}</div>
        </div>
      )}
      {r.notes?.length > 0 && <ul className="list" style={{ marginTop: 10, fontSize: 12.5 }}>{r.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
    </section>
  );
}

function ContactsPanel({ contacts }) {
  return (
    <section className="panel">
      <h2 className="panel__title"><Mail /> People named in the posting</h2>
      {contacts?.length ? contacts.map((c, i) => (
        <div className="fact" key={i}>
          <div className="fact__value"><b>{c.name || 'Unnamed contact'}</b>{c.role ? ` · ${c.role}` : ''}</div>
          {c.email && <div className="fact__src"><Mail width={13} height={13} /> {c.email}</div>}
          <div className="quote">“{c.evidence}”</div>
        </div>
      )) : <p className="muted" style={{ fontSize: 13.5 }}>The posting doesn’t name anyone.</p>}
      <p className="fine-print" style={{ marginTop: 10 }}><Shield /> Only people the employer published are shown. Addresses are never guessed.</p>
    </section>
  );
}

export default function PostingDetailPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { toast } = useToast();
  const [p, setP] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState('');

  const load = useCallback(async () => {
    setError('');
    try {
      const res = await applyAPI.getPosting(id);
      setP(res.data);
    } catch (err) {
      setError(getErrorMessage(err, 'Could not load this posting.'));
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  const run = async (key, fn, success) => {
    setBusy(key);
    try {
      const result = await fn();
      if (success) toast(success, 'success');
      return result;
    } catch (err) {
      if (getErrorCode(err) === 'resume_required') {
        toast('Add your resume first — drafts are built only from it.', 'warn');
        navigate('/apply/profile');
      } else {
        toast(getErrorMessage(err), 'error');
      }
      return null;
    } finally {
      setBusy('');
    }
  };

  if (error) {
    return (
      <div className="center-state">
        <div className="ic"><AlertCircle /></div><h3>Couldn’t open this posting</h3><p>{error}</p>
        <Link className="btn btn-ghost" to="/apply/postings">Back to postings</Link>
      </div>
    );
  }
  if (!p) return <Loading label="Loading posting…" />;

  const prepare = async () => {
    const res = await run('prepare', () => applyAPI.prepare(p.id));
    if (res) navigate(`/apply/applications/${res.data.id}`);
  };
  const track = async () => {
    const res = await run('track', () => applyAPI.trackPosting(p.id), 'Added to your tracker.');
    if (res) load();
  };
  const refresh = async () => {
    const res = await run('refresh', () => applyAPI.refreshPosting(p.id), 'Re-checked against your current resume.');
    if (res) setP((old) => ({ ...old, ...res.data }));
  };
  const toggleArchive = async () => {
    const archived = p.status === 'archived';
    const res = await run('archive', () => (archived ? applyAPI.restorePosting(p.id) : applyAPI.archivePosting(p.id)),
      archived ? 'Restored.' : 'Archived.');
    if (res) load();
  };
  const open = (p.packages || []).find((k) => ['ready_for_review', 'approved'].includes(k.status));

  return (
    <>
      <Link className="back-link" to="/apply/postings"><ChevronLeft /> All postings</Link>
      <section className="panel">
        <div className="detail-head">
          <div style={{ minWidth: 0 }}>
            <h1>{p.title}</h1>
            <div className="co">{p.company}</div>
            <div className="posting-card__meta" style={{ marginTop: 10 }}>
              {p.location && <span className="row"><MapPin /> {p.location}</span>}
              {p.location_type && <span className="chip">{p.location_type}</span>}
              {p.listing_url && <a className="row" href={p.listing_url} target="_blank" rel="noopener noreferrer nofollow"><LinkIcon /> Original posting</a>}
              {p.analyzed_at && <span>Analysed {formatDate(p.analyzed_at)}</span>}
            </div>
          </div>
          <div className="detail-actions">
            {open ? (
              <Link className="btn btn-primary" to={`/apply/applications/${open.id}`}><Sparkle /> Review application</Link>
            ) : (
              <button className="btn btn-primary" onClick={prepare} disabled={!!busy || p.status === 'archived'}>
                {busy === 'prepare' ? <><span className="spinner" /> Preparing…</> : <><Sparkle /> Prepare application</>}
              </button>
            )}
            {p.tracked_job_id ? (
              <Link className="btn btn-ghost" to="/dashboard"><Bookmark /> In tracker</Link>
            ) : (
              <button className="btn btn-ghost" onClick={track} disabled={!!busy}><Bookmark /> Add to tracker</button>
            )}
            <button className="btn btn-ghost" onClick={refresh} disabled={!!busy} title="Re-check fit with your current resume">
              {busy === 'refresh' ? <span className="spinner" /> : <Refresh />} Re-check
            </button>
            <button className="btn btn-ghost" onClick={toggleArchive} disabled={!!busy}>
              <Trash /> {p.status === 'archived' ? 'Restore' : 'Archive'}
            </button>
          </div>
        </div>
      </section>

      {p.injection_findings?.length > 0 && (
        <div className="alert alert-warn" role="alert" style={{ marginBottom: 18 }}>
          <AlertTriangle />
          <span>
            This posting contains text that looks like instructions aimed at AI tools
            {p.injection_findings[0]?.excerpt ? <> (for example: “{p.injection_findings[0].excerpt}”)</> : null}.
            It is treated as plain text and kept out of AI drafting.
          </span>
        </div>
      )}

      <div className="two-col">
        <div>
          <FitPanel match={p.match} score={p.fit_score} />
          <RolePanel a={p.analysis} />
          <section className="panel">
            <details>
              <summary>Full posting text</summary>
              <div className="posting-text">{p.text}</div>
            </details>
          </section>
        </div>
        <div>
          {p.packages?.length > 0 && (
            <section className="panel">
              <h2 className="panel__title"><Sparkle /> Applications for this role</h2>
              {p.packages.map((k) => (
                <Link key={k.id} to={`/apply/applications/${k.id}`} className="pkg-row">
                  <div><div className="pkg-row__title">Draft {k.version}</div><div className="pkg-row__meta">{formatDate(k.created_at)}</div></div>
                  <StatusPill status={k.status} />
                </Link>
              ))}
            </section>
          )}
          <ResearchPanel r={p.research} />
          <ContactsPanel contacts={p.analysis?.contacts} />
        </div>
      </div>
    </>
  );
}
