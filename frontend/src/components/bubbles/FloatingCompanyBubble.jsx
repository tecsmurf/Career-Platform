import CompanyBubble from './CompanyBubble';
import FloatingBubble from './FloatingBubble';

/**
 * One company orb floating in a scene — FloatingBubble (position, depth,
 * motion) around CompanyBubble (glass material + logo). `company` is an entry
 * from lib/companies.js: { name, logo, size, tone, color, position, tablet,
 * mobile, depth, tier, motion }.
 */
export default function FloatingCompanyBubble({ company, seed }) {
  return (
    <FloatingBubble
      seed={seed ?? company.name}
      position={company.position}
      tablet={company.tablet}
      mobile={company.mobile}
      depth={company.depth}
      tier={company.tier ?? 1}
      motion={company.motion}
    >
      <CompanyBubble name={company.name} logo={company.logo ?? null} size={company.size} tone={company.tone} color={company.color} />
    </FloatingBubble>
  );
}
