// Pure helpers for the email-code screens (unit-tested with node:test).

export const CODE_LENGTH = 6;
export const MIN_PASSWORD = 6;

/** Keep digits only (people paste "123 456" or "123-456"), at most 6. */
export function normalizeCode(value) {
  return String(value ?? '').replace(/\D/g, '').slice(0, CODE_LENGTH);
}

export function isCompleteCode(code) {
  return new RegExp(`^\\d{${CODE_LENGTH}}$`).test(String(code ?? ''));
}

/** '' when the new password is acceptable, otherwise a short message. */
export function passwordProblem(password, confirm) {
  if (!password || password.length < MIN_PASSWORD) return `Password must be at least ${MIN_PASSWORD} characters.`;
  if (password.length > 100) return 'Password must be at most 100 characters.';
  if (password !== confirm) return 'The two passwords don’t match.';
  return '';
}

/** 42 → "42s", 75 → "1:15". */
export function formatCountdown(seconds) {
  const s = Math.max(0, Math.ceil(Number(seconds) || 0));
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/** Plausible enough to send to the server (the server does the real check). */
export function looksLikeEmail(value) {
  return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(String(value ?? '').trim());
}

/** Whole seconds from a Retry-After header, clamped to [1, max]; fallback if missing. */
export function retryAfterFrom(err, fallback = 60, max = 3600) {
  const raw = Number.parseInt(err?.response?.headers?.['retry-after'], 10);
  if (!Number.isFinite(raw) || raw <= 0) return fallback;
  return Math.min(raw, max);
}
