import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fitTone, packageStatus, parseList, parseBoardUrl, packageAsText } from './applyUi.js';

test('fitTone bands', () => {
  assert.equal(fitTone(null).tone, 'none');
  assert.equal(fitTone(80).tone, 'strong');
  assert.equal(fitTone(75).tone, 'strong');
  assert.equal(fitTone(60).tone, 'possible');
  assert.equal(fitTone(10).tone, 'stretch');
  assert.equal(fitTone(0).tone, 'stretch');
});

test('packageStatus falls back safely', () => {
  assert.equal(packageStatus('approved').tone, 'approved');
  assert.equal(packageStatus('weird').label, 'weird');
  assert.equal(packageStatus(undefined).label, 'Unknown');
});

test('parseList trims, de-duplicates and caps', () => {
  assert.deepEqual(parseList(' Backend Engineer, , backend engineer,SRE\nRemote '), ['Backend Engineer', 'SRE', 'Remote']);
  assert.equal(parseList(Array.from({ length: 30 }, (_, i) => `r${i}`).join(','), 5).length, 5);
  assert.deepEqual(parseList(null), []);
});

test('parseBoardUrl recognises the three public boards', () => {
  assert.deepEqual(parseBoardUrl('https://boards.greenhouse.io/Acme/jobs/1'), { provider: 'greenhouse', board_token: 'acme' });
  assert.deepEqual(parseBoardUrl('https://job-boards.greenhouse.io/acme'), { provider: 'greenhouse', board_token: 'acme' });
  assert.deepEqual(parseBoardUrl('https://jobs.lever.co/acme-inc'), { provider: 'lever', board_token: 'acme-inc' });
  assert.deepEqual(parseBoardUrl('https://jobs.ashbyhq.com/acme'), { provider: 'ashby', board_token: 'acme' });
  assert.equal(parseBoardUrl('https://evil.example/boards.greenhouse.io/acme'), null);
  assert.equal(parseBoardUrl(''), null);
});

test('packageAsText includes every document and flags missing answers', () => {
  const text = packageAsText({ data: {
    cover_letter: 'Dear team', resume_text: 'Resume',
    answers: [{ question: 'Why?', answer: 'Because' }, { question: 'Salary?', answer: '' }],
    email: { to: 'a@b.co', subject: 'Hi', body: 'Body' },
  } });
  assert.match(text, /COVER LETTER\n\nDear team/);
  assert.match(text, /Salary\?\n\[needs your answer\]/);
  assert.match(text, /To: a@b\.co/);
  assert.match(text, /TAILORED RESUME/);
  assert.equal(packageAsText(null), '');
});
