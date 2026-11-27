import { useEffect, useRef, useState } from 'react';
import {
  animate, motion, useInView, useMotionTemplate, useMotionValue, useReducedMotion, useSpring, useTransform,
} from 'framer-motion';

/** Shared easing (expo out), same curve as the portfolio site. */
export const EASE_OUT_EXPO = [0.16, 1, 0.3, 1];

/** Fades content up once as it enters the viewport. */
export function Reveal({ children, delay = 0, y = 18, className, as = 'div', ...rest }) {
  const Tag = motion[as];
  return (
    <Tag
      className={className}
      initial={{ opacity: 0, y }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '0px 0px -6% 0px' }}
      transition={{ duration: 0.8, delay, ease: EASE_OUT_EXPO }}
      {...rest}
    >
      {children}
    </Tag>
  );
}

/** Container + item variants for staggered lists (rows, cards). */
export const stagger = {
  hidden: {},
  show: { transition: { staggerChildren: 0.045, delayChildren: 0.05 } },
};
export const rise = {
  hidden: { opacity: 0, y: 14 },
  show: { opacity: 1, y: 0, transition: { duration: 0.6, ease: EASE_OUT_EXPO } },
};

/** Counts up to a number (or the number inside "57%") when it scrolls into view. */
export function CountUp({ value }) {
  const ref = useRef(null);
  const inView = useInView(ref, { once: true });
  const reduced = useReducedMotion();
  const str = String(value);
  const match = str.match(/^(\D*)(\d+)(.*)$/);
  const target = match ? Number(match[2]) : 0;
  const [shown, setShown] = useState(0);

  useEffect(() => {
    if (!match || !inView || reduced || target === 0) return undefined;
    const controls = animate(0, target, { duration: 1.4, ease: EASE_OUT_EXPO, onUpdate: (v) => setShown(Math.round(v)) });
    return () => controls.stop();
  }, [inView, reduced, target]); // eslint-disable-line react-hooks/exhaustive-deps

  // The ref wrapper always renders, so the view observer works even when the
  // value arrives after the first render (e.g. "—" while stats load).
  const n = reduced || target === 0 ? target : shown;
  return (
    <span ref={ref} aria-label={str}>
      <span aria-hidden="true">{match ? <>{match[1]}{n}{match[3]}</> : str}</span>
    </span>
  );
}

const SPRING = { stiffness: 180, damping: 18, mass: 0.6 };

/** Tilts its content in 3D toward the pointer, with a moving glare. Mouse/pen only. */
export function Tilt({ children, className = '', max = 7, glare = true }) {
  const ref = useRef(null);
  const reduced = useReducedMotion();
  const px = useMotionValue(0.5);
  const py = useMotionValue(0.5);
  const hover = useMotionValue(0);
  const rotateX = useSpring(useTransform(py, [0, 1], [max, -max]), SPRING);
  const rotateY = useSpring(useTransform(px, [0, 1], [-max, max]), SPRING);
  const lift = useSpring(hover, SPRING);
  const scale = useTransform(lift, [0, 1], [1, 1.02]);
  const gx = useTransform(px, [0, 1], ['0%', '100%']);
  const gy = useTransform(py, [0, 1], ['0%', '100%']);
  const glareBg = useMotionTemplate`radial-gradient(360px circle at ${gx} ${gy}, rgba(255,255,255,0.45), rgba(255,255,255,0) 60%)`;

  if (reduced) return <div className={className}>{children}</div>;

  const onMove = (e) => {
    if (e.pointerType === 'touch' || !ref.current) return;
    const r = ref.current.getBoundingClientRect();
    px.set((e.clientX - r.left) / r.width);
    py.set((e.clientY - r.top) / r.height);
    hover.set(1);
  };
  const onLeave = () => { px.set(0.5); py.set(0.5); hover.set(0); };

  return (
    <div ref={ref} className={`tilt ${className}`} onPointerMove={onMove} onPointerLeave={onLeave}>
      <motion.div className="tilt__inner" style={{ rotateX, rotateY, scale, transformStyle: 'preserve-3d' }}>
        {children}
        {glare && <motion.div aria-hidden="true" className="tilt__glare" style={{ background: glareBg, opacity: lift }} />}
      </motion.div>
    </div>
  );
}
