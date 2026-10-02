'use strict';

const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const h = require('./helpers');
const { call } = h;

before(h.start);
after(h.stop);

const D = (hhmm, day = '20') => `2026-09-${day}T${hhmm}:00+00:00`;
const k = () => Math.random().toString();
const err = (r, status, code) => {
  assert.equal(r.status, status, r.text);
  assert.equal(r.body.error.code, code);
};
const user = (id, handle, balance) => ({ id: `u_${id}`, email: `${id}@example.com`, password: 'correct horse', display_name: handle, handle, balance });
const pay = (id, from, to, amount, created_at, extra = {}) => ({ id, from_user_id: `u_${from}`, to_user_id: `u_${to}`, amount, note: id, visibility: 'public', created_at, ...extra });

/** ada 10000/ bob 2500 / cy 5500 after: p1 bob->cy 2000 @10:00, p2 cy->ada 1500 @11:00, p3 ada->cy 5000 @12:00. */
const HISTORY = () => ({
  currency: 'EUR', minor_units: 2,
  users: [user('ada', 'ada', 10000), user('bob', 'bob', 2500), user('cy', 'cy', 5500)],
  payments: [pay('p1', 'bob', 'cy', 2000, D('10:00')), pay('p2', 'cy', 'ada', 1500, D('11:00')), pay('p3', 'ada', 'cy', 5000, D('12:00'))],
});
async function setup(fixture = HISTORY()) {
  await h.reset(fixture);
  return h.tokens();
}
const get = async (path, token) => (await call('GET', path, { token }));
const me = async (token, q = '') => (await get(`/me${q}`, token)).body;
const correct = (token, id, body, key = k()) => call('POST', `/payments/${id}/corrections`, { token, key, body });

test('as_of: opening before the first payment, inclusive at an instant, current after the last', async () => {
  const t = await setup();
  assert.equal((await me(t.ada, '?as_of=2026-09-20T09:59:59%2B00:00')).balance, 13500);
  assert.equal((await me(t.ada, '?as_of=2026-09-20T11:00:00%2B00:00')).balance, 15000);
  assert.equal((await me(t.ada, '?as_of=2026-09-20T11:59:59%2B00:00')).balance, 15000);
  assert.equal((await me(t.ada, '?as_of=2026-09-20T12:00:00%2B00:00')).balance, 10000);
  assert.equal((await me(t.ada, '?as_of=2099-01-01T00:00:00Z')).balance, 10000);
  assert.equal((await me(t.cy, '?as_of=2026-09-20T09:00:00Z')).balance, 0);
  assert.equal((await me(t.cy, '?as_of=2026-09-20T10:00:00Z')).balance, 2000);
  assert.equal((await me(t.cy, '?as_of=2026-09-20T11:00:00Z')).balance, 500);
  assert.equal((await me(t.cy, '?as_of=2026-09-20T12:00:00Z')).balance, 5500);
  // echo exactly as given; absent means absent; a raw plus is an offset
  assert.equal((await me(t.ada, '?as_of=2026-09-20T13:00:00+00:00')).as_of, '2026-09-20T13:00:00+00:00');
  assert.equal((await me(t.ada, '?as_of=2026-09-20T15:00:00%2B02:00')).as_of, '2026-09-20T15:00:00+02:00');
  const plain = await me(t.ada);
  assert.ok(!('as_of' in plain) && !('known_at' in plain));
  assert.deepEqual([plain.balance, plain.total, plain.available, plain.held], [10000, 10000, 10000, 0]);
  const hist = await me(t.ada, '?as_of=2026-09-20T11:30:00Z');
  assert.deepEqual([hist.balance, hist.total, hist.available, hist.held], [15000, 15000, 15000, 0]);
});

test('instants: every invalid spelling is 422, on every endpoint that takes one', async () => {
  const t = await setup();
  const bad = ['', '2026-09-20', '2026-09-20T10:00:00', '2026-02-30T00:00:00Z', '2026-09-20T24:00:00Z', 'yesterday', '1700000000', '2026-09-20T10:00:00.Z'];
  for (const v of bad) {
    for (const q of ['as_of', 'known_at']) err(await get(`/me?${q}=${encodeURIComponent(v)}`, t.ada), 422, 'validation_failed');
    for (const q of ['from', 'to', 'known_at']) err(await get(`/statement?${q}=${encodeURIComponent(v)}`, t.ada), 422, 'validation_failed');
  }
  err(await get('/me?as_of', t.ada), 422, 'validation_failed');
  assert.equal((await get('/me?junk=1&as_of=2026-09-20T10:00:00Z', t.ada)).status, 200);
  err(await call('GET', '/me?as_of=2026-09-20T10:00:00Z'), 401, 'unauthenticated');
  err(await call('GET', '/statement'), 401, 'unauthenticated');
});

test('microsecond instants are compared exactly, not rounded to milliseconds', async () => {
  const t = await setup({ ...HISTORY(), payments: [pay('p1', 'bob', 'cy', 2000, '2026-09-20T10:00:00.000500Z')] });
  const bal = async (v) => (await me(t.cy, `?as_of=${encodeURIComponent(v)}`)).balance;
  const opening = 5500 - 2000;
  assert.equal(await bal('2026-09-20T10:00:00.000499Z'), opening);
  assert.equal(await bal('2026-09-20T10:00:00.000500Z'), opening + 2000);
  assert.equal(await bal('2026-09-20T12:00:00.0005+02:00'), opening + 2000);
  assert.equal(await bal('2026-09-20T09:59:59.999999Z'), opening);
  const st = (await get('/statement?from=2026-09-20T10:00:00.000500Z', t.cy)).body;
  assert.equal(st.entries.length, 1);
  assert.equal((await get('/statement?from=2026-09-20T10:00:00.000501Z', t.cy)).body.entries.length, 0);
  assert.equal((await get('/statement?to=2026-09-20T10:00:00.000500Z', t.cy)).body.entries.length, 0);
  assert.equal(st.entries[0].payment.created_at, '2026-09-20T10:00:00.000500Z');
});

