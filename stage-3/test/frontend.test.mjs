// Unit tests for the browser modules that hold logic: money, retry identity, latest-wins, model.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatAmount, parseDecimal, splitShares, parseHandles, toTypedDecimal } from '../public/js/money.js';
import { RetryIdentity } from '../public/js/retry.js';
import { latestOnly } from '../public/js/latest.js';
import { normalizeMe } from '../public/js/api.js';

test('formatAmount: exact places, one space, currency, no sign for balances', () => {
  assert.equal(formatAmount(10000, 2, 'EUR'), '100.00 EUR');
  assert.equal(formatAmount(5, 2, 'EUR'), '0.05 EUR');
  assert.equal(formatAmount(0, 2, 'EUR'), '0.00 EUR');
  assert.equal(formatAmount(1200, 0, 'JPY'), '1200 JPY');
  assert.equal(formatAmount(0, 0, 'JPY'), '0 JPY');
  assert.equal(formatAmount(1000, 3, 'BHD'), '1.000 BHD');
  assert.equal(formatAmount(7, 3, 'BHD'), '0.007 BHD');
  assert.equal(formatAmount(2 ** 53, 2, 'EUR'), '90071992547409.92 EUR');
  assert.equal(formatAmount(1234567, 2, 'EUR'), '12345.67 EUR');
  assert.equal(toTypedDecimal(2000, 2), '20.00');
  assert.equal(toTypedDecimal(2000, 0), '2000');
});

test('parseDecimal: typed decimals become exact minor units, never rounded', () => {
  const ok = (t, mu, minor) => assert.deepEqual(parseDecimal(t, mu), { ok: true, minor }, `${t} / ${mu}`);
  ok('15', 2, 1500); ok('15.00', 2, 1500); ok('15.5', 2, 1550); ok(' 15.5 ', 2, 1550); ok('0.05', 2, 5);
  ok('007', 2, 700); ok('15', 0, 15); ok('1.234', 3, 1234); ok('1.2', 3, 1200); ok('0', 2, 0);
  ok('90071992547409.92', 2, 2 ** 53);
  for (const [t, mu] of [['15.005', 2], ['', 2], ['  ', 2], ['abc', 2], ['-5', 2], ['+5', 2], ['1e3', 2], ['1,5', 2], ['15.', 2], ['.5', 2], ['15.5', 0], ['15.0', 0], ['1.2345', 3], ['1 000', 2], ['９', 2], ['90071992547409.93', 2], ['0x10', 2]]) {
    assert.equal(parseDecimal(t, mu).ok, false, `${JSON.stringify(t)} / ${mu}`);
  }
});

test('splitShares follows the equal-split rule', () => {
  assert.deepEqual(splitShares(1000, 3), [334, 333, 333]);
  assert.deepEqual(splitShares(1, 3), [1, 0, 0]);
  assert.deepEqual(splitShares(10, 3), [4, 3, 3]);
  assert.deepEqual(splitShares(999, 3), [333, 333, 333]);
  assert.deepEqual(splitShares(5, 5), [1, 1, 1, 1, 1]);
  assert.deepEqual(splitShares(7, 1), [7]);
  for (let amount = 0; amount < 60; amount++) {
    for (let n = 1; n < 9; n++) {
      const shares = splitShares(amount, n);
      assert.equal(shares.reduce((a, b) => a + b, 0), amount);
      assert.ok(Math.max(...shares) - Math.min(...shares) <= 1);
      assert.deepEqual([...shares].sort((a, b) => b - a), shares);
    }
  }
});

test('parseHandles keeps order and ignores spaces and empty entries', () => {
  assert.deepEqual(parseHandles('cy, bob ,ada'), ['cy', 'bob', 'ada']);
  assert.deepEqual(parseHandles(' ,, '), []);
});

test('RetryIdentity: same content keeps its key, changed content gets a new one', () => {
  let n = 0;
  const r = new RetryIdentity(() => `k${++n}`);
  assert.equal(r.keyFor('a'), 'k1');
  assert.equal(r.keyFor('a'), 'k1');
  assert.equal(r.keyFor('b'), 'k2');
  assert.equal(r.keyFor('b'), 'k2');
  assert.equal(r.keyFor('a'), 'k3');
});

test('latestOnly: a delayed earlier read never overwrites a later one', async () => {
  const run = latestOnly();
  const shown = [];
  const later = (ms, value) => () => new Promise((r) => setTimeout(() => r(value), ms));
  const first = run(later(60, 'old'), (v) => shown.push(v));
  const second = run(later(5, 'new'), (v) => shown.push(v));
  assert.deepEqual(await Promise.all([first, second]), [false, true]);
  assert.deepEqual(shown, ['new']);
  // in-order responses are all shown
  const a = run(later(5, 'a'), (v) => shown.push(v));
  await a;
  await run(later(5, 'b'), (v) => shown.push(v));
  assert.deepEqual(shown, ['new', 'a', 'b']);
});

test('normalizeMe fills fields missing from a previous-stage service', () => {
  const old = normalizeMe({ user_id: 'u', balance: 700 });
  assert.deepEqual([old.total, old.available, old.held], [700, 700, 0]);
  const now = normalizeMe({ balance: 700, total: 700, available: 500, held: 200 });
  assert.deepEqual([now.total, now.available, now.held], [700, 500, 200]);
});
