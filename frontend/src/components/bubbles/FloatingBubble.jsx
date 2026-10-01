import { bubbleMotion } from '../../lib/bubbleMotion';

// Coordinates are % of the scene box; a string is used as-is (e.g. 'calc(50% - 300px)').
const pct = (v) => (v === undefined ? undefined : typeof v === 'string' ? v : `${v}%`);

/**
 * Positions one decorative object in a ParallaxScene and gives it slow,
 * organic float + depth + parallax. Duration, amplitude, delay and rotation
 * differ per bubble (seeded) unless `motion` overrides them.
 */
export default function FloatingBubble({ position, tablet, mobile, depth = 'mid', tier = 1, seed = 'bubble', motion, children }) {
  const m = bubbleMotion(seed, depth, motion);

  const style = {
    '--x': pct(position.x), '--y': pct(position.y),
    '--xt': pct(tablet?.x), '--yt': pct(tablet?.y),
    '--xs': pct(mobile?.x), '--ys': pct(mobile?.y),
    '--z': `${m.z}px`, '--o': m.opacity, '--blur': `${m.blur}px`, '--par': m.parallax,
    '--dur': `${m.duration.toFixed(2)}s`, '--delay': `${m.delay.toFixed(2)}s`,
    '--ax': `${m.ampX.toFixed(1)}px`, '--ay': `${m.ampY.toFixed(1)}px`, '--rot': `${m.rotation.toFixed(1)}deg`,
  };

  return (
    <div
      className="fb"
      data-depth={depth}
      data-tier={tier}
      data-tablet={tablet ? '' : undefined}
      data-mobile={mobile ? '' : undefined}
      data-mobile-low={mobile && mobile.y > 50 ? '' : undefined}
      style={style}
    >
      <div className="fb__parallax">
        <div className="fb__float">{children}</div>
      </div>
    </div>
  );
}
