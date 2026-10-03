import { useEffect, useState } from 'react';
import { applyAPI, getErrorMessage } from '../../api';
import { useToast } from '../../lib/toast';
import { formatDate, parseList } from '../../lib/applyUi';
import { AlertCircle, Edit, Lock, Shield } from '../../components/icons';
import { Loading } from './parts';

const LINKS = [
  ['linkedin_url', 'LinkedIn'], ['github_url', 'GitHub'], ['portfolio_url', 'Portfolio'], ['website_url', 'Website'],
];

function ProfileForm() {
  const { toast } = useToast();
  const [form, setForm] = useState(null);
  const [lists, setLists] = useState({ target_roles: '', target_locations: '', skills: '' });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    applyAPI.getProfile().then((r) => {
      setForm(r.data);
      setLists({
        target_roles: r.data.target_roles.join(', '),
        target_locations: r.data.target_locations.join(', '),
        skills: r.data.skills.join(', '),
      });
    }).catch((err) => setError(getErrorMessage(err, 'Could not load your profile.')));
  }, []);

  if (!form) return error ? <div className="alert alert-error"><AlertCircle /><span>{error}</span></div> : <Loading />;

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }));

  const save = async (e) => {
    e.preventDefault();
    setError('');
    setBusy(true);
    try {
      const years = form.years_experience === '' || form.years_experience === null ? null : Number(form.years_experience);
      const body = {
        ...form,
        years_experience: Number.isFinite(years) ? years : null,
        target_roles: parseList(lists.target_roles),
        target_locations: parseList(lists.target_locations),
        skills: parseList(lists.skills, 60),
      };
      for (const [key] of LINKS) body[key] = body[key]?.trim() || null;
      const res = await applyAPI.saveProfile(body);
      setForm(res.data);
      toast('Profile saved. Re-check postings to update their fit.', 'success');
    } catch (err) {
      setError(getErrorMessage(err, 'Could not save your profile.'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel">
      <h2 className="panel__title"><Edit /> Profile</h2>
      <form className="intake" onSubmit={save}>
        <div className="form-row">
          <div className="field">
            <label htmlFor="pf-headline">Headline</label>
            <input id="pf-headline" className="input" placeholder="Backend Engineer" value={form.headline || ''} onChange={set('headline')} maxLength={200} />
          </div>
          <div className="field">
            <label htmlFor="pf-years">Years of experience</label>
            <input id="pf-years" className="input" type="number" min={0} max={60} value={form.years_experience ?? ''} onChange={set('years_experience')} />
          </div>
        </div>
        <div className="form-row">
          <div className="field">
            <label htmlFor="pf-roles">Roles you’re targeting</label>
            <input id="pf-roles" className="input" placeholder="Backend Engineer, Platform Engineer" value={lists.target_roles}
              onChange={(e) => setLists((l) => ({ ...l, target_roles: e.target.value }))} />
          </div>
          <div className="field">
            <label htmlFor="pf-locs">Preferred locations</label>
            <input id="pf-locs" className="input" placeholder="Bengaluru, Remote" value={lists.target_locations}
              onChange={(e) => setLists((l) => ({ ...l, target_locations: e.target.value }))} />
          </div>
        </div>
        <div className="form-row">
          <div className="field">
            <label htmlFor="pf-location">Where you live</label>
            <input id="pf-location" className="input" value={form.location || ''} onChange={set('location')} maxLength={200} />
          </div>
          <div className="field">
            <label htmlFor="pf-phone">Phone <span className="dim">(shown in your signature)</span></label>
            <input id="pf-phone" className="input" value={form.phone || ''} onChange={set('phone')} maxLength={40} />
          </div>
        </div>
        <label className="checkbox" style={{ marginTop: 0 }}>
          <input type="checkbox" checked={!!form.open_to_remote} onChange={set('open_to_remote')} /> Open to remote roles
        </label>
        <div className="field">
          <label htmlFor="pf-skills">Extra skills <span className="dim">(only ones not already in your resume)</span></label>
          <input id="pf-skills" className="input" placeholder="Terraform, GraphQL" value={lists.skills}
            onChange={(e) => setLists((l) => ({ ...l, skills: e.target.value }))} />
        </div>
        <div className="field">
          <label htmlFor="pf-summary">Short summary <span className="dim">(optional)</span></label>
          <textarea id="pf-summary" className="textarea" rows={3} maxLength={3000} value={form.summary || ''} onChange={set('summary')} />
        </div>
        <div className="form-row">
          {LINKS.map(([key, label]) => (
            <div className="field" key={key}>
              <label htmlFor={`pf-${key}`}>{label}</label>
              <input id={`pf-${key}`} className="input" type="url" placeholder="https://" value={form[key] || ''} onChange={set(key)} maxLength={300} />
            </div>
          ))}
        </div>
        {error && <div className="alert alert-error" role="alert"><AlertCircle /><span>{error}</span></div>}
        <div className="intake__actions">
          <button className="btn btn-primary" type="submit" disabled={busy}>{busy ? <span className="spinner" /> : 'Save profile'}</button>
        </div>
      </form>
    </section>
  );
}

function ResumeForm() {
  const { toast } = useToast();
  const [data, setData] = useState(null);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    applyAPI.getResume().then((r) => { setData(r.data); setText(r.data.current?.text || ''); })
      .catch((err) => setError(getErrorMessage(err, 'Could not load your resume.')));
  }, []);

  if (!data) return error ? <div className="alert alert-error"><AlertCircle /><span>{error}</span></div> : <Loading />;

  const save = async () => {
    setError('');
    setBusy('save');
    try {
      const res = await applyAPI.saveResume(text);
      setData(res.data);
      toast(`Saved as version ${res.data.current.version}.`, 'success');
    } catch (err) {
      setError(getErrorMessage(err, 'Could not save your resume.'));
    } finally {
      setBusy('');
    }
  };

  const upload = async (e) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;
    setError('');
    setBusy('upload');
    try {
      const res = await applyAPI.uploadResume(file);
      setData(res.data);
      setText(res.data.current.text);
      toast('Resume read. Check the text below — this is exactly what drafts will use.', 'success', 6000);
    } catch (err) {
      setError(getErrorMessage(err, 'Could not read that file.'));
    } finally {
      setBusy('');
    }
  };

  return (
    <section className="panel">
      <div className="panel__head">
        <h2 className="panel__title"><Lock /> Your resume</h2>
        <label className="btn btn-ghost btn-sm file-btn">
          {busy === 'upload' ? <span className="spinner" /> : 'Upload PDF / DOCX / TXT'}
          <input type="file" accept=".pdf,.docx,.txt,.md,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
            onChange={upload} disabled={!!busy} aria-label="Upload resume file" />
        </label>
      </div>
      <p className="muted" style={{ fontSize: 13.5, marginBottom: 10 }}>
        Fit scores and every draft are built only from this text and your profile — nothing is invented.
        {data.current && <> Current: version {data.current.version}{data.current.filename ? ` (${data.current.filename})` : ''}, saved {formatDate(data.current.created_at)}.</>}
      </p>
      <textarea className="textarea" rows={18} value={text} onChange={(e) => setText(e.target.value)} maxLength={40000}
        placeholder="Paste your resume as plain text…" aria-label="Resume text" />
      {error && <div className="alert alert-error" role="alert" style={{ marginTop: 12 }}><AlertCircle /><span>{error}</span></div>}
      <div className="intake__actions" style={{ marginTop: 12 }}>
        <button className="btn btn-primary" onClick={save} disabled={!!busy || text.trim().length < 50 || text === data.current?.text}>
          {busy === 'save' ? <span className="spinner" /> : 'Save as new version'}
        </button>
        {data.versions.length > 1 && <span className="fine-print">{data.versions.length} versions kept — older tailored drafts stay linked to the version they used.</span>}
      </div>
      <p className="fine-print" style={{ marginTop: 14 }}><Shield /> Your resume is stored only in your account and never sent anywhere by the app.</p>
    </section>
  );
}

export default function ProfilePage() {
  return (
    <div className="two-col">
      <div><ResumeForm /></div>
      <div><ProfileForm /></div>
    </div>
  );
}
