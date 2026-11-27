import { Brand } from './AppShell';
import { Shield, CheckCircle, Mail, Sparkle } from './icons';

const POINTS = [
  { icon: CheckCircle, title: 'One pipeline for every application', text: 'Move roles from Saved to Offer and always know what needs a follow-up.' },
  { icon: Mail, title: 'Inbox updates, with your approval', text: 'Interview invites and rejections are spotted for you. Nothing changes until you say so.' },
  { icon: Sparkle, title: 'Tailored drafts in minutes', text: 'See your fit for a posting and get a resume and cover letter drafted from your own experience.' },
];

/**
 * Sign-in / sign-up layout: a product story on the left (wide screens only),
 * the form on the right. The form stays the focus on every screen size.
 */
export default function AuthShell({ children }) {
  return (
    <div className="auth">
      <aside className="auth__story" aria-hidden="true">
        <Brand />
        <div className="auth__story-body">
          <h2>Your job search, finally organised.</h2>
          <ul className="auth__points">
            {POINTS.map(({ icon: Icon, title, text }) => (
              <li key={title}>
                <span className="auth__point-ic"><Icon /></span>
                <span><b>{title}</b>{text}</span>
              </li>
            ))}
          </ul>
        </div>
        <p className="auth__story-foot"><Shield /> Private by default. Your data stays yours.</p>
      </aside>

      <main className="auth__main">
        <div className="auth__brand"><Brand /></div>
        <div className="auth-card">{children}</div>
        <p className="auth__foot"><Shield /> Private by default. Your data stays yours.</p>
      </main>
    </div>
  );
}
