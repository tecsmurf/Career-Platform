import { useCallback, useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { applyAPI, getErrorCode, getErrorMessage } from '../../api';
import { useToast } from '../../lib/toast';
import Modal from '../../components/Modal';
import { copyText, EVENT_LABEL, formatDate, packageAsText } from '../../lib/applyUi';
import {
  AlertCircle, AlertTriangle, Briefcase, Check, CheckCircle, ChevronLeft, Clock, Edit, Lock, Mail, Shield, Sparkle,
} from '../../components/icons';
import { Loading, StatusPill } from './parts';

const BANNER = {
  ready_for_review: {
    tone: 'review', icon: Shield,
    text: 'Review everything below. Approving locks this exact version. Nothing is sent — after approving you submit it yourself.',
  },
  approved: {
    tone: 'approved', icon: CheckCircle,
    text: 'Approved. Copy the final version, submit it on the employer’s site (and send the email from your own account if there is one), then mark it as sent.',
  },
  sent: { tone: 'sent', icon: Check, text: 'You marked this application as sent. It’s in your tracker as “Applied”.' },
  rejected: { tone: 'rejected', icon: AlertCircle, text: 'You rejected this draft. Prepare a new one from the posting if you change your mind.' },
  superseded: { tone: 'muted', icon: Clock, text: 'A newer draft replaced this one.' },
};
const EDITABLE = ['ready_for_review', 'approved'];

function CopyButton({ text, label = 'Copy', small = true }) {
  const { toast } = useToast();
  return (
    <button className={`btn btn-ghost ${small ? 'btn-sm' : ''}`} type="button"
      onClick={async () => toast((await copyText(text)) ? 'Copied.' : 'Copy failed — select the text instead.', 'info', 2000)}>
      {label}
    </button>
  );
}

function TextDoc({ value, editable, onSave, field, rows = 16 }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (!editing) setDraft(value); }, [value, editing]);

  const save = async () => {
    setSaving(true);
    const ok = await onSave({ [field]: draft });
    setSaving(false);
    if (ok) setEditing(false);
  };

  return (
    <>
      <div className="doc-tools">
        <span className="dim" style={{ fontSize: 12.5 }}>{value.length.toLocaleString()} characters</span>
        <div style={{ display: 'flex', gap: 8 }}>
          {!editing && <CopyButton text={value} />}
          {editable && !editing && <button className="btn btn-ghost btn-sm" onClick={() => setEditing(true)}><Edit /> Edit</button>}
        </div>
      </div>
      {editing ? (
        <>
          <textarea className="textarea doc-edit" rows={rows} value={draft} onChange={(e) => setDraft(e.target.value)}
            aria-label={`Edit ${field.replace('_', ' ')}`} />
          <div className="form-actions">
            <button className="btn btn-ghost" onClick={() => { setEditing(false); setDraft(value); }} disabled={saving}>Cancel</button>
            <button className="btn btn-primary" onClick={save} disabled={saving || !draft.trim() || draft === value}>
              {saving ? <span className="spinner" /> : 'Save changes'}
            </button>
          </div>
        </>
      ) : <div className="doc-text">{value}</div>}
    </>
  );
}

function Answers({ answers, editable, onSave }) {
  const [editing, setEditing] = useState(null);
  const [draft, setDraft] = useState('');
  const save = async (index) => {
    const ok = await onSave({ answers: [{ index, answer: draft }] });
    if (ok) setEditing(null);
  };
  return answers.map((a, i) => (
    <div key={i} className={`answer ${a.needs_user_input && !a.answer ? 'needs' : ''}`}>
      <div className="answer__q">{a.question}</div>
      {editing === i ? (
        <>
          <textarea className="textarea" rows={5} value={draft} onChange={(e) => setDraft(e.target.value)} aria-label={`Answer: ${a.question}`} />
          <div className="form-actions">
            <button className="btn btn-ghost btn-sm" onClick={() => setEditing(null)}>Cancel</button>
            <button className="btn btn-primary btn-sm" onClick={() => save(i)} disabled={draft === a.answer}>Save</button>
          </div>
        </>
      ) : (
        <div className="answer__a">{a.answer || <span className="dim">Needs your answer.</span>}</div>
      )}
      <div className="answer__basis">
        {a.edited_by_you ? 'Written by you' : `Based on: ${a.basis}`}
        {editable && editing !== i && (
          <> · <button className="btn-link" onClick={() => { setEditing(i); setDraft(a.answer || ''); }}>{a.answer ? 'Edit' : 'Answer'}</button></>
        )}
      </div>
    </div>
  ));
}

