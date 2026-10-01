import FloatingCompanyBubble from './FloatingCompanyBubble';

const DENSITY = { sparse: 1, medium: 2, dense: 3 };

/**
 * Renders a list of company placements (see lib/companies.js) as floating orbs.
 * `density` caps the tier; CSS then thins tiers further on tablet / mobile.
 */
export default function FloatingBubbleField({ companies = [], density = 'dense', className = '' }) {
  const maxTier = DENSITY[density] ?? 3;
  return (
    <div className={`fb-field${className ? ` ${className}` : ''}`}>
      {companies.filter((co) => (co.tier ?? 1) <= maxTier).map((co, i) => (
        <FloatingCompanyBubble key={`${co.name}-${i}`} seed={`${co.name}-${i}`} company={co} />
      ))}
    </div>
  );
}
