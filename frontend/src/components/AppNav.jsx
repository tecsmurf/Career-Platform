import { NavLink } from 'react-router-dom';
import { useAuth } from '../hooks/useAuth';
import { Logo, Logout, Briefcase, Sparkle } from './icons';

function initials(name) {
  if (!name) return '?';
  return name.trim().split(/\s+/).slice(0, 2).map((w) => w[0]?.toUpperCase()).join('');
}

/** Top bar shared by every signed-in page: brand, section links, account. */
export default function AppNav() {
  const { user, logout } = useAuth();
  return (
    <nav className="nav">
      <div className="nav__left">
        <div className="brand">
          <span className="brand__mark"><Logo /></span>
          <span className="brand__name">Career<b>Platform</b></span>
        </div>
        <div className="nav__links" role="navigation" aria-label="Sections">
          <NavLink to="/dashboard" className="nav__link" aria-label="Tracker"><Briefcase /> <span>Tracker</span></NavLink>
          <NavLink to="/apply" className="nav__link" aria-label="Apply Assistant"><Sparkle /> <span>Apply Assistant</span></NavLink>
        </div>
      </div>
      <div className="nav__right">
        <div className="nav__user">
          <span className="avatar" aria-hidden="true">{initials(user?.full_name)}</span>
          <span className="who"><b>{user?.full_name}</b>{user?.email}</span>
        </div>
        <button className="btn btn-ghost" onClick={logout} aria-label="Logout"><Logout /> <span className="nav__logout-label">Logout</span></button>
      </div>
    </nav>
  );
}
