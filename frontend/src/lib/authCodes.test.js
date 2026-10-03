import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatCountdown, isCompleteCode, looksLikeEmail, normalizeCode, passwordProblem } from './authCodes.js';

test('codes keep digits only and at most six', () => {
  assert.equal(normalizeCode('123 456'), '123456');
  assert.equal(normalizeCode('12-34-56-78'), '123456');
  assert.equal(normalizeCode('ab1c2'), '12');
  assert.equal(normalizeCode(undefined), '');
  assert.equal(normalizeCode(42), '42');
});

test('a complete code is exactly six digits', () => {
  assert.ok(isCompleteCode('012345'));
  assert.ok(!isCompleteCode('12345'));
  assert.ok(!isCompleteCode('1234567'));
  assert.ok(!isCompleteCode('12a456'));
  assert.ok(!isCompleteCode(null));
});

test('new password checks match the server rules', () => {
  assert.match(passwordProblem('abc', 'abc'), /at least 6/);
  assert.match(passwordProblem('x'.repeat(101), 'x'.repeat(101)), /at most 100/);
  assert.match(passwordProblem('secret1', 'secret2'), /match/);
  assert.equal(passwordProblem('secret1', 'secret1'), '');
});

test('countdown formatting', () => {
  assert.equal(formatCountdown(0), '0s');
  assert.equal(formatCountdown(42), '42s');
  assert.equal(formatCountdown(59.2), '1:00');
  assert.equal(formatCountdown(75), '1:15');
  assert.equal(formatCountdown(-3), '0s');
  assert.equal(formatCountdown('soon'), '0s');
});

test('email plausibility', () => {
  assert.ok(looksLikeEmail(' ada@example.com '));
  assert.ok(!looksLikeEmail('ada@example'));
  assert.ok(!looksLikeEmail('ada example.com'));
  assert.ok(!looksLikeEmail(''));
});

test('Retry-After for code requests can be long (hourly caps) but is clamped', async () => {
  const { retryAfterFrom } = await import('./authCodes.js');
  const e = (v) => ({ response: { headers: v === undefined ? {} : { 'retry-after': v } } });
  assert.equal(retryAfterFrom(e('1800')), 1800);
  assert.equal(retryAfterFrom(e('99999')), 3600);
  assert.equal(retryAfterFrom(e(undefined)), 60);
  assert.equal(retryAfterFrom(e('x'), 30), 30);
  assert.equal(retryAfterFrom(undefined), 60);
});
