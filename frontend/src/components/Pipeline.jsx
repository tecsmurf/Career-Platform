import { STATUSES, STATUS_LABEL, STATUS_COLOR, PIPELINE_ORDER } from '../constants';

/**
 * Application pipeline: one proportional bar plus a legend where every stage is
 * a filter button. Every number comes from /jobs/stats — never fabricated.
 */
export default function Pipeline({ stats, active = 'all', onSelect }) {
  const counts = PIPELINE_ORDER.map((s) => ({ status: s, n: stats?.[s] || 0 }));
  const total = counts.reduce((a, c) => a + c.n, 0);
  const share = (n) => (total ? Math.round((n / total) * 100) : 0);

  return (
    <div className="pipeline-wrap">
      <div className="pipeline" role="img" aria-label={`Pipeline: ${counts.map((c) => `${STATUS_LABEL[c.status]} ${c.n}`).join(', ')}`}>
        {total === 0 ? (
          <div className="pipeline__empty" />
        ) : (
          counts.filter((c) => c.n > 0).map((c) => (
            <div
              key={c.status}
              className="pipeline__seg"
              style={{ width: `${(c.n / total) * 100}%`, backgroundColor: STATUS_COLOR[c.status] }}
              title={`${STATUS_LABEL[c.status]}: ${c.n}`}
            />
          ))
        )}
      </div>

      <ul className="stages" aria-label="Filter by stage">
        {STATUSES.map((s) => {
          const n = stats?.[s.value] || 0;
          return (
            <li key={s.value}>
              <button
                type="button"
                className="stage"
                aria-pressed={active === s.value}
                onClick={() => onSelect?.(active === s.value ? 'all' : s.value)}
              >
                <span className="legend-dot" style={{ background: s.color }} />
                <span className="stage__label">{s.label}</span>
                <span className="stage__count">{n}</span>
                <span className="stage__pct">{share(n)}%</span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