test('statement: arithmetic, order, window, parties only, opening of the wallet', async () => {
  const t = await setup();
  let s = (await get('/statement', t.cy)).body;
  assert.equal(s.opening_balance, 0);
  assert.deepEqual(s.entries.map((e) => [e.payment.payment_id, e.delta, e.balance_after, e.revision]), [['p1', 2000, 2000, 1], ['p2', -1500, 500, 1], ['p3', 5000, 5500, 1]]);
  assert.equal(s.closing_balance, 5500);
  assert.equal(s.has_more, false);
  assert.match(s.snapshot, /^[0-9a-f]{20,}$/);
  assert.equal(s.opening_balance + s.entries.reduce((a, e) => a + e.delta, 0), s.closing_balance);
  assert.equal(s.entries[0].effective_at, D('10:00'));
  assert.equal(s.entries[0].recorded_at, D('10:00'));
  // half-open window
  s = (await get('/statement?from=2026-09-20T11:00:00Z&to=2026-09-20T12:00:00Z', t.cy)).body;
  assert.deepEqual([s.opening_balance, s.entries.map((e) => e.payment.payment_id), s.closing_balance], [2000, ['p2'], 500]);
  s = (await get('/statement?from=2026-09-20T11:00:00Z&to=2026-09-20T11:00:00Z', t.cy)).body;
  assert.deepEqual([s.opening_balance, s.entries.length, s.closing_balance], [2000, 0, 2000]);
  err(await get('/statement?from=2026-09-20T12:00:00Z&to=2026-09-20T11:00:00Z', t.cy), 422, 'validation_failed');
  // only the caller's own payments, even though p1 is public and bob/cy/ada are all involved
  s = (await get('/statement', t.bob)).body;
  assert.deepEqual(s.entries.map((e) => e.payment.payment_id), ['p1']);
  assert.deepEqual([s.opening_balance, s.closing_balance], [4500, 2500]);
  // unknown query parameters are ignored; limit and offset as elsewhere
  assert.equal((await get('/statement?junk=1', t.cy)).status, 200);
  for (const q of ['limit=0', 'limit=201', 'offset=-1', 'limit=1e2']) err(await get(`/statement?${q}`, t.cy), 422, 'validation_failed');
  // a private payment of two other people never shows
  const t2 = await setup({ ...HISTORY(), payments: [pay('p1', 'bob', 'cy', 2000, D('10:00'), { visibility: 'private' })] });
  assert.equal((await get('/statement', t2.ada)).body.entries.length, 0);
});

test('statement ordering: effective instant, then payment id by code point', async () => {
  const t = await setup({
    ...HISTORY(),
    payments: [pay('p_9', 'bob', 'cy', 100, D('10:00')), pay('p_10', 'bob', 'cy', 200, D('10:00')), pay('p_1', 'bob', 'cy', 300, D('10:00')), pay('p_0', 'bob', 'cy', 50, D('09:00'))],
    users: [user('ada', 'ada', 10000), user('bob', 'bob', 2500), user('cy', 'cy', 650)],
  });
  const ids = (await get('/statement', t.cy)).body.entries.map((e) => e.payment.payment_id);
  assert.deepEqual(ids, ['p_0', 'p_1', 'p_10', 'p_9']);
});

test('pagination keeps balances, opening and closing; has_more at the edges', async () => {
  const payments = Array.from({ length: 7 }, (_, i) => pay(`q${i}`, 'ada', 'bob', 10 + i, D(`0${i + 1}:00`)));
  const t = await setup({ ...HISTORY(), payments, users: [user('ada', 'ada', 10000), user('bob', 'bob', 2500), user('cy', 'cy', 0)] });
  const full = (await get('/statement', t.ada)).body;
  assert.equal(full.entries.length, 7);
  const pages = [];
  for (const [limit, offset] of [[3, 0], [3, 3], [3, 6], [3, 9], [7, 0], [1, 6], [200, 0]]) {
    const r = (await get(`/statement?limit=${limit}&offset=${offset}`, t.ada)).body;
    pages.push([limit, offset, r.entries.length, r.has_more]);
    assert.equal(r.opening_balance, full.opening_balance);
    assert.equal(r.closing_balance, full.closing_balance);
    for (const [i, e] of r.entries.entries()) {
      assert.deepEqual(e.payment, full.entries[offset + i].payment);
      assert.equal(e.balance_after, full.entries[offset + i].balance_after);
    }
  }
  assert.deepEqual(pages, [[3, 0, 3, true], [3, 3, 3, true], [3, 6, 1, false], [3, 9, 0, false], [7, 0, 7, false], [1, 6, 1, false], [200, 0, 7, false]]);
});

