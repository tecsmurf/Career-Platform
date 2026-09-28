import { Logo, Briefcase, BarChart, Shield } from './icons';

const FEATURES = [
  { icon: Briefcase, text: 'Track every application in one organized place' },
  { icon: BarChart, text: 'See your pipeline and stats at a glance' },
  { icon: Shield, text: 'Private by default — your data stays yours' },
];

export default function AuthShell({ children }) {
  return (
    <div className="auth">
      <aside className="auth__brandpane">
        <div className="brand" style={{ position: 'relative', zIndex: 1 }}>
          <span className="brand__mark"><Logo /></span>
          <span className="brand__name">Career<b>Platform</b></span>
        </div>

        <div className="auth__tagline">
          <h2>Run your job search like a <span>product</span>.</h2>
          <p>A focused workspace to track applications, follow up on time, and know exactly where every opportunity stands.</p>
          <div className="auth__features">
            {FEATURES.map((f, i) => (
              <div className="auth__feature" key={i}>
                <span className="fi"><f.icon /></span>{f.text}
              </div>
            ))}
          </div>
        </div>

        <div className="auth__foot">© {new Date().getFullYear()} Career Platform</div>
      </aside>

      <main className="auth__formpane">
        <div className="auth-card">{children}</div>
      </main>
    </div>
  );
}
