/**
 * Company registry + bubble scenes (data-driven: components never hardcode bubbles).
 *
 * Logos come from the `simple-icons` package (CC0-1.0, https://simpleicons.org),
 * imported individually so the build only ships the eight paths used here.
 * Simple Icons has removed several brands at their owners' request (Microsoft,
 * Amazon, OpenAI, Adobe, IBM, Salesforce, Oracle, LinkedIn are not in it), so
 * those render as a plain-text label instead — never a scraped logo file.
 * All names and logos are trademarks of their respective owners; they appear
 * as decoration only and imply no affiliation or endorsement.
 */
import {
  siApple, siGoogle, siMeta, siNetflix, siNvidia, siSpotify, siTesla, siUber,
} from 'simple-icons';

// name → { logo: simple-icon | null, label: fallback text when no logo }
export const COMPANY_REGISTRY = {
  google: { name: 'Google', logo: siGoogle },
  apple: { name: 'Apple', logo: siApple },
  meta: { name: 'Meta', logo: siMeta },
  nvidia: { name: 'NVIDIA', logo: siNvidia },
  netflix: { name: 'Netflix', logo: siNetflix },
  tesla: { name: 'Tesla', logo: siTesla },
  uber: { name: 'Uber', logo: siUber },
  spotify: { name: 'Spotify', logo: siSpotify },
  microsoft: { name: 'Microsoft', logo: null },
  amazon: { name: 'Amazon', logo: null },
  openai: { name: 'OpenAI', logo: null },
  adobe: { name: 'Adobe', logo: null },
  ibm: { name: 'IBM', logo: null },
  salesforce: { name: 'Salesforce', logo: null },
  oracle: { name: 'Oracle', logo: null },
  linkedin: { name: 'LinkedIn', logo: null },
};

/**
 * Best-effort match of a free-text company name ("Google LLC", "Meta Platforms")
 * to the registry, by whole first word only — so "Applebee's" is not Apple.
 */
export function lookupCompany(name) {
  if (!name) return null;
  const words = String(name).toLowerCase().normalize('NFKD').replace(/[^a-z0-9\s]/g, ' ').trim().split(/\s+/);
  return COMPANY_REGISTRY[words.join('')] || COMPANY_REGISTRY[words[0]] || null;
}

export function monogram(name) {
  const words = String(name || '?').trim().split(/\s+/).filter(Boolean);
  if (!words.length) return '?';
  if (words.length === 1) return words[0][0].toUpperCase();
  return (words[0][0] + words[1][0]).toUpperCase();
}

// Orb diameters in px (before responsive scaling).
export const BUBBLE_SIZES = { xs: 52, sm: 68, md: 88, lg: 108, xl: 132 };

const c = (key, placement) => ({ ...COMPANY_REGISTRY[key], ...placement });

/*
 * Scene placements. position/mobile are % of the scene box; tier controls
 * density: 1 = always (mobile 3–7), 2 = tablet+, 3 = desktop only.
 * depth: near | mid | far.  size: xs | sm | md | lg | xl.  tone: sky | ice | deep.
 */

