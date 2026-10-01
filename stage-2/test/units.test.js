import test from 'node:test';
import assert from 'node:assert/strict';
import { parseAmount, formatAmount, formatPlain } from '../public/assets/js/money.js';
import { equalShares } from '../public/assets/js/split.js';
import { equalShares as serverShares } from '../src/ledger.js';

test('N4/N5: decimal parser is exact string arithmetic', () => {
  const ok = (s, u, minor) => assert.deepEqual(parseAmount(s, u), { ok: true, minor }, `${JSON.stringify(s)} @${u}`);
  const no = (s, u) => assert.equal(parseAmount(s, u).ok, false, `${JSON.stringify(s)} @${u}`);
  ok('15.00', 2, 1500); ok('15', 2, 1500); ok('15.5', 2, 1550); ok('0.29', 2, 29); ok('1.1', 2, 110); ok('4.35', 2, 435);
  ok(' 5 ', 2, 500); ok('0', 2, 0); ok('0.00', 2, 0); ok('007', 2, 700); ok('1.500', 3, 1500); ok('1200', 0, 1200); ok('5', 3, 5000);
  ok('90071992547409.91', 2, 9007199254740991);
  for (const s of ['15.005', '.5', '5.', '1e3', '-1', '+1', 'abc', '', ' ', '1,000', '1 000', '1.2.3', '0x10', 'Infinity', '٣']) no(s, 2);
  no('1.0', 0); no('1.', 0); no('90071992547409.92', 2); no(null, 2); no(undefined, 2);
});

test('N2: formatter', () => {
  assert.equal(formatAmount(10000, 2, 'EUR'), '100.00 EUR');
  assert.equal(formatAmount(5, 2, 'EUR'), '0.05 EUR');
  assert.equal(formatAmount(0, 2, 'EUR'), '0.00 EUR');
  assert.equal(formatAmount(1200, 0, 'JPY'), '1200 JPY');
  assert.equal(formatAmount(0, 0, 'JPY'), '0 JPY');
  assert.equal(formatAmount(1500, 3, 'BHD'), '1.500 BHD');
  assert.equal(formatAmount(7, 3, 'BHD'), '0.007 BHD');
  assert.equal(formatAmount(9007199254740991, 2, 'EUR'), '90071992547409.91 EUR');
  assert.equal(formatAmount(1234567, 2, 'EUR'), '12345.67 EUR');
  assert.equal(formatPlain(2000, 2), '20.00');
});

test('parse then format round-trips', () => {
  for (const u of [0, 2, 3]) for (const m of [0, 1, 9, 10, 99, 100, 101, 12345, 999999999]) {
    assert.deepEqual(parseAmount(formatPlain(m, u), u), { ok: true, minor: m });
  }
});

test('Q8: split rule is one module shared by server and browser', () => {
  assert.equal(equalShares, serverShares);
  assert.deepEqual(equalShares(1000, 3), [334, 333, 333]);
  assert.deepEqual(equalShares(1, 3), [1, 0, 0]);
  assert.deepEqual(equalShares(10, 3), [4, 3, 3]);
  assert.deepEqual(equalShares(999, 3), [333, 333, 333]);
  assert.deepEqual(equalShares(5, 5), [1, 1, 1, 1, 1]);
  assert.deepEqual(equalShares(1000, 3).map((x) => formatAmount(x, 2, 'EUR')), ['3.34 EUR', '3.33 EUR', '3.33 EUR']);
});