test('corrections: shape, money, history, feed untouched', async () => {
  const t = await setup();
  const before = (await get('/activity', t.ada)).text;
  const r = await correct(t.ada, 'p3', { expected_revision: 1, amount: 4000, effective_at: D('12:30'), reason: 'overpaid' }, 'c1');
  assert.equal(r.status, 201);
  assert.deepEqual(Object.keys(r.body), ['payment_id', 'revision', 'amount', 'effective_at', 'recorded_at', 'reason']);
  assert.deepEqual([r.body.payment_id, r.body.revision, r.body.amount, r.body.effective_at, r.body.reason], ['p3', 2, 4000, D('12:30'), 'overpaid']);
  assert.match(r.body.recorded_at, /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}\+00:00$/);
  // decrease of 1000: the receiver (cy) is debited, the sender (ada) credited
  assert.equal((await me(t.ada)).balance, 11000);
  assert.equal((await me(t.cy)).balance, 4500);
  assert.equal((await me(t.ada, '?as_of=2026-09-20T12:10:00Z')).balance, 15000);
  assert.equal((await me(t.ada, '?as_of=2026-09-20T12:30:00Z')).balance, 11000);
  // the feed and the original idempotent receipts keep the original payment
  assert.equal((await get('/activity', t.ada)).text, before);
  const hist = (await get('/payments/p3/revisions', t.cy)).body.revisions;
  assert.deepEqual(hist.map((x) => [x.revision, x.amount, x.reason]), [[1, 5000, ''], [2, 4000, 'overpaid']]);
  assert.deepEqual(Object.keys(hist[0]), ['payment_id', 'revision', 'amount', 'effective_at', 'recorded_at', 'reason']);
  // statement uses the selected revision once, by effective time
  const s = (await get('/statement', t.ada)).body;
  assert.deepEqual(s.entries.map((e) => [e.payment.payment_id, e.revision, e.payment.amount, e.delta, e.balance_after]), [['p2', 1, 1500, 1500, 15000], ['p3', 2, 4000, -4000, 11000]]);
  // replay returns the original revision after newer ones; other body is key reuse
  const second = await correct(t.ada, 'p3', { expected_revision: 2, amount: 4500, effective_at: D('12:30'), reason: 'again' });
  assert.equal(second.status, 201);
  const replay = await correct(t.ada, 'p3', { expected_revision: 1, amount: 4000, effective_at: D('12:30'), reason: 'overpaid' }, 'c1');
  assert.equal(replay.status, 200);
  assert.deepEqual(replay.body, r.body);
  err(await correct(t.ada, 'p3', { expected_revision: 1, amount: 4001, effective_at: D('12:30'), reason: 'overpaid' }, 'c1'), 409, 'idempotency_key_reuse');
  // total conservation
  const total = (await Promise.all([t.ada, t.bob, t.cy].map((x) => me(x)))).reduce((a, b) => a + b.total, 0);
  assert.equal(total, 18000);
  // zero reverses the payment, still an entry
  const zero = await correct(t.ada, 'p3', { expected_revision: 3, amount: 0, effective_at: D('12:30'), reason: 'reversed' });
  assert.equal(zero.status, 201);
  const z = (await get('/statement', t.ada)).body.entries.find((e) => e.payment.payment_id === 'p3');
  assert.deepEqual([z.delta, z.revision, z.payment.amount], [0, 4, 0]);
});

test('corrections: validation, errors and their precedence', async () => {
  const t = await setup();
  const good = { expected_revision: 1, amount: 4000, effective_at: D('12:30'), reason: 'r' };
  const c = (tok, id, body, key) => correct(tok, id, body, key);
  err(await call('POST', '/payments/p3/corrections', { token: t.ada, body: good }), 400, 'missing_idempotency_key');
  err(await call('POST', '/payments/p3/corrections', { body: good, key: 'x' }), 401, 'unauthenticated');
  err(await c(t.ada, 'p3', '[]'), 400, 'malformed_request');
  for (const field of ['expected_revision', 'amount', 'effective_at', 'reason']) {
    const body = { ...good };
    delete body[field];
    err(await c(t.ada, 'p3', body), 422, 'validation_failed');
  }
  const invalid = [
    { expected_revision: 0 }, { expected_revision: -1 }, { expected_revision: 1.5 }, { expected_revision: '1' }, { expected_revision: null },
    { amount: -1 }, { amount: 1000000001 }, { amount: 1.5 }, { amount: '5' }, { amount: null }, { amount: true },
    { reason: '' }, { reason: 5 }, { reason: 'x'.repeat(201) }, { reason: null },
    { effective_at: 'tomorrow' }, { effective_at: '2026-09-20T12:00:00' }, { effective_at: '2099-01-01T00:00:00Z' }, { effective_at: 5 },
  ];
  for (const bad of invalid) err(await c(t.ada, 'p3', { ...good, ...bad }), 422, 'validation_failed');
  assert.equal((await c(t.ada, 'p3', { ...good, expected_revision: 1.0, amount: 4e3, reason: 'x'.repeat(200) })).status, 201);
  assert.equal((await c(t.ada, 'p3', { expected_revision: 2, amount: 4000, effective_at: new Date().toISOString().replace('Z', '+00:00'), reason: '😀'.repeat(200) })).status, 201);
  // validation precedes 404 and 403; then 404 -> 403 -> stale
  err(await c(t.ada, 'nope', { ...good, amount: -1 }), 422, 'validation_failed');
  err(await c(t.ada, 'nope', good), 404, 'not_found');
  err(await c(t.cy, 'p3', { ...good, expected_revision: 99 }), 403, 'forbidden');
  err(await c(t.bob, 'p3', good), 403, 'forbidden');
  err(await c(t.ada, 'p3', { ...good, expected_revision: 1 }), 409, 'stale_revision');
  err(await c(t.ada, 'p3', { ...good, expected_revision: 9 }), 409, 'stale_revision');
  // failed requests leave the key free and change nothing
  const hist = (await get('/payments/p3/revisions', t.ada)).body.revisions.length;
  err(await c(t.ada, 'p3', { ...good, expected_revision: 9 }, 'free'), 409, 'stale_revision');
  assert.equal((await c(t.ada, 'p3', { ...good, expected_revision: hist, amount: 3000 }, 'free')).status, 201);
  // percent-encoded ids are the same resource
  assert.equal((await get('/payments/p%33/revisions', t.ada)).status, 200);
  assert.equal((await get('/payments/%E0%A4%A/revisions', t.ada)).status, 404);
});

test('revisions: only the two parties; third party and operator get 404', async () => {
  const t = await setup({ ...HISTORY(), settlement_operator_ids: ['u_bob'] });
  assert.equal((await get('/payments/p3/revisions', t.ada)).status, 200);
  assert.equal((await get('/payments/p3/revisions', t.cy)).status, 200);
  err(await get('/payments/p3/revisions', t.bob), 404, 'not_found');
  err(await get('/payments/zzz/revisions', t.bob), 404, 'not_found');
  err(await call('GET', '/payments/p3/revisions'), 401, 'unauthenticated');
});

