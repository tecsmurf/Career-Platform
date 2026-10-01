import { test } from 'node:test';
import assert from 'node:assert/strict';
import { DEPTH, bubbleMotion } from './bubbleMotion.js';
import { AUTH_BUBBLES } from './companies.js';

test('motion is deterministic per bubble', () => {
  assert.deepEqual(bubbleMotion('Google-0', 'near'), bubbleMotion('Google-0', 'near'));
});

test('no two bubbles share timing (no artificial lock-step)', () => {
  const all = AUTH_BUBBLES.map((co, i) => bubbleMotion(`${co.name}-${i}`, co.depth));
  assert.equal(new Set(all.map((m) => m.duration.toFixed(2))).size, all.length);
  assert.equal(new Set(all.map((m) => m.delay.toFixed(2))).size, all.length);
  assert.equal(new Set(all.map((m) => m.ampY.toFixed(1))).size, all.length);
});

test('slow, subtle ranges — and far bubbles move less and slower', () => {
  for (let i = 0; i < 200; i += 1) {
    const near = bubbleMotion(`n${i}`, 'near');
    const far = bubbleMotion(`f${i}`, 'far');
    assert.ok(near.duration >= 12 && near.duration <= 20, `near duration ${near.duration}`);
    assert.ok(far.duration >= 12 * 1.6 && far.duration <= 20 * 1.6);
    assert.ok(near.ampY >= 16 && near.ampY <= 30);
    assert.ok(far.ampY >= 8 && far.ampY <= 15);
    assert.ok(Math.abs(near.ampX) <= near.ampY * 0.6);
    assert.ok(Math.abs(near.rotation) <= 6);
    assert.ok(near.delay <= 0 && near.delay > -near.duration);
  }
});

test('depth layers: far is behind, fainter, blurrier and parallaxes less', () => {
  assert.ok(DEPTH.far.z < DEPTH.mid.z && DEPTH.mid.z < DEPTH.near.z);
  assert.ok(DEPTH.far.opacity < DEPTH.mid.opacity && DEPTH.mid.opacity <= DEPTH.near.opacity);
  assert.ok(DEPTH.far.blur > DEPTH.near.blur);
  assert.ok(DEPTH.far.parallax < DEPTH.mid.parallax && DEPTH.mid.parallax < DEPTH.near.parallax);
});

test('explicit motion overrides win', () => {
  const m = bubbleMotion('x', 'mid', { duration: 14, amplitude: 20, rotation: 3 });
  assert.equal(m.duration, 14);
  assert.equal(m.ampY, 20);
  assert.equal(m.rotation, 3);
});
