import { test } from 'node:test';
import assert from 'node:assert/strict';
import { MAX_COOLDOWN_SECONDS, RATE_LIMIT_MESSAGE, loginFailureKind, retryAfterSeconds } from './loginErrors.js';

const err = (status, headers = {}) => ({ response: { status, headers } });

test('Retry-After drives the cooldown (whole seconds)', () => {
  assert.equal(retryAfterSeconds(err(429, { 'retry-after': '2' })), 2);
  assert.equal(retryAfterSeconds(err(429, { 'retry-after': '1' })), 1);
  assert.equal(retryAfterSeconds(err(429, { 'retry-after': '3' })), 3);
});

test('missing or malformed Retry-After falls back to 2 s; huge values are capped', () => {
  assert.equal(retryAfterSeconds(err(429)), 2);
  assert.equal(retryAfterSeconds(err(429, { 'retry-after': 'soon' })), 2);
  assert.equal(retryAfterSeconds(err(429, { 'retry-after': '0' })), 2);
  assert.equal(retryAfterSeconds(err(429, { 'retry-after': '-5' })), 2);
  assert.equal(retryAfterSeconds(err(429, { 'retry-after': '86400' })), MAX_COOLDOWN_SECONDS);
  assert.equal(retryAfterSeconds(undefined), 2);
});

test('failure kinds: 429 is never shown as invalid credentials', () => {
  assert.equal(loginFailureKind(err(429)), 'rate_limited');
  assert.equal(loginFailureKind(err(401)), 'invalid');
  assert.equal(loginFailureKind(err(500)), 'error');
  assert.equal(loginFailureKind({ message: 'Network Error' }), 'error');
});

test('rate-limit copy matches the product spec', () => {
  assert.equal(RATE_LIMIT_MESSAGE, 'Too many login attempts. Please wait a moment before trying again.');
});

test('a 403 email_not_verified is its own kind; other 403s are plain errors', () => {
  const unverified = { response: { status: 403, headers: {}, data: { detail: { code: 'email_not_verified', email: 'a@x.com' } } } };
  assert.equal(loginFailureKind(unverified), 'unverified');
  assert.equal(loginFailureKind({ response: { status: 403, headers: {}, data: { detail: 'Forbidden' } } }), 'error');
});
