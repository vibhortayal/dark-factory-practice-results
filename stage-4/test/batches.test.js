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
const FIXTURE = (extra = {}) => ({
  currency: 'EUR', minor_units: 2,
  // ada 10000, bob 2500, cy 5500, op 0 (operator)
  users: [user('ada', 'ada', 10000), user('bob', 'bob', 2500), user('cy', 'cy', 5500), user('op', 'op', 0)],
  payments: [pay('p1', 'bob', 'cy', 2000, D('10:00')), pay('p2', 'cy', 'ada', 1500, D('11:00')), pay('p3', 'ada', 'cy', 5000, D('12:00'))],
  settlement_operator_ids: ['u_op'],
  ...extra,
});
async function setup(fx = FIXTURE()) {
  await h.reset(fx);
  return { ...(await h.tokens()), op: await h.login('op@example.com') };
}
const get = (path, token) => call('GET', path, { token });
const me = async (token, q = '') => (await get(`/me${q}`, token)).body;
const batch = (token, corrections, key = k()) => call('POST', '/correction-batches', { token, key, body: { corrections } });
const item = (payment_id, amount, over = {}) => ({ payment_id, expected_revision: 1, amount, effective_at: D('12:00'), reason: 'r', ...over });

test('batch: access, shape and key rules', async () => {
  const t = await setup();
  err(await call('POST', '/correction-batches', { key: 'x', body: { corrections: [item('p3', 1)] } }), 401, 'unauthenticated');
  err(await batch(t.ada, [item('p3', 1)]), 403, 'forbidden');
  err(await call('POST', '/correction-batches', { token: t.ada, body: {} }), 403, 'forbidden'); // operator check precedes the key
  err(await call('POST', '/correction-batches', { token: t.op, body: { corrections: [item('p3', 1)] } }), 400, 'missing_idempotency_key');
  err(await call('POST', '/correction-batches', { token: t.op, key: 'k'.repeat(256), body: { corrections: [item('p3', 1)] } }), 422, 'validation_failed');
  err(await call('POST', '/correction-batches', { token: t.op, key: 'a', body: '[]' }), 400, 'malformed_request');
  const many = (n) => Array.from({ length: n }, (_, i) => item(`x${i}`, 1));
  for (const corrections of [undefined, 'x', {}, [], many(33), [5], [null], [item('p3', 1), item('p3', 2)], [item('p3', 1), 'x']]) {
    err(await call('POST', '/correction-batches', { token: t.op, key: k(), body: { corrections } }), 422, 'validation_failed');
  }
  // unknown fields are ignored
  const ok = await call('POST', '/correction-batches', { token: t.op, key: k(), body: { corrections: [{ ...item('p3', 4000), extra: 1 }], more: 2 } });
  assert.equal(ok.status, 201);
});

