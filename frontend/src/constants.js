// Single source of truth for job statuses across the app.
// Must match the backend JobStatus enum exactly.
export const STATUSES = [
  { value: 'saved',     label: 'Saved',     color: 'var(--st-saved)' },
  { value: 'applied',   label: 'Applied',   color: 'var(--st-applied)' },
  { value: 'interview', label: 'Interview', color: 'var(--st-interview)' },
  { value: 'offer',     label: 'Offer',     color: 'var(--st-offer)' },
  { value: 'rejected',  label: 'Rejected',  color: 'var(--st-rejected)' },
];

export const STATUS_VALUES = STATUSES.map((s) => s.value);
export const STATUS_LABEL = Object.fromEntries(STATUSES.map((s) => [s.value, s.label]));
export const STATUS_COLOR = Object.fromEntries(STATUSES.map((s) => [s.value, s.color]));

// Left→right funnel order used by the pipeline and stat row.
export const PIPELINE_ORDER = ['saved', 'applied', 'interview', 'offer', 'rejected'];
