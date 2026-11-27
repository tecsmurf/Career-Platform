import { NavLink, useLocation } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { Logo, Logout, Briefcase, Sparkle, Search, CheckCircle, Inbox, Edit } from './icons';

function initials(name) {
  if (!name) return '?';
  return name.trim().split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase()).join('');
}

const APPLY_LINKS = [
  { to: '/apply/postings', label: 'Postings', icon: Search },
  { to: '/apply/applications', label: 'Drafts & approvals', icon: CheckCircle },
  { to: '/apply/boards', label: 'Job boards', icon: Inbox },
  { to: '/apply/profile', label: 'Profile & resume', icon: Edit },
];

export function Brand() {
  return (
    <span className="brand">
      <span className="brand__mark"><Logo /></span>
      <span className="brand__name">Career<b>Platform</b></span>
    </span>
  );
}

/**
 * Signed-in layout. Desktop: a fixed sidebar with every section one click
 * away. Mobile: a compact top bar plus a bottom tab bar for the two areas.
 */
export default function AppShell({ children }) {
  const { user, logout } = useAuth();
  const { pathname } = useLocation();
  const inApply = pathname.startsWith('/apply');

  return (
    <div className="shell">
      <a className="skip-link" href="#main">Skip to content</a>

      <aside className="sidebar" aria-label="Main">
        <div className="sidebar__brand"><Brand /></div>

        <nav className="sidebar__nav" aria-label="Sections">
          <p className="sidebar__label">Track</p>
          <NavLink to="/dashboard" className="side-link"><Briefcase /> <span>My applications</span></NavLink>

          <p className="sidebar__label">Apply Assistant</p>
          {APPLY_LINKS.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} className="side-link"><Icon /> <span>{label}</span></NavLink>
          ))}
        </nav>

        <div className="sidebar__foot">
          <div className="side-user">
            <span className="avatar" aria-hidden="true">{initials(user?.full_name)}</span>
            <span className="side-user__who">
              <b>{user?.full_name}</b>
              <span>{user?.email}</span>
            </span>
          </div>
          <button className="side-link side-link--btn" onClick={logout}><Logout /> <span>Sign out</span></button>
        </div>
      </aside>

      <header className="topbar">
        <Brand />
        <div className="topbar__right">
          <span className="avatar" aria-hidden="true">{initials(user?.full_name)}</span>
          <button className="icon-btn" onClick={logout} aria-label="Sign out"><Logout /></button>
        </div>
      </header>

      <main id="main" className="shell__main" tabIndex={-1}>{children}</main>

      <nav className="tabbar" aria-label="Sections">
        <NavLink to="/dashboard" className="tabbar__link"><Briefcase /><span>Tracker</span></NavLink>
        <NavLink to="/apply/postings" className={`tabbar__link ${inApply ? 'active' : ''}`}><Sparkle /><span>Apply Assistant</span></NavLink>
      </nav>
    </div>
  );
}
