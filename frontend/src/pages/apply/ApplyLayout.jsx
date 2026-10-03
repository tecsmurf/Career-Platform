import { useEffect, useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import AppNav from '../../components/AppNav';
import { BubbleBackground } from '../../components/bubbles';
import { applyAPI } from '../../api';
import { Briefcase, CheckCircle, Inbox, Search, Shield, Sparkle, Edit, AlertCircle } from '../../components/icons';
import './apply.css';

const TABS = [
  { to: '/apply/postings', label: 'Postings', icon: Search },
  { to: '/apply/applications', label: 'Applications', icon: CheckCircle },
  { to: '/apply/boards', label: 'Job boards', icon: Inbox },
  { to: '/apply/profile', label: 'Profile & resume', icon: Edit },
];

export default function ApplyLayout() {
  const [status, setStatus] = useState(null);

  useEffect(() => {
    applyAPI.status().then((r) => setStatus(r.data)).catch(() => setStatus(null));
  }, []);

  return (
    <>
      <BubbleBackground />
      <AppNav />
      <div className="page">
        <header className="apply-head">
          <div>
            <p className="hero__eyebrow">Apply Assistant</p>
            <h1>Find the right roles. Apply with less effort.</h1>
            <p className="muted">
              Analyse postings, see how well you fit, and get a tailored resume, cover letter and answers drafted
              from your own experience. You review everything — nothing is ever sent for you.
            </p>
          </div>
          <div className="apply-head__chips">
            <span className="trust-chip"><Shield /> Nothing sent automatically</span>
            {status && (
              <span className={`trust-chip ${status.ai?.configured ? '' : 'trust-chip--off'}`}>
                <Sparkle /> {status.ai?.configured ? 'AI drafting on' : 'Standard drafting'}
              </span>
            )}
            <span className="trust-chip"><Briefcase /> Fits only from your resume</span>
          </div>
        </header>

        <nav className="apply-tabs" aria-label="Apply Assistant sections">
          {TABS.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} className="apply-tab"><Icon /> {label}</NavLink>
          ))}
        </nav>

        {status && status.enabled === false ? (
          <div className="alert alert-warn"><AlertCircle /><span>The Apply Assistant is turned off right now.</span></div>
        ) : (
          <Outlet context={{ status }} />
        )}
      </div>
    </>
  );
}
