import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { applyAPI, getErrorMessage } from '../../api';
import { formatDate } from '../../lib/applyUi';
import { AlertCircle, CheckCircle, Mail } from '../../components/icons';
import { Loading, StatusPill } from './parts';

const FILTERS = [
  { value: 'open', label: 'To do' },
  { value: 'ready_for_review', label: 'Needs review' },
  { value: 'approved', label: 'Approved' },
  { value: 'sent', label: 'Sent' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'all', label: 'All' },
];

export default function ApplicationsPage() {
  const [filter, setFilter] = useState('open');
  const [rows, setRows] = useState(null);
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setRows(null);
    setError('');
    try {
      const res = await applyAPI.listPackages(filter);
      setRows(res.data.data);
    } catch (err) {
      setError(getErrorMessage(err, 'Could not load applications.'));
    }
  }, [filter]);

  useEffect(() => { load(); }, [load]);

  return (
    <>
      <div className="toolbar" style={{ marginTop: 0 }}>
        <div className="toolbar__left">
          <h2 className="section-title">Applications</h2>
          <p className="muted" style={{ fontSize: 14 }}>
            Review each draft, edit anything, then approve. Approving freezes that exact version — you send it yourself.
          </p>
          <div className="filters" role="group" aria-label="Filter applications">
            {FILTERS.map((f) => (
              <button key={f.value} className="pill" aria-pressed={filter === f.value} onClick={() => setFilter(f.value)}>{f.label}</button>
            ))}
          </div>
        </div>
      </div>
      {error ? (
        <div className="center-state"><div className="ic"><AlertCircle /></div><h3>Couldn’t load applications</h3><p>{error}</p>
          <button className="btn btn-primary" onClick={load}>Retry</button></div>
      ) : rows === null ? <Loading /> : rows.length === 0 ? (
        <div className="center-state">
          <div className="ic"><CheckCircle /></div>
          <h3>{filter === 'open' ? 'Nothing to review' : 'No applications here'}</h3>
          <p>Open a posting and choose “Prepare application” to get a tailored draft.</p>
          <Link className="btn btn-ghost" to="/apply/postings">Go to postings</Link>
        </div>
      ) : (
        <div>
          {rows.map((k) => (
            <Link key={k.id} to={`/apply/applications/${k.id}`} className="pkg-row">
              <div style={{ minWidth: 0 }}>
                <div className="pkg-row__title">{k.title} <span className="dim" style={{ fontWeight: 600 }}>· {k.company}</span></div>
                <div className="pkg-row__meta">
                  Draft {k.version} · updated {formatDate(k.updated_at)}
                  {k.has_email && <> · <Mail width={12} height={12} /> email draft</>}
                  {k.sent_at && <> · sent {formatDate(k.sent_at)}</>}
                </div>
              </div>
              <StatusPill status={k.status} />
            </Link>
          ))}
        </div>
      )}
    </>
  );
}