test('batch: response, shared recorded_at, batch ids, money and history', async () => {
  const t = await setup();
  const r = await batch(t.op, [item('p3', 4000, { reason: 'a' }), item('p1', 1500, { effective_at: D('10:00'), reason: 'b' })], 'bk');
  assert.equal(r.status, 201);
  assert.deepEqual(Object.keys(r.body), ['correction_batch_id', 'recorded_at', 'revisions']);
  assert.match(r.body.correction_batch_id, /^[^\s]{1,64}$/);
  assert.deepEqual(r.body.revisions.map((x) => [x.payment_id, x.revision, x.amount, x.effective_at, x.reason, x.correction_batch_id]), [['p3', 2, 4000, D('12:00'), 'a', r.body.correction_batch_id], ['p1', 2, 1500, D('10:00'), 'b', r.body.correction_batch_id]]);
  for (const rev of r.body.revisions) {
    assert.deepEqual(Object.keys(rev), ['payment_id', 'revision', 'amount', 'effective_at', 'recorded_at', 'reason', 'correction_batch_id']);
    assert.equal(rev.recorded_at, r.body.recorded_at);
  }
  assert.ok(Date.parse(r.body.recorded_at) > Date.parse(D('12:00')));
  // p3 -1000 (receiver cy debited, ada credited); p1 -500 (receiver cy debited, bob credited)
  assert.deepEqual([(await me(t.ada)).balance, (await me(t.bob)).balance, (await me(t.cy)).balance, (await me(t.op)).balance], [11000, 3000, 4000, 0]);
  const revs = (await get('/payments/p3/revisions', t.ada)).body.revisions;
  assert.deepEqual(revs.map((x) => [x.revision, x.correction_batch_id]), [[1, null], [2, r.body.correction_batch_id]]);
  // single corrections report a null batch id
  const single = await call('POST', '/payments/p3/corrections', { token: t.ada, key: k(), body: { expected_revision: 2, amount: 3900, effective_at: D('12:00'), reason: 'x' } });
  assert.equal(single.body.correction_batch_id, null);
  // replay and reuse
  const replay = await batch(t.op, [item('p3', 4000, { reason: 'a' }), item('p1', 1500, { effective_at: D('10:00'), reason: 'b' })], 'bk');
  assert.equal(replay.status, 200);
  assert.deepEqual(replay.body, r.body);
  err(await batch(t.op, [item('p3', 4001)], 'bk'), 409, 'idempotency_key_reuse');
  // two batches in a row: later and increasing, distinct ids
  const r2 = await batch(t.op, [item('p1', 1600, { expected_revision: 2, effective_at: D('10:00') })]);
  assert.equal(r2.status, 201);
  assert.notEqual(r2.body.correction_batch_id, r.body.correction_batch_id);
  assert.ok(Date.parse(r2.body.recorded_at) > Date.parse(r.body.recorded_at));
  // original receipts and the feed are unchanged; statements reflect the corrections
  const feed = (await get('/activity?limit=200', t.ada)).body.payments;
  assert.equal(feed.find((p) => p.payment_id === 'p3').amount, 5000);
  const s = (await get('/statement', t.cy)).body;
  assert.deepEqual(s.entries.map((e) => [e.payment.payment_id, e.revision, e.payment.amount]), [['p1', 3, 1600], ['p2', 1, 1500], ['p3', 3, 3900]]);
  assert.equal(s.opening_balance + s.entries.reduce((a, e) => a + e.delta, 0), s.closing_balance);
  const sum = (await Promise.all([t.ada, t.bob, t.cy, t.op].map((x) => me(x)))).reduce((a, v) => a + v.total, 0);
  assert.equal(sum, 18000);
});

test('batch: item errors in input order, with the per-item precedence', async () => {
  const t = await setup();
  const a = (await call('POST', '/authorizations', { token: t.ada, key: 'a', body: { to_handle: 'bob', amount: 300 } })).body;
  const cap = (await call('POST', `/authorizations/${a.authorization_id}/capture`, { token: t.bob, key: 'c', body: { amount: 200 } })).body;
  const ref = (await call('POST', '/payments/p3/refunds', { token: t.cy, key: 'rf', body: { amount: 1000 } })).body;
  const run = (items) => batch(t.op, items);
  // per item: fields -> unknown -> linked -> stale -> refunds
  err(await run([item('p3', -1)]), 422, 'validation_failed');
  err(await run([item('p3', 1, { reason: '' })]), 422, 'validation_failed');
  err(await run([item('p3', 1, { effective_at: '2099-01-01T00:00:00Z' })]), 422, 'validation_failed');
  err(await run([item(5, 1)]), 422, 'validation_failed');
  err(await run([{ amount: 1, expected_revision: 1, effective_at: D('12:00'), reason: 'r' }]), 422, 'validation_failed');
  err(await run([item('nope', 1)]), 404, 'not_found');
  err(await run([item(cap.payment_id, 1, { effective_at: cap.created_at })]), 422, 'linked_payment_immutable');
  err(await run([item(ref.payment_id, 1, { effective_at: ref.created_at })]), 422, 'linked_payment_immutable');
  err(await run([item('p3', 1, { expected_revision: 9 })]), 409, 'stale_revision');
  err(await run([item('p3', 999)]), 422, 'refund_exceeds_payment');
  err(await run([item('p3', 999, { expected_revision: 9 })]), 409, 'stale_revision');
  // first bad item decides, in input order
  err(await run([item('p3', 4000), item('nope', 1), item('p1', 1, { expected_revision: 9 })]), 404, 'not_found');
  err(await run([item('p3', 4000), item('p1', 1, { expected_revision: 9 }), item('nope', 1)]), 409, 'stale_revision');
  err(await run([item('p3', 4000), item(cap.payment_id, 1), item('p1', -5)]), 422, 'linked_payment_immutable');
  err(await run([item('p3', 4000), item('p1', -5), item('nope', 1)]), 422, 'validation_failed');
  // exactly the refunded total is fine
  assert.equal((await run([item('p3', 1000)])).status, 201);
  // nothing changed by any refusal: key still free
  const before = (await get('/payments/p1/revisions', t.bob)).body.revisions.length;
  assert.equal(before, 1);
});