test('linked payments are immutable: settlement members and captures', async () => {
  const t = await setup({ ...HISTORY(), settlement_operator_ids: ['u_bob'] });
  const s = await call('POST', '/settlements', { token: t.bob, key: 's', body: { transfers: [{ from_handle: 'ada', to_handle: 'cy', amount: 100 }] } });
  const member = s.body.payments[0];
  const body = { expected_revision: 1, amount: 1, effective_at: member.created_at, reason: 'x' };
  err(await correct(t.ada, member.payment_id, body), 422, 'linked_payment_immutable');
  err(await correct(t.cy, member.payment_id, body), 403, 'forbidden');
  const rev = (await get(`/payments/${member.payment_id}/revisions`, t.ada)).body.revisions[0];
  assert.deepEqual([rev.effective_at, rev.recorded_at], [s.body.committed_at, s.body.committed_at]);
  const a = (await call('POST', '/authorizations', { token: t.ada, key: 'a', body: { to_handle: 'cy', amount: 300 } })).body;
  const cap = (await call('POST', `/authorizations/${a.authorization_id}/capture`, { token: t.cy, key: 'c', body: { amount: 200 } })).body;
  err(await correct(t.ada, cap.payment_id, { ...body, effective_at: cap.created_at }), 422, 'linked_payment_immutable');
  // stale and linked: linked wins over stale
  err(await correct(t.ada, member.payment_id, { ...body, expected_revision: 7 }), 422, 'linked_payment_immutable');
});

test('insufficient_funds is judged on the current available balance and comes before historical_overdraft', async () => {
  const t = await setup();
  // p3 ada->cy 5000: raising it by more than ada's 10000 fails now
  err(await correct(t.ada, 'p3', { expected_revision: 1, amount: 16000, effective_at: D('12:00'), reason: 'r' }), 409, 'insufficient_funds');
  // lowering p3 below what cy holds is fine, lowering p1 enough to overdraw cy at 11:00 but not now is historical
  assert.equal((await correct(t.bob, 'p1', { expected_revision: 1, amount: 2200, effective_at: D('10:00'), reason: 'up' })).status, 201);
  err(await correct(t.bob, 'p1', { expected_revision: 2, amount: 1000, effective_at: D('10:00'), reason: 'down' }), 409, 'historical_overdraft');
  // same amount, effective moved after cy spent it
  err(await correct(t.bob, 'p1', { expected_revision: 2, amount: 2200, effective_at: D('11:30'), reason: 'late' }), 409, 'historical_overdraft');
  // nothing changed by the refusals
  assert.deepEqual((await get('/payments/p1/revisions', t.bob)).body.revisions.length, 2);
  assert.equal((await me(t.cy)).balance, 5700);
  // held money is not available for a current debit
  await call('POST', '/authorizations', { token: t.ada, key: 'h', body: { to_handle: 'bob', amount: 9000 } });
  err(await correct(t.ada, 'p3', { expected_revision: 1, amount: 6500, effective_at: D('12:00'), reason: 'r' }), 409, 'insufficient_funds');
});

test('historical overdraft already present is not made worse, only refused when lowered', async () => {
  // cy: p1 bob->cy 100 effective 12:00 but p2 cy->ada 100 already left at 11:00 (inconsistent seed)
  const t = await setup({
    ...HISTORY(),
    users: [user('ada', 'ada', 10000), user('bob', 'bob', 2500), user('cy', 'cy', 0)],
    payments: [pay('p2', 'cy', 'ada', 100, D('11:00')), pay('p1', 'bob', 'cy', 100, D('12:00'))],
  });
  const rev = (id, n, over) => correct(over.token, id, { expected_revision: n, amount: over.amount, effective_at: over.at, reason: 'r' });
  // reason/effective changes that keep the -100 at 11:00 are accepted
  assert.equal((await rev('p1', 1, { token: t.bob, amount: 100, at: D('12:30') })).status, 201);
  // lowering p2 helps the already negative boundary: accepted
  assert.equal((await rev('p2', 1, { token: t.cy, amount: 0, at: D('11:00') })).status, 201);
});

test('historical available with holds: moving income after a hold was placed is refused', async () => {
  const hold = { id: 'a_1', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 9000, note: 'h', visibility: 'public', status: 'open', expires_at: '2099-01-01T00:00:00+00:00', created_at: D('11:00') };
  const t = await setup({
    currency: 'EUR', minor_units: 2,
    users: [user('ada', 'ada', 10000), user('bob', 'bob', 2500), user('cy', 'cy', 0)],
    payments: [pay('p_r', 'bob', 'ada', 5000, D('10:00'))],
    authorizations: [hold],
  });
  // ada: opening 5000, +5000 at 10:00 = 10000, hold 9000 from 11:00 -> available 1000
  const v = await me(t.ada, '?as_of=2026-09-20T11:30:00Z');
  assert.deepEqual([v.total, v.held, v.available], [10000, 9000, 1000]);
  const early = await me(t.ada, '?as_of=2026-09-20T10:30:00Z');
  assert.deepEqual([early.total, early.held, early.available], [10000, 0, 10000]);
  const before = await me(t.ada, '?as_of=2026-09-20T09:00:00Z');
  assert.deepEqual([before.total, before.held, before.available], [5000, 0, 5000]);
  err(await correct(t.bob, 'p_r', { expected_revision: 1, amount: 5000, effective_at: D('11:30'), reason: 'late' }), 409, 'historical_overdraft');
  assert.equal((await correct(t.bob, 'p_r', { expected_revision: 1, amount: 5000, effective_at: D('10:30'), reason: 'ok' })).status, 201);
});

