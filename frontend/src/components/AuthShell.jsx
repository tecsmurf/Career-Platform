import { BubbleBackground } from './bubbles';
import { AUTH_BUBBLES } from '../lib/companies';
import { Logo, Shield } from './icons';

/**
 * Login / register layout: a centred card floating in a field of 3D company
 * bubbles. The bubbles are decoration only (behind the card, no pointer
 * events, hidden from assistive tech); the form stays the focus.
 */
export default function AuthShell({ children }) {
  return (
    <div className="auth" data-bubble-pass="">
      <BubbleBackground companies={AUTH_BUBBLES} density="dense" />

      <main className="auth__main" data-bubble-pass="">
        <div className="auth__brand">
          <span className="brand__mark"><Logo /></span>
          <span className="brand__name">Career<b>Platform</b></span>
          <span className="auth__tagline">Every application, interview and offer — in one place.</span>
        </div>

        <div className="auth-card">{children}</div>

        <p className="auth__foot"><Shield /> Private by default — your data stays yours.</p>
      </main>
    </div>
  );
}
