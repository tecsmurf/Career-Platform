export function JobCardSkeleton() {
  return (
    <div className="skeleton" aria-hidden="true">
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 16 }}>
        <div className="sk sk-badge" />
        <div className="sk" style={{ width: 40, height: 20, borderRadius: 6 }} />
      </div>
      <div className="sk sk-line" style={{ width: '70%', height: 16 }} />
      <div className="sk sk-line" style={{ width: '45%' }} />
      <div style={{ marginTop: 14 }}>
        <div className="sk sk-line" style={{ width: '55%' }} />
        <div className="sk sk-line" style={{ width: '40%', marginBottom: 0 }} />
      </div>
    </div>
  );
}

export function JobsGridSkeleton({ count = 6 }) {
  return (
    <div className="jobs">
      {Array.from({ length: count }).map((_, i) => <JobCardSkeleton key={i} />)}
    </div>
  );
}