function HowItWasMade({ generation, guard }) {
  if (!generation) return null;
  const letter = generation.cover_letter || {};
  const tailoring = generation.tailoring || {};
  return (
    <section className="panel">
      <h2 className="panel__title"><Sparkle /> How this draft was made</h2>
      <ul className="list">
        <li>Cover letter: {letter.mode === 'llm' ? 'written with AI, then checked against your resume' : 'assembled from your own resume lines'}.</li>
        {letter.ai_draft_discarded && <li>{letter.reason}</li>}
        {letter.ai_unavailable && <li>{letter.ai_unavailable}.</li>}
        {letter.ai_skipped && <li>{letter.ai_skipped}</li>}
        <li>Resume: re-ordered for this role — no lines invented.</li>
      </ul>
      {tailoring.changes?.length > 0 && (<><h3 className="subhead">Resume changes</h3><ul className="list">{tailoring.changes.map((c) => <li key={c}>{c}</li>)}</ul></>)}
      {tailoring.missing_keywords?.length > 0 && (
        <>
          <h3 className="subhead">Asked for, not in your resume</h3>
          <div className="chips">{tailoring.missing_keywords.map((k) => <span key={k} className="chip chip--warn">{k}</span>)}</div>
          <p className="fine-print" style={{ marginTop: 8 }}><AlertCircle /> Add these to your resume only if they’re true.</p>
        </>
      )}
      {guard && (
        <p className="fine-print" style={{ marginTop: 12 }}>
          <Shield /> {Object.values(guard).every((g) => g.ok)
            ? 'Every document was checked: no skills, numbers, credentials or names that aren’t in your resume.'
            : 'Some text could not be verified against your resume — review carefully.'}
        </p>
      )}
    </section>
  );
}

