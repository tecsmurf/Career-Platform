import { lookupCompany, monogram } from '../lib/companies';

// Stable, pleasant hue per company name so the list is easy to scan.
function hue(name) {
  let h = 0;
  for (const ch of String(name || '')) h = (h * 31 + ch.charCodeAt(0)) % 360;
  return h;
}

/** Square company tile: the brand mark when we have a licensed one, else initials. Decorative. */
export default function CompanyLogo({ name, size = 40 }) {
  const entry = lookupCompany(name);
  const h = hue(entry?.name || name);
  return (
    <span className="co-logo" aria-hidden="true"
      style={{ '--s': `${size}px`, '--h': h }}>
      {entry?.logo
        ? <svg viewBox="0 0 24 24" focusable="false"><path d={entry.logo.path} /></svg>
        : <span>{monogram(entry?.name || name)}</span>}
    </span>
  );
}
