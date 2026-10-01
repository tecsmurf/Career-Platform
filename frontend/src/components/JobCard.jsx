import StatusBadge from './StatusBadge';
import { CompanyBubble } from './bubbles';
import { STATUS_COLOR } from '../constants';
import { Edit, Trash, MapPin, Money, Calendar, LinkIcon } from './icons';

function formatSalary(min, max) {
  const f = (n) => `$${n.toLocaleString()}`;
  if (min && max) return `${f(min)} – ${f(max)}`;
  if (min) return `From ${f(min)}`;
  if (max) return `Up to ${f(max)}`;
  return null;
}

export default function JobCard({ job, onEdit, onDelete }) {
  const accent = STATUS_COLOR[job.status] || 'var(--border)';
  const salary = formatSalary(job.salary_min, job.salary_max);

  return (
    <article className="job" style={{ '--job-accent': accent }}>
      <div className="job__head">
        {/* one small glass accent: the company's logo (or initials) */}
        <CompanyBubble name={job.company} size={42} compact still />
        <div className="job__title">
          <h3 className="job__pos">{job.position}</h3>
          <div className="job__co">{job.company}</div>
        </div>
        <div className="job__actions">
          <button className="icon-btn" onClick={onEdit} aria-label={`Edit ${job.position} at ${job.company}`}><Edit /></button>
          <button className="icon-btn danger" onClick={onDelete} aria-label={`Delete ${job.position} at ${job.company}`}><Trash /></button>
        </div>
      </div>

      <div className="job__status"><StatusBadge status={job.status} /></div>

      <div className="job__meta">
        {job.location && <div className="row"><MapPin /> {job.location}</div>}
        {salary && <div className="row"><Money /> {salary}</div>}
        {job.applied_date && (
          <div className="row"><Calendar /> {new Date(job.applied_date).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })}</div>
        )}
      </div>

      {job.notes && <p className="job__notes">{job.notes}</p>}

      {job.job_url && (
        <a className="job__link" href={job.job_url} target="_blank" rel="noopener noreferrer">
          <LinkIcon /> View posting
        </a>
      )}
    </article>
  );
}