test('batch: settlements as a whole, at one effective instant, with differing amounts', async () => {
  const t = await setup();
  const st = (await call('POST', '/settlements', { token: t.op, key: 's', body: { transfers: [{ from_handle: 'ada', to_handle: 'bob', amount: 100 }, { from_handle: 'bob', to_handle: 'cy', amount: 50 }, { from_handle: 'cy', to_handle: 'ada', amount: 10 }] } })).body;
  const [m1, m2, m3] = st.payments.map((p) => p.payment_id);
  const at = Date.parse(st.committed_at);
  const eff = new Date(at - 5).toISOString().replace('Z', '+00:00');
  const mk = (id, amount, over = {}) => item(id, amount, { effective_at: eff, ...over });
  // single corrections still refuse members
  err(await call('POST', `/payments/${m1}/corrections`, { token: t.ada, key: k(), body: mk(m1, 1) }), 422, 'linked_payment_immutable');
  // incomplete
  err(await batch(t.op, [mk(m1, 90)]), 422, 'incomplete_settlement');
  err(await batch(t.op, [mk(m1, 90), mk(m2, 40)]), 422, 'incomplete_settlement');
  err(await batch(t.op, [mk(m1, 90), mk(m2, 40), mk('p3', 4000, { effective_at: D('12:00') })]), 422, 'incomplete_settlement');
  // different instants (same instant in another spelling is fine)
  err(await batch(t.op, [mk(m1, 90), mk(m2, 40), mk(m3, 5, { effective_at: new Date(at - 4).toISOString().replace('Z', '+00:00') })]), 422, 'validation_failed');
  const sameInstant = eff.replace('+00:00', 'Z');
  const offsetSpelling = new Date(at - 5 + 7200000).toISOString().replace('Z', '+02:00').replace(/^(\d{4}-\d\d-\d\dT)/, '$1');
  void offsetSpelling;
  const ok = await batch(t.op, [mk(m1, 90), mk(m2, 40, { effective_at: sameInstant }), mk(m3, 0)], 'sk');
  assert.equal(ok.status, 201);
  assert.deepEqual(ok.body.revisions.map((r) => [r.payment_id, r.amount]), [[m1, 90], [m2, 40], [m3, 0]]);
  assert.deepEqual([(await me(t.ada)).balance, (await me(t.bob)).balance, (await me(t.cy)).balance], [9910, 2550, 5540]);
  // the settlement receipt and membership are unchanged
  const replay = await call('POST', '/settlements', { token: t.op, key: 's', body: { transfers: [{ from_handle: 'ada', to_handle: 'bob', amount: 100 }, { from_handle: 'bob', to_handle: 'cy', amount: 50 }, { from_handle: 'cy', to_handle: 'ada', amount: 10 }] } });
  assert.deepEqual(replay.body, st);
  assert.ok((await get('/activity?limit=200', t.ada)).body.payments.find((p) => p.payment_id === m1).amount === 100);
  const rv = (await get(`/payments/${m1}/revisions`, t.ada)).body.revisions;
  assert.deepEqual(rv.map((r) => r.amount), [100, 90]);
  // a refund of a corrected member respects the new amount
  err(await call('POST', `/payments/${m1}/refunds`, { token: t.bob, key: k(), body: { amount: 91 } }), 422, 'refund_exceeds_payment');
  assert.equal((await call('POST', `/payments/${m1}/refunds`, { token: t.bob, key: k(), body: { amount: 90 } })).status, 201);
});