test('known_at: revisions recorded later are ignored, payments first recorded later contribute nothing', async () => {
  const t = await setup();
  const t0 = new Date().toISOString();
  await new Promise((r) => setTimeout(r, 15));
  const c = await correct(t.ada, 'p3', { expected_revision: 1, amount: 4000, effective_at: D('12:00'), reason: 'r' });
  const recorded = c.body.recorded_at;
  const p4 = (await call('POST', '/payments', { token: t.ada, key: 'p4', body: { to_handle: 'bob', amount: 100 } })).body;
  const q = (v, extra = '') => `?known_at=${encodeURIComponent(v)}${extra}`;
  assert.equal((await me(t.ada, q(t0))).balance, 10000); // before the correction and before p4
  assert.equal((await me(t.ada, q(recorded))).balance, 11000); // correction known, p4 not yet
  assert.equal((await me(t.ada)).balance, 10900);
  assert.equal((await me(t.ada, q('2000-01-01T00:00:00Z'))).balance, 13500); // nothing known: opening only
  assert.equal((await me(t.ada, q('2099-01-01T00:00:00Z'))).balance, 10900);
  const echoed = await me(t.ada, q(recorded, '&as_of=2026-09-20T12:30:00%2B00:00'));
  assert.deepEqual([echoed.known_at, echoed.as_of, echoed.balance], [recorded, '2026-09-20T12:30:00+00:00', 11000]);
  // statements by knowledge
  const s = (await get(`/statement${q(t0)}`, t.ada)).body;
  assert.deepEqual([s.known_at, s.entries.map((e) => [e.payment.payment_id, e.revision, e.payment.amount])], [t0, [['p2', 1, 1500], ['p3', 1, 5000]]]);
  assert.equal(s.closing_balance, 10000);
  const s2 = (await get('/statement', t.ada)).body;
  assert.ok(!('known_at' in s2));
  assert.deepEqual(s2.entries.map((e) => [e.payment.payment_id, e.revision]), [['p2', 1], ['p3', 2], [p4.payment_id, 1]]);
  // payments first recorded after K contribute nothing at any as_of
  assert.equal((await me(t.bob, q(t0, '&as_of=2099-01-01T00:00:00Z'))).balance, 2500);
});

test('statement snapshots freeze the read; token rules', async () => {
  const t = await setup();
  const first = (await get('/statement?limit=1', t.ada)).body;
  assert.equal(first.entries.length, 1);
  const token = first.snapshot;
  await call('POST', '/payments', { token: t.ada, key: 'n1', body: { to_handle: 'bob', amount: 10 } });
  await correct(t.ada, 'p3', { expected_revision: 1, amount: 4000, effective_at: D('12:00'), reason: 'r' });
  const page2 = (await get(`/statement?snapshot=${token}&limit=1&offset=1`, t.ada)).body;
  assert.equal(page2.snapshot, token);
  const rest = (await get(`/statement?snapshot=${token}&limit=50&offset=0`, t.ada)).body;
  assert.deepEqual(rest.entries.map((e) => [e.payment.payment_id, e.payment.amount, e.balance_after]), [['p2', 1500, 15000], ['p3', 5000, 10000]]);
  assert.deepEqual([rest.opening_balance, rest.closing_balance, rest.has_more], [13500, 10000, false]);
  assert.equal(page2.entries[0].payment.payment_id, 'p3');
  assert.equal(page2.has_more, false);
  assert.equal((await get(`/statement?snapshot=${token}&offset=5`, t.ada)).body.has_more, false);
  assert.deepEqual((await get(`/statement?snapshot=${token}&offset=5`, t.ada)).body.entries, []);
  // a fresh read sees the changes
  const fresh = (await get('/statement', t.ada)).body;
  assert.notEqual(fresh.snapshot, token);
  assert.equal(fresh.closing_balance, (await me(t.ada)).balance);
  assert.equal(fresh.entries.length, 3);
  // known_at echoes through the snapshot
  const k1 = (await get('/statement?known_at=2099-01-01T00:00:00Z&limit=1', t.ada)).body;
  assert.equal((await get(`/statement?snapshot=${k1.snapshot}&offset=1`, t.ada)).body.known_at, '2099-01-01T00:00:00Z');
  // rules
  for (const extra of ['from=2026-09-20T10:00:00Z', 'to=2026-09-21T10:00:00Z', 'known_at=2026-09-21T10:00:00Z', 'from=']) {
    err(await get(`/statement?snapshot=${token}&${extra}`, t.ada), 422, 'validation_failed');
  }
  err(await get(`/statement?snapshot=${token}&limit=0`, t.ada), 422, 'validation_failed');
  err(await get(`/statement?snapshot=${token}`, t.bob), 404, 'not_found');
  err(await get('/statement?snapshot=nonsense', t.ada), 404, 'not_found');
  err(await get('/statement?snapshot=', t.ada), 404, 'not_found');
  assert.equal((await get(`/statement?snapshot=${token}&junk=1`, t.ada)).status, 200);
  await h.reset(HISTORY());
  const t2 = await h.tokens();
  err(await get(`/statement?snapshot=${token}`, t2.ada), 404, 'not_found');
});

test('a correction moves a payment into or out of a statement window for new reads only', async () => {
  const t = await setup();
  const win = '?from=2026-09-20T11:30:00Z&to=2026-09-20T12:30:00Z';
  const old = (await get(`/statement${win}`, t.ada)).body;
  assert.deepEqual(old.entries.map((e) => e.payment.payment_id), ['p3']);
  await correct(t.ada, 'p3', { expected_revision: 1, amount: 5000, effective_at: D('13:00'), reason: 'later' });
  await correct(t.cy, 'p2', { expected_revision: 1, amount: 1500, effective_at: D('12:00'), reason: 'later' });
  const now = (await get(`/statement${win}`, t.ada)).body;
  assert.deepEqual(now.entries.map((e) => [e.payment.payment_id, e.revision]), [['p2', 2]]);
  assert.deepEqual((await get(`/statement?snapshot=${old.snapshot}`, t.ada)).body.entries.map((e) => e.payment.payment_id), ['p3']);
});

test('concurrent corrections with one expected revision: exactly one succeeds', async () => {
  const t = await setup();
  const rs = await Promise.all(Array.from({ length: 50 }, (_, i) => correct(t.ada, 'p3', { expected_revision: 1, amount: 100 + i, effective_at: D('12:00'), reason: `c${i}` }, `k${i}`)));
  assert.equal(rs.filter((r) => r.status === 201).length, 1);
  assert.equal(rs.filter((r) => r.status === 409 && r.body.error.code === 'stale_revision').length, 49);
  const win = rs.find((r) => r.status === 201).body;
  assert.equal((await me(t.ada)).balance, 15000 - win.amount);
  const total = (await Promise.all([t.ada, t.bob, t.cy].map((x) => me(x)))).reduce((a, b) => a + b.total, 0);
  assert.equal(total, 18000);
  const same = await Promise.all(Array.from({ length: 50 }, () => correct(t.ada, 'p3', { expected_revision: 2, amount: 7, effective_at: D('12:00'), reason: 'same' }, 'same-key')));
  assert.equal(same.filter((r) => r.status === 201).length, 1);
  assert.equal(same.filter((r) => r.status === 200).length, 49);
});

