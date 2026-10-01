import { useCallback, useEffect, useMemo, useState } from 'react';
import { emailAPI, getErrorCode, getErrorMessage } from '../../api';
import { useToast } from '../../lib/toast';
import ConfirmDialog from '../ConfirmDialog';
import ConnectEmailModal from './ConnectEmailModal';
import EmailDetailModal from './EmailDetailModal';
import ReviewSuggestionModal from './ReviewSuggestionModal';
import SuggestionCard from './SuggestionCard';
import {
  Activity, AlertCircle, AlertTriangle, CheckCircle, Lock, Mail, Refresh, Server, Shield, Unlink,
} from '../icons';
import { CATEGORY, categoryInfo, senderLabel, timeAgo } from '../../lib/emailUi';

const DETECTS = ['application_confirmation', 'interview_invitation', 'rejection', 'offer', 'recruiter_outreach'];
const EMAIL_PAGE = 8;

/**
 * Email intelligence: connect a mailbox, sync, and review what was found.
 * Everything here uses the real backend; there are no simulated states.
 */
export default function EmailPanel({ onJobsChanged }) {
  const { toast } = useToast();

  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');

  const [suggestions, setSuggestions] = useState([]);
  const [emails, setEmails] = useState({ data: [], total: 0 });
  const [emailPage, setEmailPage] = useState(1);

  const [syncing, setSyncing] = useState(false);
  const [syncResult, setSyncResult] = useState(null);
  const [testing, setTesting] = useState(false);
  const [cooldownUntil, setCooldownUntil] = useState(0);
  const [now, setNow] = useState(() => Date.now());

  const [connectOpen, setConnectOpen] = useState(null);      // {provider, email, reconnect}
  const [confirmDisconnect, setConfirmDisconnect] = useState(false);
  const [purge, setPurge] = useState(false);
  const [reviewing, setReviewing] = useState(null);
  const [viewEmailId, setViewEmailId] = useState(null);
  const [busyId, setBusyId] = useState(null);

  const applyStatus = useCallback((s) => {
    setStatus(s);
    const remaining = s?.sync?.cooldown_seconds_remaining || 0;
    setCooldownUntil(remaining > 0 ? Date.now() + remaining * 1000 : 0);
  }, []);

  const loadStatus = useCallback(async () => {
    try {
      const res = await emailAPI.getStatus();
      applyStatus(res.data);
      setLoadError('');
      return res.data;
    } catch (err) {
      setLoadError(getErrorMessage(err, 'Couldn’t load your email connection.'));
      return null;
    } finally {
      setLoading(false);
    }
  }, [applyStatus]);

  const loadData = useCallback(async (page = 1) => {
    try {
      const [sugg, msgs] = await Promise.all([
        emailAPI.listSuggestions({ review_status: 'pending', limit: 50 }),
        emailAPI.listMessages({ page: 1, limit: EMAIL_PAGE * page }),
      ]);
      setSuggestions(sugg.data.data);
      setEmails(msgs.data);
    } catch (err) {
      toast(getErrorMessage(err, 'Couldn’t load email results.'), 'error');
    }
  }, [toast]);

  useEffect(() => {
    loadStatus().then((s) => {
      if (s && (s.state !== 'not_connected' || s.pending_suggestions > 0)) loadData();
    });
  }, [loadStatus, loadData]);

  // Cooldown countdown (server-enforced; this only mirrors it in the UI).
  useEffect(() => {
    if (!cooldownUntil) return undefined;
    const t = setInterval(() => {
      setNow(Date.now());
      if (Date.now() >= cooldownUntil) setCooldownUntil(0);
    }, 1000);
    return () => clearInterval(t);
  }, [cooldownUntil]);
  const cooldown = cooldownUntil ? Math.max(0, Math.ceil((cooldownUntil - now) / 1000)) : 0;

  // ---------------------------------------------------------------- actions
  const onConnected = (s) => {
    applyStatus(s);
    setConnectOpen(null);
    setSyncResult(null);
    toast(`${s.provider_name} connected — ${s.email}`, 'success');
    loadData();
  };

  const runSync = async () => {
    setSyncing(true);
    setSyncResult(null);
    try {
      const res = await emailAPI.sync();
      applyStatus(res.data.status);
      const s = res.data.summary;
      setSyncResult({ summary: s });
      toast(s.status === 'partial' ? 'Sync finished with some issues' : 'Sync complete', s.status === 'partial' ? 'info' : 'success');
      await loadData(emailPage);
    } catch (err) {
      setSyncResult({ error: getErrorMessage(err, 'Email sync failed.'), code: getErrorCode(err) });
      loadStatus();
    } finally {
      setSyncing(false);
    }
  };

  const runTest = async () => {
    setTesting(true);
    try {
      const res = await emailAPI.testConnection();
      applyStatus(res.data.status);
      toast(res.data.message, res.data.ok ? 'success' : 'error');
    } catch (err) {
      toast(getErrorMessage(err, 'Connection test failed.'), 'error');
    } finally {
      setTesting(false);
    }
  };

  const disconnect = async () => {
    try {
      const res = await emailAPI.disconnect({ delete_imported_emails: purge });
      applyStatus(res.data);
      setSyncResult(null);
      setConfirmDisconnect(false);
      if (purge) { setSuggestions([]); setEmails({ data: [], total: 0 }); }
      toast(purge ? 'Email disconnected and imported data deleted' : 'Email disconnected', 'success');
      setPurge(false);
      if (!purge) loadData();
    } catch (err) {
      toast(getErrorMessage(err, 'Could not disconnect.'), 'error');
    }
  };

  const afterReview = async (message) => {
    toast(message, 'success');
    await Promise.all([loadData(emailPage), loadStatus()]);
    onJobsChanged?.();
  };

  const acceptNew = async (data) => {
    // Errors propagate to JobForm, which shows them inline.
    const res = await emailAPI.acceptSuggestion(reviewing.id, data);
    setReviewing(null);
    await afterReview(`Added “${res.data.job.position}” at ${res.data.job.company} to your jobs`);
  };

  const applyUpdate = async (s) => {
    setBusyId(s.id);
    try {
      const res = await emailAPI.acceptSuggestion(s.id, {});
      await afterReview(`${res.data.job.company} moved to ${res.data.job.status}`);
    } catch (err) {
      toast(getErrorMessage(err, 'Could not update the job.'), 'error');
      loadData(emailPage);
    } finally {
      setBusyId(null);
    }
  };

  const dismiss = async (s) => {
    setBusyId(s.id);
    try {
      await emailAPI.dismissSuggestion(s.id);
      setSuggestions((list) => list.filter((x) => x.id !== s.id));
      setStatus((st) => (st ? { ...st, pending_suggestions: Math.max(0, st.pending_suggestions - 1) } : st));
      toast('Suggestion ignored', 'info');
    } catch (err) {
      toast(getErrorMessage(err, 'Could not dismiss that suggestion.'), 'error');
      loadData(emailPage);
    } finally {
      setBusyId(null);
    }
  };

  const showMoreEmails = async () => {
    const next = emailPage + 1;
    setEmailPage(next);
    await loadData(next);
  };

  // ---------------------------------------------------------------- render
  const state = status?.state;
  const linked = state === 'connected' || state === 'needs_attention';
  const sync = status?.sync;
  const openConnect = (provider, reconnect = false) =>
    setConnectOpen({ provider, email: reconnect ? status?.email || '' : '', reconnect });

  const syncLine = useMemo(() => {
    if (!sync) return null;
    if (!sync.last_sync_at) return `Not synced yet. Your first sync scans the last ${status.limits.default_days} days.`;
    return `Last synced ${timeAgo(sync.last_sync_at)} · ${sync.last_scanned} checked · ${sync.last_job_related} job-related · ${sync.last_new_suggestions} new`;
  }, [sync, status, now]); // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <section className="panel email-panel" aria-labelledby="email-intel-title" aria-busy={syncing || undefined}>
      <div className="email-panel__head">
        <div className="panel__title" id="email-intel-title"><Activity /> Email intelligence</div>
        {status && (
          <span className="chip" title={status.ai_enabled
            ? 'Emails are classified by rules, then refined by an AI model. You review everything.'
            : 'Emails are classified by rule-based matching. No AI model is configured.'}>
            {status.ai_enabled ? 'AI extraction on' : 'Rule-based detection'}
          </span>
        )}
      </div>

      {loading ? (
        <div className="email-loading" role="status"><span className="spinner" /> Checking email connection…</div>
      ) : loadError ? (
        <div className="alert alert-error" role="alert">
          <AlertCircle /><span>{loadError}</span>
          <button className="btn btn-ghost btn-sm alert__action" onClick={() => { setLoadError(''); setLoading(true); loadStatus(); }}>Retry</button>
        </div>
      ) : !linked ? (
        <>
          {state === 'legacy_reconnect' && (
            <div className="alert alert-warn" role="note"><AlertTriangle /><span>{status.status_detail}</span></div>
          )}
          <div className="connect-hero">
            <div className="connect-hero__copy">
              <h3>Connect your email</h3>
              <p>Career Platform scans your inbox for job updates and suggests changes. You review every suggestion before it touches your jobs.</p>
              <ul className="detect-list" aria-label="What gets detected">
                {DETECTS.map((c) => (
                  <li key={c}><span className="legend-dot" style={{ background: CATEGORY[c].color }} />{CATEGORY[c].label}</li>
                ))}
              </ul>
              <p className="fine-print"><Lock /> Read-only · nothing is marked as read · only job-related emails are kept · disconnect anytime</p>
            </div>
            <div className="connect-hero__cta">
              <button className="btn btn-primary" onClick={() => openConnect('gmail')}><Mail /> Connect Gmail</button>
              <button className="btn btn-ghost" onClick={() => openConnect('imap')}><Server /> Other IMAP provider</button>
            </div>
          </div>
        </>
      ) : (
        <>
          <div className="email-account">
            <span className="email-account__ic"><Mail /></span>
            <div className="email-account__id">
              <div className="email-account__line">
                <b>{status.provider_name}</b>
                {state === 'connected'
                  ? <span className="status-dot status-dot--ok">Connected</span>
                  : <span className="status-dot status-dot--warn">Needs attention</span>}
              </div>
              <div className="muted email-account__addr">{status.email}</div>
            </div>
            <div className="email-account__actions">
              {state === 'connected' ? (
                <button className="btn btn-primary" onClick={runSync} disabled={syncing || cooldown > 0}
                  title={cooldown > 0 ? 'Syncs are limited to protect your mailbox' : undefined}>
                  {syncing ? <><span className="spinner" /> Syncing…</> : cooldown > 0 ? `Sync in ${cooldown}s` : <><Refresh /> Sync now</>}
                </button>
              ) : (
                <button className="btn btn-primary" onClick={() => openConnect(status.provider, true)}>Reconnect</button>
              )}
              {state === 'connected' && (
                <button className="btn btn-ghost" onClick={runTest} disabled={testing || syncing}>
                  {testing ? <><span className="spinner" /> Testing…</> : 'Test'}
                </button>
              )}
              <button className="btn btn-ghost" onClick={() => setConfirmDisconnect(true)} disabled={syncing}>
                <Unlink /> Disconnect
              </button>
            </div>
          </div>

          {state === 'needs_attention' && (
            <div className="alert alert-warn" role="alert">
              <AlertTriangle />
              <span><b>Credentials need attention.</b> {status.status_detail || 'Your email credentials could not be verified.'}</span>
            </div>
          )}

          <div className="sync-line" role="status">
            {syncing ? <><span className="spinner" /> Scanning your inbox…</> : <><Refresh /> {syncLine}</>}
          </div>
          {!syncing && !syncResult && sync?.last_status === 'failed' && sync.last_error && (
            <div className="sync-note sync-note--error"><AlertCircle /> Last sync failed: {sync.last_error}</div>
          )}

          {syncResult?.summary && (
            <div className={`sync-result ${syncResult.summary.status === 'partial' ? 'sync-result--warn' : ''}`} role="status">
              {syncResult.summary.status === 'partial' ? <AlertTriangle /> : <CheckCircle />}
              <div>
                <b>{syncResult.summary.status === 'partial' ? 'Sync finished with some issues' : 'Sync complete'}</b>
                <div className="sync-result__stats">
                  <span><b>{syncResult.summary.scanned}</b> emails checked</span>
                  <span><b>{syncResult.summary.job_related}</b> job-related</span>
                  <span><b>{syncResult.summary.new_suggestions}</b> new {syncResult.summary.new_suggestions === 1 ? 'opportunity' : 'opportunities'}</span>
                  {syncResult.summary.updated_suggestions > 0 && <span><b>{syncResult.summary.updated_suggestions}</b> updated</span>}
                </div>
                {syncResult.summary.message && <div className="dim">{syncResult.summary.message}</div>}
              </div>
              <button className="toast__close" onClick={() => setSyncResult(null)} aria-label="Dismiss">×</button>
            </div>
          )}
          {syncResult?.error && (
            <div className="alert alert-error" role="alert">
              <AlertCircle />
              <span><b>Email sync failed.</b> {syncResult.error}</span>
              {['auth_failed', 'reconnect_required', 'unsafe_host'].includes(syncResult.code) ? (
                <button className="btn btn-ghost btn-sm alert__action" onClick={() => openConnect(status.provider, true)}>Reconnect</button>
              ) : syncResult.code !== 'cooldown' && syncResult.code !== 'sync_in_progress' ? (
                <button className="btn btn-ghost btn-sm alert__action" onClick={runSync} disabled={cooldown > 0}>Retry</button>
              ) : null}
            </div>
          )}
        </>
      )}

      {/* Review queue — shown whenever there is something to review */}
      {!loading && !loadError && (linked || suggestions.length > 0) && (
        <div className="email-section">
          <div className="email-section__head">
            <h3>Found in your inbox</h3>
            {suggestions.length > 0 && <span className="count-badge">{suggestions.length}</span>}
            <span className="dim">Nothing is added to your jobs until you approve it.</span>
          </div>
          {suggestions.length === 0 ? (
            <p className="empty-line">
              <Shield /> {sync?.last_sync_at ? 'You’re all caught up. No new opportunities to review.' : 'Run a sync to find job updates in your inbox.'}
            </p>
          ) : (
            <div className="suggestions">
              {suggestions.map((s) => (
                <SuggestionCard key={s.id} suggestion={s} busy={busyId === s.id}
                  onReview={setReviewing} onApplyUpdate={applyUpdate} onDismiss={dismiss} onViewEmail={setViewEmailId} />
              ))}
            </div>
          )}
        </div>
      )}

      {!loading && !loadError && emails.total > 0 && (
        <details className="email-section email-list-wrap">
          <summary>
            <span>Job-related emails</span> <span className="count-badge">{emails.total}</span>
          </summary>
          <ul className="email-list">
            {emails.data.map((m) => {
              const cat = categoryInfo(m.category);
              return (
                <li key={m.id}>
                  <button type="button" className="email-row" onClick={() => setViewEmailId(m.id)}>
                    <span className="email-row__from">{senderLabel(m)}</span>
                    <span className="email-row__subject">{m.subject || '(no subject)'}</span>
                    <span className="badge" style={{ '--badge-color': cat.color }}>{cat.label}</span>
                    <span className="email-row__time">{timeAgo(m.received_at)}</span>
                  </button>
                </li>
              );
            })}
          </ul>
          {emails.data.length < emails.total && (
            <button className="btn btn-ghost btn-sm email-list__more" onClick={showMoreEmails}>Show more</button>
          )}
        </details>
      )}

      {connectOpen && (
        <ConnectEmailModal
          initialProvider={connectOpen.provider}
          initialEmail={connectOpen.email}
          reconnect={connectOpen.reconnect}
          onClose={() => setConnectOpen(null)}
          onConnected={onConnected}
        />
      )}
      {confirmDisconnect && (
        <ConfirmDialog
          title="Disconnect your email?"
          message="Your saved email credentials will be deleted and syncing will stop. Jobs you’ve added are never deleted."
          confirmLabel="Disconnect"
          onConfirm={disconnect}
          onCancel={() => { setConfirmDisconnect(false); setPurge(false); }}
        >
          <label className="checkbox">
            <input type="checkbox" checked={purge} onChange={(e) => setPurge(e.target.checked)} />
            <span>Also delete imported emails and pending suggestions</span>
          </label>
        </ConfirmDialog>
      )}
      {reviewing && (
        <ReviewSuggestionModal suggestion={reviewing} onClose={() => setReviewing(null)}
          onAccept={acceptNew} onViewEmail={setViewEmailId} />
      )}
      {viewEmailId && <EmailDetailModal emailId={viewEmailId} onClose={() => setViewEmailId(null)} />}
    </section>
  );
}
