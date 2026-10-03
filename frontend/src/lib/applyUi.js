// Small pure helpers for the Apply Assistant screens (unit-tested with node:test).

/** Fit score → label + tone. `null` means "can't score yet" (no resume). */
export function fitTone(score) {
  if (score === null || score === undefined) return { label: 'Add resume to score', tone: 'none' };
  if (score >= 75) return { label: 'Strong fit', tone: 'strong' };
  if (score >= 50) return { label: 'Possible fit', tone: 'possible' };
  return { label: 'Stretch', tone: 'stretch' };
}

export const PACKAGE_STATUS = {
  ready_for_review: { label: 'Needs review', tone: 'review' },
  approved: { label: 'Approved — ready to send', tone: 'approved' },
  sent: { label: 'Sent', tone: 'sent' },
  rejected: { label: 'Rejected', tone: 'rejected' },
  superseded: { label: 'Replaced by a newer draft', tone: 'muted' },
};

export function packageStatus(status) {
  return PACKAGE_STATUS[status] || { label: status || 'Unknown', tone: 'muted' };
}

/** "a, b ,, c" → ["a", "b", "c"] (trimmed, de-duplicated case-insensitively, capped). */
export function parseList(text, max = 15) {
  const seen = new Set();
  const out = [];
  for (const raw of String(text || '').split(/[,\n]/)) {
    const item = raw.trim();
    const key = item.toLowerCase();
    if (!item || seen.has(key)) continue;
    seen.add(key);
    out.push(item);
    if (out.length >= max) break;
  }
  return out;
}

const BOARD_PATTERNS = [
  { provider: 'greenhouse', re: /^https?:\/\/(?:boards|job-boards)(?:\.eu)?\.greenhouse\.io\/([a-z0-9._-]+)/i },
  { provider: 'lever', re: /^https?:\/\/jobs(?:\.eu)?\.lever\.co\/([a-z0-9._-]+)/i },
  { provider: 'ashby', re: /^https?:\/\/jobs\.ashbyhq\.com\/([a-z0-9._-]+)/i },
];

/** A careers-page link pasted by the user → {provider, board_token} or null. */
export function parseBoardUrl(url) {
  const value = String(url || '').trim();
  for (const { provider, re } of BOARD_PATTERNS) {
    const m = value.match(re);
    if (m) return { provider, board_token: m[1].toLowerCase() };
  }
  return null;
}

/** Human labels for package history events. */
export const EVENT_LABEL = {
  created: 'Draft prepared',
  edited: 'Edited',
  approved: 'Approved',
  rejected: 'Rejected',
  marked_sent: 'Marked as sent',
  superseded: 'Replaced by a newer draft',
};

/** Plain-text version of a whole package, for "copy everything". */
export function packageAsText(payload) {
  const d = payload?.data || {};
  const parts = [];
  if (d.cover_letter) parts.push(`COVER LETTER\n\n${d.cover_letter}`);
  if (d.answers?.length) {
    parts.push('APPLICATION ANSWERS\n\n' + d.answers
      .map((a) => `${a.question}\n${a.answer || '[needs your answer]'}`)
      .join('\n\n'));
  }
  if (d.email) parts.push(`EMAIL\nTo: ${d.email.to}\nSubject: ${d.email.subject}\n\n${d.email.body}`);
  if (d.resume_text) parts.push(`TAILORED RESUME\n\n${d.resume_text}`);
  return parts.join('\n\n────────\n\n');
}

export function formatDate(iso) {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

export async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}
