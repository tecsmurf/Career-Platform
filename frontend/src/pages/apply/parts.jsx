import { fitTone, packageStatus } from '../../lib/applyUi';

export function FitRing({ score, large = false }) {
  const { tone } = fitTone(score);
  const has = score !== null && score !== undefined;
  return (
    <div className={`fit ${large ? 'fit--lg' : ''}`} data-tone={tone} style={{ '--pct': has ? score : 0 }}
      role="img" aria-label={has ? `Fit score ${score} out of 100` : 'Not scored yet'}>
      <span>{has ? score : 'n/a'}</span>
    </div>
  );
}

export function ToneLabel({ score }) {
  const { label, tone } = fitTone(score);
  return <span className="tone-label" data-tone={tone}>{label}</span>;
}

export function StatusPill({ status }) {
  const { label, tone } = packageStatus(status);
  return <span className="status-pill" data-tone={tone}>{label}</span>;
}

export function Loading({ label = 'Loading…' }) {
  return <div className="email-loading"><span className="spinner" /> {label}</div>;
}