test('batch: precedence of completeness, current funds and history', async () => {
  const t = await setup();
  // current funds: ada would owe more than she has
  err(await batch(t.op, [item('p3', 16000)]), 409, 'insufficient_funds');
  // incomplete settlement beats funds
  const st = (await call('POST', '/settlements', { token: t.op, key: 's', body: { transfers: [{ from_handle: 'ada', to_handle: 'bob', amount: 100 }, { from_handle: 'bob', to_handle: 'cy', amount: 50 }] } })).body;
  const eff = new Date(Date.parse(st.committed_at) - 3).toISOString().replace('Z', '+00:00');
  err(await batch(t.op, [item('p3', 16000), item(st.payments[0].payment_id, 1, { effective_at: eff })]), 422, 'incomplete_settlement');
  // funds beat history: cy (5500) would be debited 2000 and more...
  const hist = await batch(t.op, [item('p1', 1000, { effective_at: D('10:00') })]);
  err(hist, 409, 'historical_overdraft'); // cy at 11:00 would hold 1000 - 1500 < 0 though 5500 is available now
  err(await batch(t.op, [item('p1', 1000, { effective_at: D('10:00') }), item('p3', 16000)]), 409, 'insufficient_funds');
  // moving income after the spend, without changing the amount
  err(await batch(t.op, [item('p1', 2000, { effective_at: D('11:30') })]), 409, 'historical_overdraft');
  // all refusals left everything alone
  assert.deepEqual([(await me(t.ada)).balance, (await me(t.cy)).balance], [9900, 5550]);
  assert.equal((await get('/payments/p1/revisions', t.bob)).body.revisions.length, 1);
  // a refused batch does not claim its key
  err(await batch(t.op, [item('p1', 1000, { effective_at: D('10:00') })], 'free'), 409, 'historical_overdraft');
  assert.equal((await batch(t.op, [item('p1', 1900, { effective_at: D('10:00') })], 'free')).status, 201);
});

test('batch: affordability is judged on the combined effect', async () => {
  // ada holds 1000: A raises ada->bob by 1500 (unaffordable alone), B raises bob->ada by 1500 (credits ada)
  const fx = FIXTURE({
    users: [user('ada', 'ada', 1000), user('bob', 'bob', 4000), user('cy', 'cy', 0), user('op', 'op', 0)],
    payments: [pay('a1', 'ada', 'bob', 1000, D('10:00')), pay('b1', 'bob', 'ada', 1000, D('10:00'))],
  });
  const t = await setup(fx);
  err(await call('POST', '/payments/a1/corrections', { token: t.ada, key: k(), body: item('a1', 2500, { effective_at: D('10:00') }) }), 409, 'insufficient_funds');
  const both = await batch(t.op, [item('a1', 2500, { effective_at: D('10:00') }), item('b1', 2500, { effective_at: D('10:00') })]);
  assert.equal(both.status, 201);
  assert.deepEqual([(await me(t.ada)).balance, (await me(t.bob)).balance], [1000, 4000]);
  // each affordable alone, not together
  const t2 = await setup(FIXTURE({
    users: [user('ada', 'ada', 1000), user('bob', 'bob', 0), user('cy', 'cy', 0), user('op', 'op', 0)],
    payments: [pay('a1', 'ada', 'bob', 100, D('10:00')), pay('a2', 'ada', 'cy', 100, D('10:00'))],
  }));
  assert.equal((await call('POST', '/payments/a1/corrections', { token: t2.ada, key: k(), body: item('a1', 900, { effective_at: D('10:00') }) })).status, 201);
  const t3 = await setup(FIXTURE({
    users: [user('ada', 'ada', 1000), user('bob', 'bob', 0), user('cy', 'cy', 0), user('op', 'op', 0)],
    payments: [pay('a1', 'ada', 'bob', 100, D('10:00')), pay('a2', 'ada', 'cy', 100, D('10:00'))],
  }));
  err(await batch(t3.op, [item('a1', 700, { effective_at: D('10:00') }), item('a2', 700, { effective_at: D('10:00') })]), 409, 'insufficient_funds');
  assert.equal((await batch(t3.op, [item('a1', 600, { effective_at: D('10:00') }), item('a2', 600, { effective_at: D('10:00') })])).status, 201);
  assert.deepEqual([(await me(t3.ada)).balance], [0]);
  // held funds are not available to a batch either
  const t4 = await setup(FIXTURE({
    users: [user('ada', 'ada', 1000), user('bob', 'bob', 0), user('cy', 'cy', 0), user('op', 'op', 0)],
    payments: [pay('a1', 'ada', 'bob', 100, D('10:00'))],
  }));
  await call('POST', '/authorizations', { token: t4.ada, key: 'h', body: { to_handle: 'cy', amount: 800 } });
  err(await batch(t4.op, [item('a1', 400, { effective_at: D('10:00') })]), 409, 'insufficient_funds');
  assert.equal((await batch(t4.op, [item('a1', 300, { effective_at: D('10:00') })])).status, 201);
});

