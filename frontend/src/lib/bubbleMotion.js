// Depth layers and per-bubble motion for the floating bubbles (pure; unit-tested).

// Far bubbles are smaller (perspective), fainter, softer, slower and react
// less to the pointer; near ones are crisp, bolder and more mobile.
export const DEPTH = {
  near: { z: 40, opacity: 1, blur: 0, parallax: 22, amp: 1, speed: 1 },
  mid: { z: -70, opacity: 0.92, blur: 0, parallax: 12, amp: 0.75, speed: 1.25 },
  far: { z: -160, opacity: 0.6, blur: 1.4, parallax: 5, amp: 0.5, speed: 1.6 },
};

// Small deterministic PRNG (FNV-1a seed → mulberry32): stable per bubble.
export function seeded(seed) {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i += 1) { h ^= seed.charCodeAt(i); h = Math.imul(h, 16777619); }
  return () => {
    h += 0x6d2b79f5;
    let t = h;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/**
 * Timing for one bubble: ~12–20 s cycles (slower when far), ~16–30 px drift,
 * ±6° logo sway, and a negative delay so no two bubbles start in sync.
 * `motion` overrides duration / amplitude / rotation.
 */
export function bubbleMotion(seed, depth = 'mid', motion = {}) {
  const d = DEPTH[depth] || DEPTH.mid;
  const rnd = seeded(seed);
  const duration = motion.duration ?? (12 + rnd() * 8) * d.speed;
  const ampY = motion.amplitude ?? (16 + rnd() * 14) * d.amp;
  const ampX = (rnd() * 2 - 1) * ampY * 0.6;
  const rotation = motion.rotation ?? (rnd() * 2 - 1) * 6;
  const delay = -(rnd() * duration);
  return { ...d, duration, ampY, ampX, rotation, delay };
}
