'use strict';

const { test } = require('node:test');
const assert = require('node:assert/strict');
const I = require('../src/instant');

test('parse accepts only real RFC 3339 date-times with an offset', () => {
  for (const ok of ['2026-09-24T13:20:00+00:00', '2026-09-24T13:20:00Z', '2026-09-24t13:20:00z', '2026-09-24T13:20:00.5-07:30', '2024-02-29T00:00:00Z', '2026-09-24T23:59:59.123456789012Z']) {
    assert.notEqual(I.parse(ok), null, ok);
  }
  for (const bad of ['', '2026-09-24', '2026-09-24T13:20:00', '2026-09-24 13:20:00Z', '2026-02-30T00:00:00Z', '2025-02-29T00:00:00Z',
    '2026-13-01T00:00:00Z', '2026-00-10T00:00:00Z', '2026-09-24T24:00:00Z', '2026-09-24T12:60:00Z', '2026-09-24T12:00:60Z',
    '2026-09-24T12:00:00.Z', '2026-09-24T12:00:00+24:00', '2026-09-24T12:00:00+01:60', '2026-09-24T12:00:00+0100', '1700000000', ' 2026-09-24T13:20:00Z', null, 5]) {
    assert.equal(I.parse(bad), null, String(bad));
  }
});

test('spellings of one instant are equal; precision finer than a millisecond is kept', () => {
  const a = I.parse('2026-09-24T13:20:00+00:00');
  for (const same of ['2026-09-24T15:20:00+02:00', '2026-09-24T13:20:00Z', '2026-09-24T13:20:00.000000Z', '2026-09-24T05:50:00-07:30', '2026-09-24T13:20:00.0000000000000Z']) {
    assert.equal(I.compare(a, I.parse(same)), 0, same);
  }
  const later = I.parse('2026-09-24T13:20:00.000001Z');
  const earlier = I.parse('2026-09-24T13:19:59.999999Z');
  assert.ok(I.compare(later, a) > 0 && I.compare(a, later) < 0 && I.compare(earlier, a) < 0);
  assert.ok(I.compare(I.parse('2026-09-24T13:20:00.0005Z'), I.parse('2026-09-24T13:20:00.0004999Z')) > 0);
  assert.ok(I.compare(I.parse('2026-09-24T13:20:00.001Z'), I.parse('2026-09-24T13:20:00.0009999Z')) > 0);
  assert.equal(I.compare(I.parse('2026-09-24T13:20:00.1Z'), I.parse('2026-09-24T13:20:00.100Z')), 0);
});

test('rawParam keeps a literal plus and decodes percent escapes', () => {
  assert.equal(I.rawParam('?as_of=2026-09-24T13:20:00+00:00&x=1', 'as_of'), '2026-09-24T13:20:00+00:00');
  assert.equal(I.rawParam('?as_of=2026-09-24T13:20:00%2B00:00', 'as_of'), '2026-09-24T13:20:00+00:00');
  assert.equal(I.rawParam('?a=&b=2', 'a'), '');
  assert.equal(I.rawParam('?a=1', 'b'), undefined);
  assert.equal(I.rawParam('?a=%E0%A4%A', 'a'), '%E0%A4%A');
  assert.equal(I.parse(I.rawParam('?a=2026-09-24T13:20:00%20%2B00:00', 'a')), null);
});
