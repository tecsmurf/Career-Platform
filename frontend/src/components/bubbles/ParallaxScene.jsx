import { useEffect, useRef } from 'react';
import { useReducedMotion } from '../../hooks/useReducedMotion';

/**
 * A 3D stage (CSS perspective) for floating bubbles.
 *
 * - Mouse parallax: one rAF-throttled listener writes --mx/--my (-1…1); each
 *   bubble shifts by its own depth factor, so near ones move more.
 * - Hover without hijacking the page: bubbles keep `pointer-events: none`;
 *   the bubble under the cursor is lit via [data-hot] only when the cursor is
 *   over empty space (body or an element marked `data-bubble-pass`), never
 *   when it is over a card, form or button.
 * - Off for reduced-motion users and touch-only devices.
 */
export default function ParallaxScene({ className = '', interactive = true, children }) {
  const ref = useRef(null);
  const reduced = useReducedMotion();

  useEffect(() => {
    const el = ref.current;
    if (!el || reduced || !interactive) return undefined;
    if (window.matchMedia?.('(hover: none)').matches) return undefined;

    let raf = 0;
    let px = -1;
    let py = -1;
    let hot = null;

    const setHot = (node) => {
      if (node === hot) return;
      hot?.removeAttribute('data-hot');
      node?.setAttribute('data-hot', '');
      hot = node;
    };

    const update = () => {
      raf = 0;
      el.style.setProperty('--mx', ((px / window.innerWidth) * 2 - 1).toFixed(3));
      el.style.setProperty('--my', ((py / window.innerHeight) * 2 - 1).toFixed(3));
      const top = document.elementFromPoint(px, py);
      const overEmptySpace = !top || top === document.body || top === document.documentElement
        || top.hasAttribute('data-bubble-pass');
      let found = null;
      if (overEmptySpace) {
        for (const orb of el.querySelectorAll('[data-orb]')) {
          const r = orb.getBoundingClientRect();
          if (!r.width) continue;
          const dx = px - (r.left + r.width / 2);
          const dy = py - (r.top + r.height / 2);
          if (dx * dx + dy * dy <= (r.width / 2) ** 2) { found = orb.closest('.fb'); break; }
        }
      }
      setHot(found);
    };

    const onMove = (e) => {
      px = e.clientX;
      py = e.clientY;
      if (!raf) raf = requestAnimationFrame(update);
    };
    const onLeave = () => {
      el.style.setProperty('--mx', '0');
      el.style.setProperty('--my', '0');
      setHot(null);
    };

    window.addEventListener('pointermove', onMove, { passive: true });
    document.documentElement.addEventListener('pointerleave', onLeave);
    window.addEventListener('blur', onLeave);
    return () => {
      window.removeEventListener('pointermove', onMove);
      document.documentElement.removeEventListener('pointerleave', onLeave);
      window.removeEventListener('blur', onLeave);
      if (raf) cancelAnimationFrame(raf);
      onLeave();
    };
  }, [reduced, interactive]);

  return (
    <div ref={ref} className={`pscene${className ? ` ${className}` : ''}`} aria-hidden="true">
      {children}
    </div>
  );
}
