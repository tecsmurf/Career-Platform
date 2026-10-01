import StatusBadge from '../StatusBadge';
import { ArrowRight, Mail, MapPin, Money } from '../icons';
import { categoryInfo, confidenceInfo, senderLabel, timeAgo } from '../../lib/emailUi';

function salaryText(min, max) {
  if (!min && !max) return null;
  const f = (n) => n.toLocaleString();
  if (min && max) return `${f(min)} – ${f(max)}`;
  return min ? `From ${f(min)}` : `Up to ${f(max)}`;
}

export default function SuggestionCard({ suggestion: s, busy, onReview, onApplyUpdate, onDismiss, onViewEmail }) {
  const cat = categoryInfo(s.category);
  const conf = confidenceInfo(s.confidence);
  const isUpdate = s.kind === 'status_update' && s.matched_job;
  const salary = salaryText(s.salary_min, s.salary_max);

  return (
    <article className="suggestion" aria-busy={busy || undefined}>
      <div className="suggestion__top">
        <span className="badge" style={{ '--badge-color': cat.color }}>{cat.label}</span>
        <span className={`conf conf--${conf.level}`} title="How sure the detector is about this email's category">{conf.label}</span>
      </div>

      {isUpdate ? (
        <>
          <div className="suggestion__title">{s.matched_job.position}</div>
          <div className="suggestion__co">{s.matched_job.company}</div>
          <div className="status-move" aria-label={`Change status from ${s.matched_job.status} to ${s.status}`}>
            <StatusBadge status={s.matched_job.status} /> <ArrowRight /> <StatusBadge status={s.status} />
          </div>
        </>
      ) : (
        <>
          <div className="suggestion__title">
            {s.position || <span className="missing">Position not detected</span>}
          </div>
          <div className="suggestion__co">
            {s.company || <span className="missing">Company not detected</span>}
          </div>
          <div className="suggestion__meta">
            <span className="dim">Adds as</span> <StatusBadge status={s.status} />
            {s.location && <span className="row"><MapPin /> {s.location}</span>}
            {salary && <span className="row"><Money /> {salary}</span>}
          </div>
        </>
      )}

      {s.email && (
        <button type="button" className="suggestion__source" onClick={() => onViewEmail(s.email.id)}
          title="View the email this was detected from">
          <Mail />
          <span className="suggestion__source-text">
            {senderLabel(s.email)} · “{s.email.subject || '(no subject)'}”
          </span>
          <span className="dim">{timeAgo(s.email.received_at)}</span>
        </button>
      )}

      <div className="suggestion__actions">
        {isUpdate ? (
          <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => onApplyUpdate(s)}>
            {busy ? <span className="spinner" /> : 'Update status'}
          </button>
        ) : (
          <button className="btn btn-primary btn-sm" disabled={busy} onClick={() => onReview(s)}>Review &amp; add</button>
        )}
        <button className="btn btn-ghost btn-sm" disabled={busy} onClick={() => onDismiss(s)}>Ignore</button>
        <span className="chip suggestion__method" title={s.extraction_method === 'ai' ? 'Extracted by the AI model' : 'Detected by rule-based matching'}>
          {s.extraction_method === 'ai' ? 'AI' : 'Rules'}
        </span>
      </div>
    </article>
  );
}
