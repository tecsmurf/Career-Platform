import { test } from 'node:test';
import assert from 'node:assert/strict';
import { AUTH_BUBBLES, COMPANY_REGISTRY, EMPTY_BUBBLES, HERO_BUBBLES, lookupCompany, monogram } from './companies.js';

const BRIEF = ['Google', 'Microsoft', 'Apple', 'Amazon', 'Meta', 'NVIDIA', 'OpenAI', 'Netflix', 'Adobe', 'IBM',
  'Tesla', 'Salesforce', 'Uber', 'Spotify', 'Oracle', 'LinkedIn'];

test('all sixteen companies are registered; logos only from simple-icons, others text', () => {
  const names = Object.values(COMPANY_REGISTRY).map((c) => c.name);
  assert.deepEqual([...names].sort(), [...BRIEF].sort());
  const withLogo = Object.values(COMPANY_REGISTRY).filter((c) => c.logo);
  assert.deepEqual(withLogo.map((c) => c.name).sort(), ['Apple', 'Google', 'Meta', 'NVIDIA', 'Netflix', 'Spotify', 'Tesla', 'Uber']);
  for (const c of withLogo) assert.match(c.logo.path, /^[Mm][\d.\s-]/);   // real SVG path data
});

test('free-text company names match by whole first word only', () => {
  assert.equal(lookupCompany('Google LLC')?.name, 'Google');
  assert.equal(lookupCompany('Meta Platforms, Inc.')?.name, 'Meta');
  assert.equal(lookupCompany('Open AI')?.name, 'OpenAI');
  assert.equal(lookupCompany('nvidia corporation')?.name, 'NVIDIA');
  assert.equal(lookupCompany("Applebee's"), null);
  assert.equal(lookupCompany('Stripe'), null);
  assert.equal(lookupCompany(''), null);
});

test('monogram fallback', () => {
  assert.equal(monogram('Stripe'), 'S');
  assert.equal(monogram('Goldman Sachs'), 'GS');
  assert.equal(monogram('  '), '?');
});

const count = (list, maxTier) => list.filter((b) => (b.tier ?? 1) <= maxTier).length;

test('density: auth 16 desktop / 10 tablet / 3–7 mobile; hero and empty states stay sparse', () => {
  assert.equal(count(AUTH_BUBBLES, 3), 16);
  assert.equal(count(AUTH_BUBBLES, 2), 10);
  const mobile = count(AUTH_BUBBLES, 1);
  assert.ok(mobile >= 3 && mobile <= 7);
  assert.ok(count(HERO_BUBBLES, 3) <= 8 && count(HERO_BUBBLES, 1) === 3);
  assert.ok(count(EMPTY_BUBBLES, 3) <= 6);
});

test('auth bubbles stay out of the card column on desktop and have tablet/mobile placements', () => {
  for (const b of AUTH_BUBBLES) {
    assert.ok(b.position.x <= 23 || b.position.x >= 77, `${b.name} at x=${b.position.x}% is in the card column`);
    if ((b.tier ?? 1) <= 2) assert.ok(b.tablet, `${b.name} needs a portrait-tablet placement`);
    if ((b.tier ?? 1) === 1) assert.ok(b.mobile, `${b.name} needs a mobile placement`);
  }
});
