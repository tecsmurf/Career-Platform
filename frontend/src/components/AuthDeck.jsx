import { useEffect, useState } from 'react';
import { motion, useMotionValue, useReducedMotion, useSpring, useTransform } from 'framer-motion';
import { EASE_OUT_EXPO } from './motion';
import { MapPin, Calendar } from './icons';

// Illustrative cards only (decorative, hidden from assistive tech).
const CARDS = [
  { role: 'Senior Frontend Engineer', co: 'Northwind', mono: 'N', hue: 222, where: 'Remote', when: 'Onsite Dec 3', status: 'Interview', color: '#ffb21e' },
  { role: 'Design Engineer', co: 'Lumen Labs', mono: 'L', hue: 150, where: 'New York', when: 'Offer in hand', status: 'Offer', color: '#3ddc84' },
  { role: 'ML Engineer', co: 'Quanta', mono: 'Q', hue: 262, where: 'Bengaluru', when: 'Applied Nov 25', status: 'Applied', color: '#6d9bff' },
  { role: 'Full-stack Engineer', co: 'Orbit', mono: 'O', hue: 20, where: 'Stockholm', when: 'Apply this week', status: 'Saved', color: '#9aa6bb' },
];

const STAGE_PROGRESS = { Saved: 25, Applied: 50, Interview: 75, Offer: 100 };

// Pose of a card by its depth in the stack (0 = top).
const POSE = [
  { rotate: 0, x: 0, y: 0 },
  { rotate: -6, x: -26, y: 16 },
  { rotate: 5, x: 24, y: 28 },
  { rotate: -9, x: -40, y: 40 },
];

/**
 * A fanned 3D deck of application cards that leans toward the pointer and
 * deals the top card to the back every few seconds.
 */
export default function AuthDeck() {
  const reduced = useReducedMotion();
  const [order, setOrder] = useState(() => CARDS.map((_, i) => i));
  const mx = useMotionValue(0);
  const my = useMotionValue(0);
  const rotY = useSpring(useTransform(mx, [-1, 1], [-14, 14]), { stiffness: 90, damping: 16 });
  const rotX = useSpring(useTransform(my, [-1, 1], [10, -10]), { stiffness: 90, damping: 16 });

  useEffect(() => {
    if (reduced) return undefined;
    const t = setInterval(() => setOrder((o) => [...o.slice(1), o[0]]), 3400);
    return () => clearInterval(t);
  }, [reduced]);

  useEffect(() => {
    if (reduced) return undefined;
    const onMove = (e) => {
      mx.set((e.clientX / window.innerWidth) * 2 - 1);
      my.set((e.clientY / window.innerHeight) * 2 - 1);
    };
    window.addEventListener('pointermove', onMove);
    return () => window.removeEventListener('pointermove', onMove);
  }, [reduced, mx, my]);

  return (
    <div className="deck" aria-hidden="true">
      <motion.div className="deck__stack" style={{ rotateX: rotX, rotateY: rotY, transformStyle: 'preserve-3d' }}>
        {CARDS.map((c, i) => {
          const depth = order.indexOf(i);
          const pose = POSE[depth];
          return (
            <motion.div
              key={c.co}
              className="deck__card"
              style={{ zIndex: CARDS.length - depth }}
              initial={{ opacity: 0, y: 120, scale: 0.9 }}
              animate={{ opacity: 1, ...pose, scale: 1 - depth * 0.04, z: -depth * 30 }}
              transition={{ duration: 0.9, ease: EASE_OUT_EXPO }}
            >
              <div className="deck__top">
                <span className="co-logo" style={{ '--s': '40px', '--h': c.hue }}><span>{c.mono}</span></span>
                <span className="deck__status" style={{ '--badge-color': c.color }}>{c.status}</span>
              </div>
              <div className="deck__role">{c.role}</div>
              <div className="deck__co">{c.co}</div>
              <div className="deck__meta">
                <span><MapPin /> {c.where}</span>
                <span><Calendar /> {c.when}</span>
              </div>
              <div className="deck__bar"><i style={{ width: `${STAGE_PROGRESS[c.status]}%`, background: c.color }} /></div>
            </motion.div>
          );
        })}
      </motion.div>
    </div>
  );
}