// Login / register: a full-viewport field around a centred card. Desktop 16,
// tablet 10, mobile 3–5. Desktop placements stay in the outer quarters
// (x ≤ 23% / ≥ 77%), clear of the card down to 1025px wide even after
// perspective, float and parallax; portrait tablets and phones use bands
// above and below the card instead.
export const AUTH_BUBBLES = [
  c('google', { size: 'lg', depth: 'near', position: { x: 14, y: 22 }, tablet: { x: 12, y: 8 }, mobile: { x: 9, y: 5 }, tier: 1 }),
  c('microsoft', { size: 'md', depth: 'mid', position: { x: 21, y: 8 }, tablet: { x: 37, y: 5 }, mobile: { x: 66, y: 3 }, tier: 1, tone: 'ice' }),
  c('apple', { size: 'lg', depth: 'near', position: { x: 86, y: 19 }, tablet: { x: 87, y: 9 }, mobile: { x: 91, y: 6 }, tier: 1, tone: 'ice' }),
  c('nvidia', { size: 'xl', depth: 'near', position: { x: 17, y: 70 }, tablet: { x: 15, y: 91 }, mobile: { x: 8, y: 95 }, tier: 1, tone: 'deep' }),
  c('tesla', { size: 'lg', depth: 'near', position: { x: 83, y: 69 }, tablet: { x: 85, y: 90 }, mobile: { x: 93, y: 93 }, tier: 1 }),
  c('meta', { size: 'md', depth: 'mid', position: { x: 78, y: 9 }, tablet: { x: 62, y: 8 }, tier: 2 }),
  c('amazon', { size: 'md', depth: 'mid', position: { x: 6, y: 46 }, tablet: { x: 7, y: 48 }, tier: 2, tone: 'deep' }),
  c('openai', { size: 'md', depth: 'mid', position: { x: 94, y: 45 }, tablet: { x: 93, y: 50 }, tier: 2, tone: 'ice' }),
  c('netflix', { size: 'sm', depth: 'mid', position: { x: 7, y: 89 }, tablet: { x: 40, y: 94 }, tier: 2 }),
  c('linkedin', { size: 'sm', depth: 'mid', position: { x: 94, y: 87 }, tablet: { x: 63, y: 93 }, tier: 2, tone: 'deep' }),
  c('adobe', { size: 'xs', depth: 'far', position: { x: 23, y: 42 }, tier: 3 }),
  c('spotify', { size: 'sm', depth: 'far', position: { x: 77, y: 41 }, tier: 3, tone: 'ice' }),
  c('ibm', { size: 'sm', depth: 'far', position: { x: 22, y: 91 }, tier: 3, tone: 'ice' }),
  c('uber', { size: 'sm', depth: 'far', position: { x: 78, y: 91 }, tier: 3 }),
  c('salesforce', { size: 'xs', depth: 'far', position: { x: 5, y: 31 }, tier: 3, tone: 'ice' }),
  c('oracle', { size: 'xs', depth: 'far', position: { x: 97, y: 66 }, tier: 3 }),
];

// Dashboard hero: a small cluster beside the greeting (its own box, so it can
// never sit under the text). Desktop 7, tablet 5, mobile 3.
export const HERO_BUBBLES = [
  c('google', { size: 'md', depth: 'near', position: { x: 30, y: 30 }, tier: 1 }),
  c('nvidia', { size: 'lg', depth: 'near', position: { x: 62, y: 58 }, tier: 1, tone: 'deep' }),
  c('apple', { size: 'sm', depth: 'mid', position: { x: 84, y: 22 }, tier: 1, tone: 'ice' }),
  c('microsoft', { size: 'sm', depth: 'mid', position: { x: 12, y: 74 }, tier: 2, tone: 'ice' }),
  c('meta', { size: 'xs', depth: 'far', position: { x: 52, y: 12 }, tier: 2 }),
  c('spotify', { size: 'xs', depth: 'far', position: { x: 92, y: 80 }, tier: 3 }),
  c('openai', { size: 'xs', depth: 'far', position: { x: 36, y: 90 }, tier: 3, tone: 'ice' }),
];

// Empty state: bubbles flank the message on wide screens; on mobile the scene
// collapses to a band above it.
export const EMPTY_BUBBLES = [
  c('google', { size: 'md', depth: 'near', position: { x: 16, y: 34 }, mobile: { x: 22, y: 50 }, tier: 1 }),
  c('microsoft', { size: 'md', depth: 'near', position: { x: 84, y: 64 }, mobile: { x: 76, y: 48 }, tier: 1, tone: 'ice' }),
  c('netflix', { size: 'sm', depth: 'mid', position: { x: 82, y: 22 }, mobile: { x: 50, y: 36 }, tier: 1 }),
  c('tesla', { size: 'xs', depth: 'far', position: { x: 8, y: 76 }, tier: 2, tone: 'deep' }),
  c('amazon', { size: 'xs', depth: 'far', position: { x: 26, y: 82 }, tier: 3 }),
];
