const STATUS_COLORS = {
  applied: '#3b82f6',
  interviewing: '#f59e0b',
  offer: '#10b981',
  rejected: '#ef4444',
  withdrawn: '#6b7280',
};

export default function JobCard({ job, onEdit, onDelete }) {
  const statusColor = STATUS_COLORS[job.status] || '#6b7280';

  return (
    <div className="job-card">
      <div className="job-card-header">
        <span className="job-status" style={{ background: statusColor }}>
          {job.status}
        </span>
        <div className="job-actions">
          <button onClick={onEdit} className="btn-icon" title="Edit">✏️</button>
          <button onClick={onDelete} className="btn-icon" title="Delete">🗑️</button>
        </div>
      </div>
      <h3 className="job-position">{job.position}</h3>
      <p className="job-company">{job.company}</p>
      {job.location && <p className="job-location">📍 {job.location}</p>}
      {(job.salary_min || job.salary_max) && (
        <p className="job-salary">
          💰 {job.salary_min ? `$${job.salary_min.toLocaleString()}` : ''}
          {job.salary_min && job.salary_max ? ' - ' : ''}
          {job.salary_max ? `$${job.salary_max.toLocaleString()}` : ''}
        </p>
      )}
      {job.applied_date && (
        <p className="job-date">📅 {new Date(job.applied_date).toLocaleDateString()}</p>
      )}
      {job.notes && <p className="job-notes">{job.notes}</p>}
      {job.job_url && (
        <a href={job.job_url} target="_blank" rel="noopener noreferrer" className="job-link">
          View Posting →
        </a>
      )}
    </div>
  );
}
