import { motion } from 'framer-motion';
import CompanyLogo from './CompanyLogo';
import { rise } from './motion';
import { STATUSES, STATUS_COLOR } from '../constants';
import { Edit, Trash, MapPin, Money, Calendar, LinkIcon } from './icons';

export function formatSalary(min, max) {
  const f = (n) => (n >= 1000 ? `$${Math.round(n / 1000)}k` : `$${n}`);
  if (min && max) return `${f(min)} – ${f(max)}`;
  if (min) return `From ${f(min)}`;
  if (max) return `Up to ${f(max)}`;
  return null;
}

export function formatDate(d) {
  if (!d) return null;
  // Dates are YYYY-MM-DD; parse as local time so the day never shifts.
  const [y, m, day] = String(d).slice(0, 10).split('-').map(Number);
  const date = new Date(y, (m || 1) - 1, day || 1);
  const sameYear = date.getFullYear() === new Date().getFullYear();
  return date.toLocaleDateString(undefined, { month: 'short', day: 'numeric', ...(sameYear ? {} : { year: 'numeric' }) });
}

/** Status shown as a coloured pill that is also a native select: change status in one click. */
export function StatusSelect({ job, onChange, disabled }) {
  return (
    <span className="status-select" style={{ '--badge-color': STATUS_COLOR[job.status] || 'var(--st-saved)' }}>
      <select
        value={job.status}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value)}
        aria-label={`Status for ${job.position} at ${job.company}`}
      >
        {STATUSES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
      </select>
    </span>
  );
}

/** One application as a scannable row (list view). Collapses to a card on small screens. */
export default function JobCard({ job, onEdit, onDelete, onStatusChange, busy }) {
  const salary = formatSalary(job.salary_min, job.salary_max);
  const date = formatDate(job.applied_date);

  return (
    <motion.article className="job-row" variants={rise} style={{ '--job-accent': STATUS_COLOR[job.status] }}>
      <CompanyLogo name={job.company} size={40} />

      <div className="job-row__main">
        <h3 className="job-row__pos">
          <button type="button" className="job-row__open" onClick={onEdit}>{job.position}</button>
        </h3>
        <div className="job-row__co">
          <span>{job.company}</span>
          {job.notes && <span className="job-row__notes" title={job.notes}>{job.notes}</span>}
        </div>
      </div>

      <div className="job-row__status"><StatusSelect job={job} onChange={onStatusChange} disabled={busy} /></div>

      <div className="job-row__meta">
        <span className={`meta ${job.location ? '' : 'meta--empty'}`}><MapPin /> {job.location || 'No location'}</span>
        <span className={`meta ${salary ? '' : 'meta--empty'}`}><Money /> {salary || 'No salary'}</span>
        <span className={`meta ${date ? '' : 'meta--empty'}`}><Calendar /> {date || 'No date'}</span>
      </div>

      <div className="job-row__actions">
        {job.job_url && (
          <a className="icon-btn" href={job.job_url} target="_blank" rel="noopener noreferrer"
            aria-label={`Open posting for ${job.position} at ${job.company} (new tab)`} title="Open posting"><LinkIcon /></a>
        )}
        <button className="icon-btn" onClick={onEdit} aria-label={`Edit ${job.position} at ${job.company}`} title="Edit"><Edit /></button>
        <button className="icon-btn danger" onClick={onDelete} aria-label={`Delete ${job.position} at ${job.company}`} title="Delete"><Trash /></button>
      </div>
    </motion.article>
  );
}

/** Compact card for the board (kanban) view. */
export function BoardCard({ job, onEdit, onStatusChange, busy }) {
  const salary = formatSalary(job.salary_min, job.salary_max);
  const date = formatDate(job.applied_date);
  return (
    <article className="board-card">
      <div className="board-card__head">
        <CompanyLogo name={job.company} size={32} />
        <div style={{ minWidth: 0 }}>
          <h4><button type="button" className="job-row__open" onClick={onEdit}>{job.position}</button></h4>
          <div className="board-card__co">{job.company}</div>
        </div>
      </div>
      {(job.location || salary || date) && (
        <div className="board-card__meta">
          {job.location && <span><MapPin /> {job.location}</span>}
          {salary && <span><Money /> {salary}</span>}
          {date && <span><Calendar /> {date}</span>}
        </div>
      )}
      <StatusSelect job={job} onChange={onStatusChange} disabled={busy} />
    </article>
  );
}