export default function ApplicationDetailPage() {
  const { id } = useParams();
  const { toast } = useToast();
  const [pkg, setPkg] = useState(null);
  const [error, setError] = useState('');
  const [tab, setTab] = useState('cover_letter');
  const [modal, setModal] = useState(null);
  const [busy, setBusy] = useState(false);
  const [reason, setReason] = useState('');
  const [channel, setChannel] = useState('company_site');
  const [warnings, setWarnings] = useState([]);

  const load = useCallback(async () => {
    setError('');
    try {
      const res = await applyAPI.getPackage(id);
      setPkg(res.data);
    } catch (err) {
      setError(getErrorMessage(err, 'Could not load this application.'));
    }
  }, [id]);

  useEffect(() => { load(); }, [load]);

  if (error) {
    return (
      <div className="center-state"><div className="ic"><AlertCircle /></div><h3>Couldn’t open this application</h3><p>{error}</p>
        <Link className="btn btn-ghost" to="/apply/applications">Back to applications</Link></div>
    );
  }
  if (!pkg) return <Loading label="Loading application…" />;

  const payload = pkg.payload || {};
  const data = payload.data || {};
  const who = payload.who || {};
  const editable = EDITABLE.includes(pkg.status);
  const banner = BANNER[pkg.status] || BANNER.superseded;
  const shortId = pkg.payload_hash.slice(0, 10);

  const saveEdit = async (edits) => {
    try {
      const res = await applyAPI.editPackage(pkg.id, pkg.payload_hash, edits);
      setPkg((old) => ({ ...old, ...res.data }));
      setWarnings(res.data.edit_warnings || []);
      toast(res.data.approval_voided ? 'Saved. Your earlier approval no longer applies — review and approve again.' : 'Saved.',
        res.data.approval_voided ? 'warn' : 'success', 6000);
      return true;
    } catch (err) {
      toast(getErrorMessage(err), 'error');
      if (['stale', 'state_changed'].includes(getErrorCode(err))) load();
      return false;
    }
  };

  const act = async (fn, success) => {
    setBusy(true);
    try {
      const res = await fn();
      setPkg((old) => ({ ...old, ...res.data }));
      setModal(null);
      toast(success, 'success');
      load();
    } catch (err) {
      toast(getErrorMessage(err), 'error');
      if (['content_changed', 'state_changed', 'invalid_state'].includes(getErrorCode(err))) load();
    } finally {
      setBusy(false);
    }
  };

  const docTabs = [
    { key: 'cover_letter', label: 'Cover letter' },
    { key: 'resume_text', label: 'Tailored resume' },
    { key: 'answers', label: `Answers${data.answers?.some((a) => a.needs_user_input && !a.answer) ? ' (needs you)' : ''}` },
    ...(data.email ? [{ key: 'email', label: 'Email' }] : []),
  ];
  const finalText = packageAsText(pkg.final || payload);

  return (
    <>
      <Link className="back-link" to="/apply/applications"><ChevronLeft /> All applications</Link>
      <section className="panel">
        <div className="detail-head">
          <div style={{ minWidth: 0 }}>
            <h1>{pkg.title}</h1>
            <div className="co">{pkg.company}</div>
            <div className="posting-card__meta" style={{ marginTop: 10 }}>
              <span>Draft {pkg.version}</span>
              <span>Edit {pkg.payload_version}</span>
              <Link to={`/apply/postings/${pkg.posting_id}`}>View posting</Link>
            </div>
          </div>
          <StatusPill status={pkg.status} />
        </div>
        <div className={`review-banner review-banner--${banner.tone}`}><banner.icon /><span>{banner.text}</span></div>

        <div className="who-grid">
          <div>
            <div className="section-label"><Briefcase /> What</div>
            <p style={{ fontSize: 14 }}>{payload.what}</p>
          </div>
          <div>
            <div className="section-label"><Lock /> Account</div>
            <p style={{ fontSize: 14 }}>{payload.account?.description}</p>
            {payload.account?.your_email && <p className="dim" style={{ fontSize: 13, marginTop: 4 }}>You: {payload.account.your_email}</p>}
          </div>
          <div>
            <div className="section-label"><Mail /> Who</div>
            <p style={{ fontSize: 14 }}>
              {who.employer}
              {who.apply_url && <> · <a href={who.apply_url} target="_blank" rel="noopener noreferrer nofollow">where to apply</a></>}
            </p>
            {who.contact && (
              <div className="fact" style={{ marginTop: 8 }}>
                <div className="fact__value"><b>{who.contact.name || 'Contact'}</b>{who.contact.role ? ` · ${who.contact.role}` : ''}</div>
                {who.contact.email && <div className="fact__src">{who.contact.email}</div>}
                <div className="quote">From the posting: “{who.contact.evidence}”</div>
              </div>
            )}
          </div>
          <div>
            <div className="section-label"><Clock /> Attachments</div>
            <ul className="list">{(payload.attachments || []).map((a) => <li key={a.kind}>{a.name}</li>)}</ul>
          </div>
        </div>
      </section>

      {['ready_for_review', 'approved'].includes(pkg.status) && (
        <div className="approve-bar">
          <div className="approve-bar__info">Review ID <code>{shortId}</code> — any edit creates a new ID.</div>
          <div className="approve-bar__actions">
            <button className="btn btn-ghost" onClick={() => setModal('reject')}>Reject</button>
            {pkg.status === 'ready_for_review' ? (
              <button className="btn btn-primary" onClick={() => setModal('approve')}><CheckCircle /> Approve this version</button>
            ) : (
              <>
                <CopyButton text={finalText} label="Copy final version" small={false} />
                <button className="btn btn-primary" onClick={() => setModal('sent')}><Check /> Mark as sent</button>
              </>
            )}
          </div>
        </div>
      )}

      {warnings.length > 0 && (
        <div className="alert alert-warn" style={{ marginBottom: 18 }}>
          <AlertTriangle />
          <span>Your edit mentions things that aren’t in your resume: {warnings.slice(0, 3).join('; ')}. Keep them only if they’re true.</span>
        </div>
      )}

      <div className="two-col">
        <div>
          <section className="panel">
            <div className="section-label"><Edit /> Data — what you’ll send</div>
            <div className="doc-tabs" role="tablist">
              {docTabs.map((t) => (
                <button key={t.key} role="tab" className="doc-tab" aria-selected={tab === t.key} onClick={() => setTab(t.key)}>{t.label}</button>
              ))}
            </div>
            {tab === 'cover_letter' && <TextDoc field="cover_letter" value={data.cover_letter || ''} editable={editable} onSave={saveEdit} />}
            {tab === 'resume_text' && <TextDoc field="resume_text" value={data.resume_text || ''} editable={editable} onSave={saveEdit} rows={22} />}
            {tab === 'answers' && <Answers answers={data.answers || []} editable={editable} onSave={saveEdit} />}
            {tab === 'email' && data.email && (
              <>
                <dl className="kv" style={{ marginBottom: 12 }}><dt>To</dt><dd>{data.email.to}</dd></dl>
                <h3 className="subhead">Subject</h3>
                <TextDoc field="email_subject" value={data.email.subject} editable={editable} onSave={saveEdit} rows={2} />
                <h3 className="subhead">Message</h3>
                <TextDoc field="email_body" value={data.email.body} editable={editable} onSave={saveEdit} rows={12} />
              </>
            )}
          </section>
        </div>
        <div>
          <HowItWasMade generation={pkg.generation} guard={pkg.guard} />
          {pkg.events?.length > 0 && (
            <section className="panel">
              <h2 className="panel__title"><Clock /> History</h2>
              <ul className="timeline">
                {pkg.events.map((e, i) => (
                  <li key={i}>
                    <span>
                      {EVENT_LABEL[e.kind] || e.kind}
                      {e.kind === 'edited' && e.detail?.approval_voided ? ' — approval voided' : ''}
                      {e.kind === 'rejected' && typeof e.detail === 'string' ? `: ${e.detail}` : ''}
                    </span>
                    <time>{formatDate(e.at)}</time>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      </div>

      {modal === 'approve' && (
        <Modal title="Approve this version?" onClose={() => !busy && setModal(null)} size="sm">
          <p className="muted" style={{ fontSize: 14 }}>
            You’re approving review ID <code>{shortId}</code>: the cover letter, tailored resume, answers
            {data.email ? ' and email' : ''} exactly as shown. Nothing will be sent — you’ll submit it yourself.
          </p>
          {data.answers?.some((a) => a.needs_user_input && !a.answer) && (
            <div className="alert alert-warn" style={{ marginTop: 12 }}><AlertTriangle /><span>Some answers still need you. You can fill them in on the employer’s form.</span></div>
          )}
          <div className="form-actions" style={{ marginTop: 18 }}>
            <button className="btn btn-ghost" onClick={() => setModal(null)} disabled={busy}>Cancel</button>
            <button className="btn btn-primary" disabled={busy}
              onClick={() => act(() => applyAPI.approvePackage(pkg.id, pkg.payload_hash), 'Approved — your final version is ready to copy.')}>
              {busy ? <span className="spinner" /> : 'Approve'}
            </button>
          </div>
        </Modal>
      )}
      {modal === 'reject' && (
        <Modal title="Reject this draft?" onClose={() => !busy && setModal(null)} size="sm">
          <div className="field">
            <label htmlFor="reject-reason">Reason <span className="dim">(optional, for your history)</span></label>
            <textarea id="reject-reason" className="textarea" rows={3} maxLength={500} value={reason} onChange={(e) => setReason(e.target.value)} />
          </div>
          <div className="form-actions" style={{ marginTop: 18 }}>
            <button className="btn btn-ghost" onClick={() => setModal(null)} disabled={busy}>Cancel</button>
            <button className="btn btn-danger" disabled={busy} onClick={() => act(() => applyAPI.rejectPackage(pkg.id, reason.trim()), 'Draft rejected.')}>
              {busy ? <span className="spinner" /> : 'Reject'}
            </button>
          </div>
        </Modal>
      )}
      {modal === 'sent' && (
        <Modal title="Did you send it?" onClose={() => !busy && setModal(null)} size="sm">
          <p className="muted" style={{ fontSize: 14 }}>Confirm only after you’ve submitted the application yourself. It will move to “Applied” in your tracker.</p>
          <div className="field" style={{ marginTop: 12 }}>
            <label htmlFor="sent-channel">How did you send it?</label>
            <select id="sent-channel" className="select" value={channel} onChange={(e) => setChannel(e.target.value)}>
              <option value="company_site">On the employer’s site</option>
              <option value="email">By email from my account</option>
              <option value="other">Some other way</option>
            </select>
          </div>
          <div className="form-actions" style={{ marginTop: 18 }}>
            <button className="btn btn-ghost" onClick={() => setModal(null)} disabled={busy}>Not yet</button>
            <button className="btn btn-primary" disabled={busy} onClick={() => act(() => applyAPI.markSent(pkg.id, channel), 'Marked as sent and moved to Applied in your tracker.')}>
              {busy ? <span className="spinner" /> : 'Yes, I sent it'}
            </button>
          </div>
        </Modal>
      )}
    </>
  );
}
