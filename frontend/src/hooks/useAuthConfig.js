import { useEffect, useState } from 'react';
import { authAPI } from '../api';

// Which email features the server has switched on. Fetched once per page load;
// until it arrives (or if it fails) the features are treated as off, so the UI
// never offers something the server can't do.
const OFF = { email_verification: false, password_reset: false, resend_seconds: 60, code_ttl_minutes: 15, loaded: false };
let cached = null;
let pending = null;

function load() {
  if (!pending) {
    pending = authAPI.config()
      .then((res) => { cached = { ...OFF, ...res.data, loaded: true }; return cached; })
      .catch(() => { pending = null; return { ...OFF, loaded: true, failed: true }; });
  }
  return pending;
}

export function useAuthConfig() {
  const [config, setConfig] = useState(cached || OFF);
  useEffect(() => {
    if (cached) return undefined;
    let alive = true;
    load().then((c) => { if (alive) setConfig(c); });
    return () => { alive = false; };
  }, []);
  return config;
}
