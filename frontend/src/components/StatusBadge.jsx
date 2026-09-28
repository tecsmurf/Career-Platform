import { STATUS_LABEL, STATUS_COLOR } from '../constants';

export default function StatusBadge({ status }) {
  const label = STATUS_LABEL[status] || status;
  const color = STATUS_COLOR[status] || 'var(--st-saved)';
  return (
    <span className="badge" style={{ '--badge-color': color }}>{label}</span>
  );
}
