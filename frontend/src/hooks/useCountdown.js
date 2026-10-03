import { useCallback, useEffect, useState } from 'react';

/** Seconds counting down to zero; `start(n)` restarts it. */
export function useCountdown(initial = 0) {
  const [left, setLeft] = useState(Math.max(0, Math.ceil(initial)));

  useEffect(() => {
    if (left <= 0) return undefined;
    const t = setTimeout(() => setLeft((s) => s - 1), 1000);
    return () => clearTimeout(t);
  }, [left]);

  const start = useCallback((seconds) => setLeft(Math.max(0, Math.ceil(Number(seconds) || 0))), []);
  return [left, start];
}
