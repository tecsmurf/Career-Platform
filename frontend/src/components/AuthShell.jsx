import { motion } from 'framer-motion';
import { Brand } from './AppShell';
import AuthDeck from './AuthDeck';
import SceneMount from './three/SceneMount';
import { EASE_OUT_EXPO } from './motion';
import { Shield, CheckCircle, Mail, Sparkle } from './icons';

const POINTS = [
  { icon: CheckCircle, text: 'Every application in one pipeline' },
  { icon: Mail, text: 'Inbox updates, only with your approval' },
  { icon: Sparkle, text: 'Tailored drafts from your own resume' },
];

/**
 * Sign-in / sign-up layout: a live product story on the left (wide screens
 * only: a 3D pipeline and a deck of application cards), the form on the right.
 */
export default function AuthShell({ children }) {
  return (
    <div className="auth">
      <aside className="auth__story" aria-hidden="true">
        <SceneMount className="auth__scene" />
        <Brand />
        <div className="auth__story-body">
          <motion.h2 initial={{ opacity: 0, y: 30 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 1, ease: EASE_OUT_EXPO }}>
            Your job search,<br /><span className="auth__accent">finally organised.</span>
          </motion.h2>
          <AuthDeck />
          <ul className="auth__points">
            {POINTS.map(({ icon: Icon, text }, i) => (
              <motion.li key={text} initial={{ opacity: 0, y: 14 }} animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.8, delay: 0.5 + i * 0.08, ease: EASE_OUT_EXPO }}>
                <span className="auth__point-ic"><Icon /></span>{text}
              </motion.li>
            ))}
          </ul>
        </div>
        <p className="auth__story-foot"><Shield /> Private by default. Your data stays yours.</p>
      </aside>

      <main className="auth__main">
        <div className="auth__brand"><Brand /></div>
        <motion.div className="auth-card" initial={{ opacity: 0, y: 24 }} animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8, ease: EASE_OUT_EXPO }}>
          {children}
        </motion.div>
        <p className="auth__foot"><Shield /> Private by default. Your data stays yours.</p>
      </main>
    </div>
  );
}
