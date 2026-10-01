import { BUBBLE_SIZES, lookupCompany, monogram } from '../../lib/companies';

/**
 * A translucent sky-blue glass orb with a company logo inside — or, when no
 * licensed logo exists for that company, its name (or initials when `compact`).
 * Always decorative (aria-hidden): the surrounding UI carries the text.
 *
 * `logo`: a simple-icons object, null for "text only", or undefined to look
 * the company up by `name`.
 */
export default function CompanyBubble({
  name, logo, size = 'md', tone = 'sky', color, compact = false, still = false, className = '',
}) {
  const px = typeof size === 'number' ? size : BUBBLE_SIZES[size] || BUBBLE_SIZES.md;
  const entry = logo === undefined ? lookupCompany(name) : null;
  const icon = logo === undefined ? entry?.logo || null : logo;
  const fullName = entry?.name || name || '?';
  const text = compact && fullName.length > 4 ? monogram(fullName) : fullName;
  const fontPx = Math.max(7, Math.min(px * 0.36, (px * 1.05) / Math.max(text.length, 1)));

  return (
    <span
      className={`orb orb--${tone}${still ? ' orb--still' : ''}${className ? ` ${className}` : ''}`}
      style={{ '--s': `${px}px`, ...(color ? { '--glyph': color } : null) }}
      data-orb=""
      aria-hidden="true"
    >
      {icon ? (
        <svg className="orb__logo" viewBox="0 0 24 24" focusable="false"><path d={icon.path} /></svg>
      ) : (
        <span className="orb__text" style={{ fontSize: `${fontPx.toFixed(1)}px` }}>{text}</span>
      )}
    </span>
  );
}
