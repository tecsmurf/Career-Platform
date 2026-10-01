// Pure helpers for the login screen's error states (unit-tested with node:test).

export const RATE_LIMIT_MESSAGE = 'Too many login attempts. Please wait a moment before trying again.';
export const MAX_COOLDOWN_SECONDS = 60;
const DEFAULT_COOLDOWN_SECONDS = 2;

/**
 * Seconds to wait after a 429, from the Retry-After header (whole seconds —
 * the API exposes it via CORS). Falls back to 2 s; never more than 60 s.
 */
export function retryAfterSeconds(err) {
  const raw = Number.parseInt(err?.response?.headers?.['retry-after'], 10);
  return Number.isFinite(raw) && raw > 0 ? Math.min(raw, MAX_COOLDOWN_SECONDS) : DEFAULT_COOLDOWN_SECONDS;
}

/** idle | invalid | rate_limited | error — what a failed login attempt means for the UI. */
export function loginFailureKind(err) {
  const status = err?.response?.status;
  if (status === 429) return 'rate_limited';
  if (status === 401) return 'invalid';
  return 'error';
}