test('concurrent payments, corrections and statement reads stay consistent', async () => {
  const t = await setup();
  const ops = [];
  for (let i = 0; i < 25; i++) ops.push(call('POST', '/payments', { token: t.ada, key: `pp${i}`, body: { to_handle: 'bob', amount: 10 } }));
  for (let i = 0; i < 10; i++) ops.push(get('/statement?limit=5', t.ada));
  ops.push(correct(t.ada, 'p3', { expected_revision: 1, amount: 4000, effective_at: D('12:00'), reason: 'r' }));
  const rs = await Promise.all(ops);
  assert.ok(rs.every((r) => r.status < 500));
  for (const r of rs.filter((x) => x.body && x.body.snapshot)) {
    assert.equal(r.body.opening_balance, 13500);
  }
  const s = (await get('/statement', t.ada)).body;
  assert.equal(s.opening_balance + s.entries.reduce((a, e) => a + e.delta, 0), s.closing_balance);
  assert.equal(s.closing_balance, (await me(t.ada)).balance);
});

test('seeded created_at: returned as given; future or invalid is 422; omitted means the reset instant', async () => {
  const fx = { ...HISTORY(), payments: [pay('p1', 'bob', 'cy', 2000, '2026-09-20T12:00:00.123456+02:00'), { ...pay('p2', 'cy', 'ada', 1500, D('11:00')), created_at: undefined }] };
  delete fx.payments[1].created_at;
  await h.reset(fx);
  const t = await h.tokens();
  const feed = (await get('/activity', t.cy)).body.payments;
  const p1 = feed.find((p) => p.payment_id === 'p1');
  assert.equal(p1.created_at, '2026-09-20T12:00:00.123456+02:00');
  const p2 = feed.find((p) => p.payment_id === 'p2');
  assert.ok(Date.parse(p2.created_at) <= Date.now() && Date.parse(p2.created_at) > Date.now() - 60000);
  const later = (await call('POST', '/payments', { token: t.ada, key: 'later', body: { to_handle: 'bob', amount: 1 } })).body;
  assert.ok(Date.parse(later.created_at) > Date.parse(p2.created_at), 'strictly after the reset instant');
  assert.equal(feed[0].payment_id, 'p2');
  // balances untouched by the seeded payments
  assert.equal((await me(t.cy)).balance, 5500);
  for (const bad of ['2099-01-01T00:00:00Z', 'yesterday', '2026-09-20T12:00:00', 5, null]) {
    err(await call('POST', '/_test/reset', { body: { ...HISTORY(), payments: [pay('p1', 'bob', 'cy', 1, bad)] } }), 422, 'validation_failed');
  }
  assert.equal((await me(t.cy)).balance, 5500);
});

test('historical views sum to the seeded total at every instant and knowledge point', async () => {
  const t = await setup();
  await correct(t.ada, 'p3', { expected_revision: 1, amount: 4000, effective_at: D('12:15'), reason: 'r' });
  await call('POST', '/payments', { token: t.ada, key: 'x', body: { to_handle: 'cy', amount: 700 } });
  const hold = (await call('POST', '/authorizations', { token: t.cy, key: 'h', body: { to_handle: 'bob', amount: 1000 } })).body;
  await call('POST', `/authorizations/${hold.authorization_id}/capture`, { token: t.bob, key: 'cap', body: { amount: 300, final: false } });
  const instants = ['2026-09-19T00:00:00Z', D('10:00'), D('11:00'), D('12:00'), D('12:15'), new Date().toISOString(), '2099-01-01T00:00:00Z'];
  for (const as_of of instants) {
    for (const known_at of [undefined, '2000-01-01T00:00:00Z', new Date().toISOString(), '2099-01-01T00:00:00Z']) {
      const q = `?as_of=${encodeURIComponent(as_of)}${known_at ? `&known_at=${encodeURIComponent(known_at)}` : ''}`;
      const views = await Promise.all([t.ada, t.bob, t.cy].map((x) => me(x, q)));
      assert.equal(views.reduce((a, v) => a + v.total, 0), 18000, q);
      for (const v of views) {
        assert.equal(v.balance, v.total);
        assert.equal(v.available, v.total - v.held);
        assert.ok(v.available >= 0 && v.total >= 0 && v.held >= 0, q);
      }
    }
  }
});

const iso = (ms) => new Date(ms).toISOString().replace('Z', '+00:00');
const q = (v) => encodeURIComponent(v);
const sleep = (n) => new Promise((r) => setTimeout(r, n));
const money = (v) => [v.total, v.held, v.available];