test('batch: historical combination - two items that are only safe together', async () => {
  // cy receives p1 (2000) at 10:00 and spends p2 (1500) at 11:00. Moving p1 later alone breaks 11:00;
  // moving p2 later as well keeps cy non-negative.
  const t = await setup();
  err(await batch(t.op, [item('p1', 2000, { effective_at: D('11:30') })]), 409, 'historical_overdraft');
  const ok = await batch(t.op, [item('p1', 2000, { effective_at: D('11:30') }), item('p2', 1500, { effective_at: D('12:00') })]);
  assert.equal(ok.status, 201);
  const s = (await get('/statement', t.cy)).body;
  assert.deepEqual(s.entries.map((e) => [e.payment.payment_id, e.balance_after]), [['p1', 2000], ['p2', 500], ['p3', 5500]]);
});

test('batch: concurrency on shared expected revisions, and snapshots stay frozen', async () => {
  const t = await setup();
  const snap = (await get('/statement?limit=1', t.cy)).body;
  const rs = await Promise.all([
    ...Array.from({ length: 25 }, (_, i) => batch(t.op, [item('p3', 4000 + i), item('p1', 2000 - i, { effective_at: D('10:00') })], `b${i}`)),
    ...Array.from({ length: 25 }, (_, i) => call('POST', '/payments/p3/corrections', { token: t.ada, key: `s${i}`, body: item('p3', 3000 + i) })),
  ]);
  assert.equal(rs.filter((r) => r.status === 201).length, 1);
  assert.ok(rs.filter((r) => r.status !== 201).every((r) => r.status === 409 && r.body.error.code === 'stale_revision'));
  const sum = (await Promise.all([t.ada, t.bob, t.cy, t.op].map((x) => me(x)))).reduce((a, v) => a + v.total, 0);
  assert.equal(sum, 18000);
  const same = await Promise.all(Array.from({ length: 50 }, () => batch(t.op, [item('p2', 1400, { effective_at: D('11:00') })], 'same-batch')));
  assert.equal(same.filter((r) => r.status === 201).length, 1);
  assert.equal(same.filter((r) => r.status === 200).length, 49);
  assert.equal(new Set(same.map((r) => JSON.stringify(r.body))).size, 1);
  // the old snapshot pages the frozen entries
  const full = (await get(`/statement?snapshot=${snap.snapshot}&limit=50`, t.cy)).body;
  assert.deepEqual(full.entries.map((e) => [e.payment.payment_id, e.revision, e.payment.amount]), [['p1', 1, 2000], ['p2', 1, 1500], ['p3', 1, 5000]]);
});

test('batch: export/import keeps batch ids and shared times; tampering is refused', async () => {
  const t = await setup();
  const r = await batch(t.op, [item('p3', 4000), item('p1', 1900, { effective_at: D('10:00') })], 'bk');
  const exp = await call('GET', '/_test/export');
  assert.equal((await call('POST', '/_test/import', { body: exp.text })).status, 204);
  const replay = await batch(t.op, [item('p3', 4000), item('p1', 1900, { effective_at: D('10:00') })], 'bk');
  assert.equal(replay.status, 200);
  assert.deepEqual(replay.body, r.body);
  assert.deepEqual((await get('/payments/p3/revisions', t.ada)).body.revisions[1].correction_batch_id, r.body.correction_batch_id);
  const next = await batch(t.op, [item('p3', 3900, { expected_revision: 2 })]);
  assert.notEqual(next.body.correction_batch_id, r.body.correction_batch_id);
  const before = await me(t.ada);
  const tamper = [
    (d) => { d.state.batches[0].recorded_at = D('09:00'); },
    (d) => { d.state.batches[0].payment_ids = ['p2']; },
    (d) => { d.state.batches = []; },
    (d) => { d.state.batches[0].payment_ids = []; },
    (d) => { d.state.payments.find((p) => p.id === 'p3').revisions[1].correction_batch_id = 7; },
  ];
  for (const mutate of tamper) {
    const d = JSON.parse(exp.text);
    mutate(d);
    err(await call('POST', '/_test/import', { body: d }), 422, 'validation_failed');
  }
  assert.deepEqual(await me(t.ada), before);
});
