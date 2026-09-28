import { STATUSES, STATUS_LABEL, STATUS_COLOR, PIPELINE_ORDER } from '../constants';
import { BarChart } from './icons';

/**
 * Visual application pipeline. Widths are proportional to real counts from the
 * /jobs/stats endpoint — never fabricated.
 */
export default function Pipeline({ stats }) {
  const counts = PIPELINE_ORDER.map((s) => ({ status: s, n: stats?.[s] || 0 }));
  const total = counts.reduce((a, c) => a + c.n, 0);

  return (
    <div className="panel">
      <div className="panel__title"><BarChart /> Application pipeline</div>
      <div className="pipeline" role="img" aria-label={`Pipeline: ${counts.map((c) => `${STATUS_LABEL[c.status]} ${c.n}`).join(', ')}`}>
        {total === 0 ? (
          <div className="pipeline__empty"><span className="dim" style={{ fontSize: 11 }}>No applications yet</span></div>
        ) : (
          counts.filter((c) => c.n > 0).map((c) => (
            <div
              key={c.status}
              className="pipeline__seg"
              style={{ width: `${(c.n / total) * 100}%`, background: STATUS_COLOR[c.status] }}
              title={`${STATUS_LABEL[c.status]}: ${c.n}`}
            />
          ))
        )}
      </div>
      <div className="pipeline-legend">
        {STATUSES.map((s) => (
          <span className="legend-item" key={s.value}>
            <span className="legend-dot" style={{ background: s.color }} />
            {s.label} <b>{stats?.[s.value] || 0}</b>
          </span>
        ))}
      </div>
    </div>
  );
}
