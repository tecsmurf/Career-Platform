import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { applyAPI, getErrorMessage } from '../../api';
import { useToast } from '../../lib/toast';
import ConfirmDialog from '../../components/ConfirmDialog';
import { formatDate, parseBoardUrl, parseList } from '../../lib/applyUi';
import { AlertCircle, Inbox, Plus, Refresh, Shield, Trash } from '../../components/icons';
import { Loading } from './parts';

const PROVIDERS = [
  { value: 'greenhouse', label: 'Greenhouse', example: 'boards.greenhouse.io/<board>' },
  { value: 'lever', label: 'Lever', example: 'jobs.lever.co/<board>' },
  { value: 'ashby', label: 'Ashby', example: 'jobs.ashbyhq.com/<board>' },
];

function AddBoard({ onAdded }) {
  const { toast } = useToast();
  const [link, setLink] = useState('');
  const [provider, setProvider] = useState('greenhouse');
  const [token, setToken] = useState('');
  const [company, setCompany] = useState('');
  const [keywords, setKeywords] = useState('');
  const [locations, setLocations] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  const onLink = (value) => {
    setLink(value);
    const parsed = parseBoardUrl(value);
    if (parsed) {
      setProvider(parsed.provider);
      setToken(parsed.board_token);
      if (!company) setCompany(parsed.board_token.replace(/[-_.]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase()));
    }
  };

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    if (!token.trim() || !company.trim()) return setError('Enter the board name and the company name.');
    setBusy(true);
    try {
      const res = await applyAPI.addSource({
        provider, board_token: token.trim().toLowerCase(), company_name: company.trim(),
        keywords: parseList(keywords, 10), locations: parseList(locations, 10),
      });
      toast(`Following ${res.data.company_name}.`, 'success');
      setLink(''); setToken(''); setCompany(''); setKeywords(''); setLocations('');
      onAdded(res.data);
    } catch (err) {
      setError(getErrorMessage(err, 'Could not add that board.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel">
      <h2 className="panel__title"><Plus /> Follow a company’s job board</h2>
      <p className="muted" style={{ fontSize: 14, marginBottom: 14 }}>
        Many companies publish open roles on Greenhouse, Lever or Ashby. Paste their careers link and we’ll pull new
        roles from the board’s public listing — no logins, no scraping of sites that don’t allow it.
      </p>
      <form className="intake" onSubmit={submit}>
        <div className="field">
          <label htmlFor="board-link">Careers page link</label>
          <input id="board-link" className="input" placeholder="https://boards.greenhouse.io/acme" value={link} onChange={(e) => onLink(e.target.value)} />
        </div>
        <div className="form-row">
          <div className="field">
            <label htmlFor="board-provider">Board type</label>
            <select id="board-provider" className="select" value={provider} onChange={(e) => setProvider(e.target.value)}>
              {PROVIDERS.map((p) => <option key={p.value} value={p.value}>{p.label} — {p.example}</option>)}
            </select>
          </div>
          <div className="field">
            <label htmlFor="board-token">Board name</label>
            <input id="board-token" className="input" placeholder="acme" value={token} onChange={(e) => setToken(e.target.value)} maxLength={100} />
          </div>
        </div>
        <div className="field">
          <label htmlFor="board-company">Company name</label>
          <input id="board-company" className="input" value={company} onChange={(e) => setCompany(e.target.value)} maxLength={200} />
        </div>
        <div className="form-row">
          <div className="field">
            <label htmlFor="board-keywords">Only titles containing <span className="dim">(comma-separated, optional)</span></label>
            <input id="board-keywords" className="input" placeholder="engineer, developer" value={keywords} onChange={(e) => setKeywords(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="board-locations">Only these locations <span className="dim">(optional)</span></label>
            <input id="board-locations" className="input" placeholder="remote, london" value={locations} onChange={(e) => setLocations(e.target.value)} />
          </div>
        </div>
        {error && <div className="alert alert-error" role="alert"><AlertCircle /><span>{error}</span></div>}
        <div className="intake__actions">
          <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? <span className="spinner" /> : <><Plus /> Follow board</>}</button>
        </div>
      </form>
    </section>
  );
}

export default function BoardsPage() {
  const { toast } = useToast();
  const [rows, setRows] = useState(null);
  const [error, setError] = useState('');
  const [running, setRunning] = useState(null);
  const [confirm, setConfirm] = useState(null);

  const load = useCallback(async () => {
    setError('');
    try {
      const res = await applyAPI.listSources();
      setRows(res.data.data);
    } catch (err) {
      setError(getErrorMessage(err, 'Could not load your job boards.'));
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const run = async (source) => {
    setRunning(source.id);
    try {
      const res = await applyAPI.runSource(source.id);
      const { new_postings: n, matched_filters: m } = res.data;
      toast(n ? `Imported ${n} new posting${n === 1 ? '' : 's'} from ${source.company_name}.` : `No new roles (${m} match your filters).`,
        n ? 'success' : 'info', 6000);
      load();
    } catch (err) {
      toast(getErrorMessage(err), 'error', 6000);
      load();
    } finally {
      setRunning(null);
    }
  };

  const remove = async () => {
    await applyAPI.deleteSource(confirm.id);
    setConfirm(null);
    toast('Stopped following that board. Postings you already saved are kept.', 'success');
    load();
  };

  return (
    <>
      <AddBoard onAdded={load} />
      <section className="panel">
        <div className="panel__head">
          <h2 className="panel__title"><Inbox /> Boards you follow</h2>
          <Link to="/apply/postings?sort=fit" className="panel__meta">See imported postings</Link>
        </div>
        {error ? <div className="alert alert-error"><AlertCircle /><span>{error}</span></div>
          : rows === null ? <Loading />
          : rows.length === 0 ? <p className="muted" style={{ fontSize: 14 }}>You’re not following any boards yet.</p>
          : rows.map((s) => (
            <div key={s.id} className="source-row">
              <div style={{ minWidth: 0 }}>
                <div className="source-row__name">{s.company_name} <span className="chip">{s.provider}</span></div>
                <div className="source-row__meta">
                  Board “{s.board_token}”
                  {s.keywords.length > 0 && <> · titles: {s.keywords.join(', ')}</>}
                  {s.locations.length > 0 && <> · locations: {s.locations.join(', ')}</>}
                </div>
                <div className="source-row__meta">
                  {s.last_run_at ? <>Last checked {formatDate(s.last_run_at)} — {s.last_status}{s.last_new_count ? ` (${s.last_new_count} new)` : ''}</> : 'Not checked yet'}
                </div>
              </div>
              <div style={{ display: 'flex', gap: 8 }}>
                <button className="btn btn-ghost btn-sm" onClick={() => run(s)} disabled={running !== null}>
                  {running === s.id ? <span className="spinner" /> : <Refresh />} Check now
                </button>
                <button className="icon-btn danger" onClick={() => setConfirm(s)} aria-label={`Stop following ${s.company_name}`}><Trash /></button>
              </div>
            </div>
          ))}
        <p className="fine-print" style={{ marginTop: 14 }}>
          <Shield /> Each check reads one public listing. New roles are analysed and scored against your resume; at most 25 are imported per check.
        </p>
      </section>
      {confirm && (
        <ConfirmDialog title="Stop following this board?" message={`${confirm.company_name} — postings you already saved stay.`}
          confirmLabel="Stop following" onConfirm={remove} onCancel={() => setConfirm(null)} />
      )}
    </>
  );
}
