import { STATUSES, STATUS_LABEL, STATUS_COLOR, PIPELINE_ORDER } from '../constants';
import { BarChart } from './icons';

/**
 * Application pipeline: a proportional bar plus one tile per stage (count,
 * share, mini bar). Every number comes from /jobs/stats — never fabricated.
 */
export default function Pipeline({ stats }) {
  const counts = PIPELINE_ORDER.map((s) => ({ status: s, n: stats?.[s] || 0 }));
  const total = counts.reduce((a, c) => a + c.n, 0);
  const share = (n) => (total ? Math.round((n / total) * 100) : 0);

  return (
    <section className="panel pipeline-panel" aria-labelledby="pipeline-title">
      <div className="panel__head">
        <h2 className="panel__title" id="pipeline-title"><BarChart /> Application pipeline</h2>
        <span className="panel__meta">{total} {total === 1 ? 'application' : 'applications'}</span>
      </div>

      <div className="pipeline" role="img" aria-label={`Pipeline: ${counts.map((c) => `${STATUS_LABEL[c.status]} ${c.n}`).join(', ')}`}>
        {total === 0 ? (
          <div className="pipeline__empty">No applications yet</div>
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

      <ol className="stages">
        {STATUSES.map((s) => {
          const n = stats?.[s.value] || 0;
          return (
            <li className="stage" key={s.value} style={{ '--stage': s.color }}>
              <span className="stage__label"><span className="legend-dot" style={{ background: s.color }} />{s.label}</span>
              <span className="stage__count">{n}</span>
              <span className="stage__pct">{share(n)}% of total</span>
              <span className="stage__bar" aria-hidden="true"><i style={{ '--w': `${share(n)}%` }} /></span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}