test('historical holds follow creation, partial capture and void at their event times', async () => {
  const t = await setup();
  const hold = (await call('POST', '/authorizations', { token: t.ada, key: 'h1', body: { to_handle: 'bob', amount: 1000 } })).body;
  assert.equal(hold.closed_at, null);
  const created = Date.parse(hold.created_at);
  await sleep(8);
  const cap = (await call('POST', `/authorizations/${hold.authorization_id}/capture`, { token: t.bob, key: 'c1', body: { amount: 300, final: false } })).body;
  const captured = Date.parse(cap.created_at);
  await sleep(8);
  const voided = (await call('POST', `/authorizations/${hold.authorization_id}/void`, { token: t.ada })).body;
  const closed = Date.parse(voided.closed_at);
  assert.ok(created < captured && captured < closed);
  assert.match(voided.closed_at, /^\d{4}-\d\d-\d\dT.*\+00:00$/);
  const view = async (asOf, known) => money(await me(t.ada, `?as_of=${q(iso(asOf))}${known === undefined ? '' : `&known_at=${q(iso(known))}`}`));
  assert.deepEqual(await view(created - 1), [10000, 0, 10000]);
  assert.deepEqual(await view(created), [10000, 1000, 9000]);
  assert.deepEqual(await view(captured - 1), [10000, 1000, 9000]);
  assert.deepEqual(await view(captured), [9700, 700, 9000]);
  assert.deepEqual(await view(closed - 1), [9700, 700, 9000]);
  assert.deepEqual(await view(closed), [9700, 0, 9700]);
  assert.deepEqual(await view(closed + 100000), [9700, 0, 9700]);
  // knowledge: before the capture was recorded the capture is unknown, the hold still stands
  assert.deepEqual(await view(closed, captured - 1), [10000, 1000, 9000]);
  assert.deepEqual(await view(closed, created - 1), [10000, 0, 10000]);
  assert.deepEqual(await view(closed, closed - 1), [9700, 700, 9000]);
  assert.deepEqual(await view(closed, closed), [9700, 0, 9700]);
  // closed_at is carried by every authorization response
  const listed = (await get('/authorizations', t.bob)).body.authorizations[0];
  assert.equal(listed.closed_at, voided.closed_at);
  // statements hold money movements only: the capture appears once, the hold and its void never
  const s = (await get('/statement', t.ada)).body;
  assert.equal(s.entries.filter((e) => e.payment.authorization_id === hold.authorization_id).length, 1);
  assert.equal(s.entries.length, 3);
});

test('historical holds: expiry takes effect at expires_at; future views release an open hold at its deadline', async () => {
  const t = await setup({ ...HISTORY(), authorization_ttl_seconds: 1 });
  const hold = (await call('POST', '/authorizations', { token: t.ada, key: 'h1', body: { to_handle: 'bob', amount: 4000 } })).body;
  const created = Date.parse(hold.created_at);
  const expires = Date.parse(hold.expires_at);
  const view = async (asOf, known) => money(await me(t.ada, `?as_of=${q(iso(asOf))}${known === undefined ? '' : `&known_at=${q(iso(known))}`}`));
  assert.deepEqual(await view(expires - 1), [10000, 4000, 6000]);
  assert.deepEqual(await view(expires), [10000, 0, 10000]);
  // while open the deadline is known: a view past it releases the hold even when K is just after creation
  assert.deepEqual(await view(expires + 5000, created), [10000, 0, 10000]);
  assert.deepEqual(await view(expires - 1, created - 1), [10000, 0, 10000]);
  await sleep(1200);
  const closed = (await get('/authorizations', t.ada)).body.authorizations[0];
  assert.deepEqual([closed.status, closed.closed_at], ['expired', hold.expires_at]);
  assert.deepEqual(await view(expires - 1), [10000, 4000, 6000]);
  assert.deepEqual(await view(expires), [10000, 0, 10000]);
  // an open hold in a future view
  const t2 = await setup();
  const open = (await call('POST', '/authorizations', { token: t2.ada, key: 'h', body: { to_handle: 'bob', amount: 2500 } })).body;
  const exp = Date.parse(open.expires_at);
  const v2 = async (asOf) => money(await me(t2.ada, `?as_of=${q(iso(asOf))}`));
  assert.deepEqual(await v2(exp - 60000), [10000, 2500, 7500]);
  assert.deepEqual(await v2(exp), [10000, 0, 10000]);
  assert.deepEqual(await v2(exp + 3600000), [10000, 0, 10000]);
});

test('seeded holds: open ones start at reset or their created_at; closed ones leave no history', async () => {
  const base = { id: 'a_1', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 2000, note: '', visibility: 'public', expires_at: '2099-01-01T00:00:00+00:00' };
  const fx = (list) => ({ ...HISTORY(), authorizations: list });
  let t = await setup(fx([{ ...base, status: 'open' }, { ...base, id: 'a_2', status: 'captured', amount: 500 }, { ...base, id: 'a_3', status: 'voided', amount: 500 }, { ...base, id: 'a_4', status: 'expired', amount: 500 }]));
  const nowHeld = await me(t.ada);
  assert.deepEqual(money(nowHeld), [10000, 2000, 8000]);
  assert.deepEqual(money(await me(t.ada, '?as_of=2026-09-20T12:00:00Z')), [10000, 0, 10000]); // before the reset instant
  assert.deepEqual(money(await me(t.ada, `?as_of=${q(iso(Date.now() + 5000))}`)), [10000, 2000, 8000]);
  const auths = (await get('/authorizations', t.ada)).body.authorizations;
  assert.deepEqual(auths.map((a) => [a.authorization_id, a.closed_at !== null]).sort(), [['a_1', false], ['a_2', true], ['a_3', true], ['a_4', true]]);
  assert.equal(auths.find((a) => a.authorization_id === 'a_4').closed_at, '2099-01-01T00:00:00+00:00');
  // a supplied created_at places the hold in history
  t = await setup(fx([{ ...base, status: 'open', created_at: D('11:00') }]));
  assert.deepEqual(money(await me(t.ada, '?as_of=2026-09-20T10:59:59Z')), [13500, 0, 13500]);
  assert.deepEqual(money(await me(t.ada, '?as_of=2026-09-20T11:00:00Z')), [15000, 2000, 13000]);
});

test('recorded times strictly increase along one payment, also for back-to-back corrections', async () => {
  const t = await setup();
  const recorded = [];
  let rev = 1;
  for (let i = 0; i < 12; i++) {
    const r = await correct(t.ada, 'p3', { expected_revision: rev, amount: 4000 + i, effective_at: D('12:00'), reason: `r${i}` });
    assert.equal(r.status, 201);
    rev = r.body.revision;
    recorded.push(Date.parse(r.body.recorded_at));
  }
  for (let i = 1; i < recorded.length; i++) assert.ok(recorded[i] > recorded[i - 1]);
  const hist = (await get('/payments/p3/revisions', t.ada)).body.revisions;
  assert.equal(hist.length, 13);
  for (let i = 1; i < hist.length; i++) assert.ok(Date.parse(hist[i].recorded_at) > Date.parse(hist[i - 1].recorded_at));
});

