// Presentation helpers for the email integration. Colors reuse the status palette.

export const CATEGORY = {
  application_confirmation: { label: 'Application received', color: 'var(--st-applied)' },
  interview_invitation: { label: 'Interview', color: 'var(--st-interview)' },
  rejection: { label: 'Rejection', color: 'var(--st-rejected)' },
  offer: { label: 'Offer', color: 'var(--st-offer)' },
  recruiter_outreach: { label: 'Recruiter outreach', color: 'var(--st-saved)' },
  job_alert: { label: 'Job alert', color: 'var(--text-dim)' },
  unrelated: { label: 'Other', color: 'var(--text-dim)' },
};

export function categoryInfo(category) {
  return CATEGORY[category] || { label: category || 'Other', color: 'var(--text-dim)' };
}

export function confidenceInfo(value) {
  const v = Number(value) || 0;
  if (v >= 0.8) return { label: 'High confidence', level: 'high' };
  if (v >= 0.6) return { label: 'Medium confidence', level: 'medium' };
  return { label: 'Low confidence', level: 'low' };
}

export function timeAgo(iso) {
  if (!iso) return '';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';
  const s = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (s < 45) return 'just now';
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} hr${h === 1 ? '' : 's'} ago`;
  const d = Math.round(h / 24);
  if (d < 30) return `${d} day${d === 1 ? '' : 's'} ago`;
  return new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
}

export function formatDateTime(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

export function senderLabel(email) {
  return email?.sender_name || email?.sender_email || 'Unknown sender';
}
