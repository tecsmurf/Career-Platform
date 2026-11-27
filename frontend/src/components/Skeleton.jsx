export function JobCardSkeleton() {
  return (
    <div className="job-row job-row--skeleton" aria-hidden="true">
      <div className="sk" style={{ width: 40, height: 40, borderRadius: 10 }} />
      <div className="job-row__main">
        <div className="sk sk-line" style={{ width: '55%', height: 14 }} />
        <div className="sk sk-line" style={{ width: '30%', marginBottom: 0 }} />
      </div>
      <div className="sk sk-badge" />
      <div className="job-row__meta">
        <div className="sk sk-line" style={{ width: 90, marginBottom: 0 }} />
        <div className="sk sk-line" style={{ width: 70, marginBottom: 0 }} />
        <div className="sk sk-line" style={{ width: 60, marginBottom: 0 }} />
      </div>
      <div />
    </div>
  );
}

export function JobsGridSkeleton({ count = 6 }) {
  return (
    <div className="job-list" aria-busy="true" aria-label="Loading applications">
      {Array.from({ length: count }).map((_, i) => <JobCardSkeleton key={i} />)}
    </div>
  );
}