test('export/import keeps revisions, snapshots, closed_at and retry receipts; the clock never runs behind', async () => {
  const t = await setup();
  const c = await correct(t.ada, 'p3', { expected_revision: 1, amount: 4000, effective_at: D('12:00'), reason: 'r' }, 'ck');
  const first = (await get('/statement?limit=1', t.ada)).body;
  const hold = (await call('POST', '/authorizations', { token: t.ada, key: 'h', body: { to_handle: 'bob', amount: 100 } })).body;
  await call('POST', `/authorizations/${hold.authorization_id}/void`, { token: t.ada });
  const exp = await call('GET', '/_test/export');
  const doc = JSON.parse(exp.text);
  assert.equal(doc.format_version, 1);
  assert.equal(doc.track, 'pocketful');
  assert.ok(!exp.text.includes('correct horse'));
  const stmt = (await get(`/statement?snapshot=${first.snapshot}&limit=50`, t.ada)).body;
  const feed = (await get('/activity', t.ada)).text;
  await h.reset({ users: [user('zed', 'zed', 5)] });
  err(await get(`/statement?snapshot=${first.snapshot}`, t.ada), 401, 'unauthenticated');
  for (let i = 0; i < 2; i++) assert.equal((await call('POST', '/_test/import', { body: exp.text })).status, 204);
  assert.deepEqual((await get(`/statement?snapshot=${first.snapshot}&limit=50`, t.ada)).body, stmt);
  assert.equal((await get('/activity', t.ada)).text, feed);
  const replay = await correct(t.ada, 'p3', { expected_revision: 1, amount: 4000, effective_at: D('12:00'), reason: 'r' }, 'ck');
  assert.equal(replay.status, 200);
  assert.deepEqual(replay.body, c.body);
  assert.deepEqual((await get('/payments/p3/revisions', t.cy)).body.revisions.map((r) => r.amount), [5000, 4000]);
  assert.notEqual((await get('/authorizations', t.ada)).body.authorizations[0].closed_at, null);
  // new recorded times come after everything already recorded
  const next = await correct(t.ada, 'p3', { expected_revision: 2, amount: 3900, effective_at: D('12:00'), reason: 'again' });
  assert.ok(Date.parse(next.body.recorded_at) > Date.parse(c.body.recorded_at));
  // tampering with a revision is rejected, destination unchanged
  const before = await me(t.ada);
  const tamper = [
    (d) => { d.state.payments.find((p) => p.id === 'p3').revisions[1].amount = 1; },
    (d) => { d.state.payments.find((p) => p.id === 'p3').revisions[0].recorded_at = D('13:00'); },
    (d) => { d.state.payments.find((p) => p.id === 'p3').revisions[1].recorded_at = D('09:00'); },
    (d) => { d.state.payments.find((p) => p.id === 'p3').revisions[1].reason = ''; },
    (d) => { d.state.payments.find((p) => p.id === 'p3').revisions[1].revision = 5; },
    (d) => { d.state.payments.find((p) => p.id === 'p3').revisions = []; },
    (d) => { d.state.payments.find((p) => p.id === 'p3').revisions[1].seq = d.state.payments[0].revisions[0].seq; },
    (d) => { d.state.snapshots[0].user_id = 'ghost'; },
    (d) => { d.state.snapshots[0].seq = 999999; },
    (d) => { d.state.snapshots[0].to = 'later'; },
    (d) => { d.state.users[0].opening_balance += 1; },
    (d) => { d.state.authorizations[0].closed_at = null; },
    (d) => { d.state.layout = 4; },
  ];
  for (const mutate of tamper) {
    const d = JSON.parse(exp.text);
    mutate(d);
    err(await call('POST', '/_test/import', { body: d }), 422, 'validation_failed');
  }
  assert.deepEqual(await me(t.ada), before);
  // the clock is never behind an imported state
  const future = JSON.parse(exp.text);
  const stamp = '2099-01-01T00:00:00.000+00:00';
  const p1 = future.state.payments.find((p) => p.id === 'p1');
  p1.created_at = stamp; p1.revisions[0].effective_at = stamp; p1.revisions[0].recorded_at = stamp;
  assert.equal((await call('POST', '/_test/import', { body: future })).status, 204);
  const later = await call('POST', '/payments', { token: t.ada, key: 'after-import', body: { to_handle: 'bob', amount: 1 } });
  assert.ok(Date.parse(later.body.created_at) >= Date.parse(stamp));
});

test('a signed-up user opens at zero and has a consistent history', async () => {
  const t = await setup();
  const su = await call('POST', '/auth/signup', { body: { email: 'new.person@x.io', password: 'longenough', display_name: 'New' } });
  const tok = su.body.token;
  assert.equal((await me(tok, '?as_of=2000-01-01T00:00:00Z')).balance, 0);
  const p = (await call('POST', '/payments', { token: t.ada, key: 'to-new', body: { to_handle: 'new_person', amount: 250 } })).body;
  const s = (await get('/statement', tok)).body;
  assert.deepEqual([s.opening_balance, s.closing_balance, s.entries.map((e) => e.delta)], [0, 250, [250]]);
  assert.equal((await me(tok, `?as_of=${q(p.created_at)}`)).balance, 250);
  assert.equal((await me(tok, `?as_of=${q(iso(Date.parse(p.created_at) - 1))}`)).balance, 0);
  const sum = (await Promise.all([t.ada, t.bob, t.cy, tok].map((x) => me(x, '?as_of=2099-01-01T00:00:00Z')))).reduce((a, v) => a + v.total, 0);
  assert.equal(sum, 18000);
  // export/import keeps the zero opening
  const exp = await call('GET', '/_test/export');
  assert.equal((await call('POST', '/_test/import', { body: exp.text })).status, 204);
  assert.equal((await get('/statement', tok)).body.opening_balance, 0);
});
