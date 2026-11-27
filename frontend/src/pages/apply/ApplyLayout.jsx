import { useEffect, useState } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import AppShell from '../../components/AppShell';
import { applyAPI } from '../../api';
import { Briefcase, CheckCircle, Inbox, Search, Shield, Sparkle, Edit, AlertCircle } from '../../components/icons';
import './apply.css';

const TABS = [
  { to: '/apply/postings', label: 'Postings', icon: Search },
  { to: '/apply/applications', label: 'Drafts & approvals', icon: CheckCircle },
  { to: '/apply/boards', label: 'Job boards', icon: Inbox },
  { to: '/apply/profile', label: 'Profile & resume', icon: Edit },
];

export default function ApplyLayout() {
  const [status, setStatus] = useState(null);
  // Detail pages (a single posting or draft) get the full width; the intro only shows on section pages.
  const isDetail = /^\/apply\/(postings|applications)\/[^/]+/.test(useLocation().pathname);

  useEffect(() => {
    applyAPI.status().then((r) => setStatus(r.data)).catch(() => setStatus(null));
  }, []);

  return (
    <AppShell>
      <div className="page">
        {!isDetail && (<>
        <header className="page-head apply-head">
          <div>
            <p className="eyebrow">Apply Assistant</p>
            <h1>Find the right roles. Apply with less effort.</h1>
            <p className="page-head__sub">
              See how well you fit each posting, then get a tailored resume, cover letter and answers drafted from your own
              experience. You review everything, and nothing is ever sent for you.
            </p>
          </div>
          <div className="apply-head__chips">
            <span className="trust-chip"><Shield /> Nothing sent automatically</span>
            {status && (
              <span className={`trust-chip ${status.ai?.configured ? '' : 'trust-chip--off'}`}>
                <Sparkle /> {status.ai?.configured ? 'AI drafting on' : 'Standard drafting'}
              </span>
            )}
            <span className="trust-chip"><Briefcase /> Fit based only on your resume</span>
          </div>
        </header>

        <nav className="tabs tabs--nav apply-tabs" aria-label="Apply Assistant sections">
          {TABS.map(({ to, label, icon: Icon }) => (
            <NavLink key={to} to={to} className="tab apply-tab"><Icon /> {label}</NavLink>
          ))}
        </nav>
        </>)}

        {status && status.enabled === false ? (
          <div className="alert alert-warn"><AlertCircle /><span>The Apply Assistant is turned off right now.</span></div>
        ) : (
          <Outlet context={{ status }} />
        )}
      </div>
    </AppShell>
  );
}
