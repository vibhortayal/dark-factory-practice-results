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
/** ada 10000, bob 2500, cy 5500 after p1 bob->cy 2000, p2 cy->ada 1500, p3 ada->cy 5000. */
const HISTORY = () => ({
  currency: 'EUR', minor_units: 2,
  users: [user('ada', 'ada', 10000), user('bob', 'bob', 2500), user('cy', 'cy', 5500)],
  payments: [pay('p1', 'bob', 'cy', 2000, D('10:00')), pay('p2', 'cy', 'ada', 1500, D('11:00')), pay('p3', 'ada', 'cy', 5000, D('12:00'))],
  settlement_operator_ids: ['u_bob'],
});
async function setup(fx = HISTORY()) {
  await h.reset(fx);
  return h.tokens();
}
const get = (path, token) => call('GET', path, { token });
const me = async (token, q = '') => (await get(`/me${q}`, token)).body;
const refund = (token, id, body, key = k()) => call('POST', `/payments/${id}/refunds`, { token, key, body });
const correct = (token, id, body, key = k()) => call('POST', `/payments/${id}/corrections`, { token, key, body });

test('refund: shape, money, replay, feed and statements', async () => {
  const t = await setup();
  const r = await refund(t.cy, 'p3', { amount: 1000 }, 'rk');
  assert.equal(r.status, 201);
  assert.deepEqual(Object.keys(r.body), ['payment_id', 'from_user_id', 'from_handle', 'to_user_id', 'to_handle', 'amount', 'currency', 'note', 'visibility', 'request_id', 'settlement_id', 'authorization_id', 'refund_of', 'created_at']);
  assert.deepEqual([r.body.from_handle, r.body.to_handle, r.body.amount, r.body.refund_of, r.body.request_id, r.body.settlement_id, r.body.authorization_id, r.body.note, r.body.visibility], ['cy', 'ada', 1000, 'p3', null, null, null, 'p3', 'public']);
  assert.deepEqual([(await me(t.ada)).balance, (await me(t.cy)).balance], [11000, 4500]);
  const replay = await refund(t.cy, 'p3', { amount: 1000 }, 'rk');
  assert.equal(replay.status, 200);
  assert.deepEqual(replay.body, r.body);
  err(await refund(t.cy, 'p3', { amount: 999 }, 'rk'), 409, 'idempotency_key_reuse');
  assert.equal((await me(t.ada)).balance, 11000);
  // an ordinary payment for every read; other payments carry refund_of: null
  const feed = (await get('/activity', t.bob)).body.payments;
  assert.equal(feed.find((p) => p.payment_id === r.body.payment_id).refund_of, 'p3');
  assert.equal(feed.find((p) => p.payment_id === 'p1').refund_of, null);
  const s = (await get('/statement', t.ada)).body;
  const entry = s.entries.find((e) => e.payment.payment_id === r.body.payment_id);
  assert.deepEqual([entry.delta, entry.revision, entry.payment.refund_of], [1000, 1, 'p3']);
  assert.equal(s.closing_balance, 11000);
  assert.equal((await get('/statement', t.cy)).body.entries.find((e) => e.payment.payment_id === r.body.payment_id).delta, -1000);
  // the target and its revisions are untouched
  assert.deepEqual((await get('/payments/p3/revisions', t.ada)).body.revisions.map((x) => x.amount), [5000]);
  const views = await Promise.all([t.ada, t.bob, t.cy].map((x) => me(x, `?as_of=${encodeURIComponent(r.body.created_at)}`)));
  assert.equal(views.reduce((a, v) => a + v.total, 0), 18000);
  // a private payment's refund keeps its visibility and note
  const t2 = await setup({ ...HISTORY(), payments: [pay('pp', 'ada', 'cy', 100, D('10:00'), { visibility: 'private', note: 'secret 🍝' })], users: [user('ada', 'ada', 100), user('bob', 'bob', 0), user('cy', 'cy', 100)] });
  const pr = await refund(t2.cy, 'pp', { amount: 40 });
  assert.deepEqual([pr.body.visibility, pr.body.note], ['private', 'secret 🍝']);
  assert.ok(!(await get('/activity', t2.bob)).text.includes(pr.body.payment_id));
});

test('refund: refusals and precedence', async () => {
  const t = await setup();
  err(await call('POST', '/payments/p3/refunds', { body: { amount: 1 }, key: 'x' }), 401, 'unauthenticated');
  err(await call('POST', '/payments/p3/refunds', { token: t.cy, body: { amount: 1 } }), 400, 'missing_idempotency_key');
  err(await refund(t.cy, 'p3', '[]'), 400, 'malformed_request');
  for (const amount of [0, -1, 1000000001, 1.5, '5', null, true, [], {}]) err(await refund(t.cy, 'p3', { amount }), 422, 'validation_failed');
  err(await refund(t.cy, 'p3', {}), 422, 'validation_failed');
  assert.equal((await refund(t.cy, 'p3', '{"amount":1e3}')).status, 201);
  assert.equal((await refund(t.cy, 'p3', '{"amount":1000.0}')).status, 201);
  // validation before 404 before 403
  err(await refund(t.cy, 'nope', { amount: 0 }), 422, 'validation_failed');
  err(await refund(t.cy, 'nope', { amount: 1 }), 404, 'not_found');
  err(await refund(t.ada, 'p3', { amount: 1 }), 403, 'forbidden'); // the sender
  err(await refund(t.bob, 'p3', { amount: 1 }), 403, 'forbidden'); // a third party and operator
  // refunds of refunds
  const r = (await refund(t.cy, 'p3', { amount: 10 })).body;
  err(await refund(t.ada, r.payment_id, { amount: 1 }), 422, 'invalid_refund_target');
  err(await refund(t.cy, r.payment_id, { amount: 1 }), 403, 'forbidden');
  err(await refund(t.ada, r.payment_id, { amount: 1 }, 'x'), 422, 'invalid_refund_target');
  // cumulative: 5000 paid, 2010 refunded so far
  err(await refund(t.cy, 'p3', { amount: 2991 }), 422, 'refund_exceeds_payment');
  assert.equal((await refund(t.cy, 'p3', { amount: 2990 })).status, 201);
  err(await refund(t.cy, 'p3', { amount: 1 }), 422, 'refund_exceeds_payment');
  // exceeding beats funds
  const t2 = await setup();
  await call('POST', '/authorizations', { token: t2.cy, key: 'h', body: { to_handle: 'bob', amount: 5500 } });
  err(await refund(t2.cy, 'p3', { amount: 1 }), 409, 'insufficient_funds'); // held money cannot fund a refund
  err(await refund(t2.cy, 'p3', { amount: 5001 }), 422, 'refund_exceeds_payment');
  assert.equal((await me(t2.cy)).balance, 5500);
  // nothing changed by the refusals
  assert.equal((await get('/activity?limit=200', t2.ada)).body.payments.filter((p) => p.refund_of).length, 0);
});

test('refunds of captures, request payments and settlement members change no link', async () => {
  const t = await setup({ ...HISTORY(), requests: [{ id: 'rq_1', requester_id: 'u_cy', payer_id: 'u_ada', amount: 300, note: 'r', status: 'pending' }] });
  // capture
  const a = (await call('POST', '/authorizations', { token: t.ada, key: 'a', body: { to_handle: 'bob', amount: 300 } })).body;
  const cap = (await call('POST', `/authorizations/${a.authorization_id}/capture`, { token: t.bob, key: 'c', body: { amount: 200 } })).body;
  const rc = await refund(t.bob, cap.payment_id, { amount: 150 });
  assert.equal(rc.status, 201);
  assert.equal(rc.body.authorization_id, null);
  const auth = (await get('/authorizations', t.ada)).body.authorizations[0];
  assert.deepEqual([auth.status, auth.captured_amount, auth.remaining_amount, auth.payment_ids], ['captured', 200, 0, [cap.payment_id]]);
  assert.equal((await me(t.ada)).held, 0);
  // request payment
  const pr = (await call('POST', '/requests/rq_1/pay', { token: t.ada, key: 'rp', body: {} })).body;
  const rr = await refund(t.cy, pr.payment_id, { amount: 300 });
  assert.equal(rr.status, 201);
  assert.equal(rr.body.request_id, null);
  const request = (await get('/requests', t.ada)).body.requests.find((r) => r.request_id === 'rq_1');
  assert.deepEqual([request.status, request.payment_id], ['paid', pr.payment_id]);
  // settlement member
  const st = await call('POST', '/settlements', { token: t.bob, key: 's', body: { transfers: [{ from_handle: 'ada', to_handle: 'cy', amount: 100 }, { from_handle: 'cy', to_handle: 'ada', amount: 20 }] } });
  const member = st.body.payments[0];
  const rs = await refund(t.cy, member.payment_id, { amount: 100 });
  assert.equal(rs.status, 201);
  assert.equal(rs.body.settlement_id, null);
  const replay = await call('POST', '/settlements', { token: t.bob, key: 's', body: { transfers: [{ from_handle: 'ada', to_handle: 'cy', amount: 100 }, { from_handle: 'cy', to_handle: 'ada', amount: 20 }] } });
  assert.deepEqual(replay.body, st.body);
  const doc = (await call('GET', '/_test/export')).body;
  assert.deepEqual(doc.state.settlements[0].payment_ids, st.body.payments.map((p) => p.payment_id));
  err(await refund(t.cy, member.payment_id, { amount: 1 }), 422, 'refund_exceeds_payment');
});

test('refunds and corrections: immutability, refunded floor, precedence', async () => {
  const t = await setup();
  const r = (await refund(t.cy, 'p3', { amount: 1000 })).body;
  const body = (amount, rev = 1) => ({ expected_revision: rev, amount, effective_at: D('12:00'), reason: 'r' });
  err(await correct(t.cy, r.payment_id, { ...body(1), effective_at: r.created_at }), 422, 'linked_payment_immutable');
  err(await correct(t.cy, r.payment_id, { ...body(1), expected_revision: 9, effective_at: r.created_at }), 422, 'linked_payment_immutable');
  err(await correct(t.ada, 'p3', body(999)), 422, 'refund_exceeds_payment');
  err(await correct(t.ada, 'p3', body(999, 7)), 409, 'stale_revision'); // stale first
  assert.equal((await correct(t.ada, 'p3', body(1000))).status, 201); // exactly the refunded total
  const corrected = await call('GET', '/payments/p3/revisions', { token: t.ada });
  assert.deepEqual(corrected.body.revisions.map((x) => x.amount), [5000, 1000]);
  err(await refund(t.cy, 'p3', { amount: 1 }), 422, 'refund_exceeds_payment');
  // corrected up: refundable again
  assert.equal((await correct(t.ada, 'p3', body(2000, 2))).status, 201);
  assert.equal((await refund(t.cy, 'p3', { amount: 1000 })).status, 201);
  // corrected to zero: nothing refundable
  const t2 = await setup();
  assert.equal((await correct(t2.ada, 'p3', body(0))).status, 201);
  err(await refund(t2.cy, 'p3', { amount: 1 }), 422, 'refund_exceeds_payment');
  // correction below the refunded total comes before funds
  const t3 = await setup();
  await refund(t3.cy, 'p3', { amount: 1000 });
  err(await correct(t3.ada, 'p3', body(500)), 422, 'refund_exceeds_payment');
});

test('concurrent refunds never exceed the corrected amount', async () => {
  const t = await setup();
  const rs = await Promise.all(Array.from({ length: 50 }, (_, i) => refund(t.cy, 'p3', { amount: 600 }, `c${i}`)));
  assert.equal(rs.filter((r) => r.status === 201).length, 8); // 8 x 600 <= 5000 < 9 x 600
  assert.equal(rs.filter((r) => r.status === 422).length, 42);
  const mixed = await Promise.all([
    ...Array.from({ length: 10 }, (_, i) => correct(t.ada, 'p3', { expected_revision: 1, amount: 4800 - i, effective_at: D('12:00'), reason: 'm' }, `m${i}`)),
    ...Array.from({ length: 10 }, (_, i) => refund(t.cy, 'p3', { amount: 50 }, `n${i}`)),
  ]);
  assert.ok(mixed.every((r) => r.status < 500));
  const revs = (await get('/payments/p3/revisions', t.ada)).body.revisions;
  const refunded = (await get('/activity?limit=200', t.ada)).body.payments.filter((p) => p.refund_of === 'p3').reduce((a, p) => a + p.amount, 0);
  assert.ok(refunded <= revs[revs.length - 1].amount);
  const total = (await Promise.all([t.ada, t.bob, t.cy].map((x) => me(x)))).reduce((a, v) => a + v.total, 0);
  assert.equal(total, 18000);
  const same = await Promise.all(Array.from({ length: 50 }, () => refund(t.bob, 'p1', { amount: 10 }, 'same')));
  assert.equal(same.filter((r) => r.status === 201).length + same.filter((r) => r.status === 403).length, 50); // bob sent p1: forbidden
  const ok = await Promise.all(Array.from({ length: 50 }, () => refund(t.cy, 'p1', { amount: 10 }, 'same')));
  assert.equal(ok.filter((r) => r.status === 201).length, 1);
  assert.equal(ok.filter((r) => r.status === 200).length, 49);
});

test('upgrade: saved snapshots keep their layout; new ones show refund_of', async () => {
  const t = await setup();
  const first = (await get('/statement?limit=1', t.ada)).body;
  assert.ok('refund_of' in first.entries[0].payment);
  // a snapshot taken under the stage-3 layout, as an older export would carry it
  const doc = (await call('GET', '/_test/export')).body;
  const old = JSON.parse(JSON.stringify(doc));
  old.state.layout = 3;
  delete old.state.batches;
  delete old.state.counters.batch;
  for (const p of old.state.payments) delete p.refund_of;
  for (const p of old.state.payments) for (const r of p.revisions) delete r.correction_batch_id;
  old.state.snapshots.forEach((s) => { delete s.layout; });
  assert.equal((await call('POST', '/_test/import', { body: old })).status, 204);
  const paged = (await get(`/statement?snapshot=${first.snapshot}&limit=50`, t.ada)).body;
  assert.equal(paged.entries.length, 2);
  for (const e of paged.entries) {
    assert.ok(!('refund_of' in e.payment), 'no stage-4 field inside a saved statement');
    assert.deepEqual(Object.keys(e), ['payment', 'delta', 'balance_after', 'revision', 'effective_at', 'recorded_at']);
  }
  // refunds and corrections afterwards do not change what the old token pages
  await refund(t.cy, 'p3', { amount: 100 });
  await correct(t.ada, 'p3', { expected_revision: 1, amount: 4000, effective_at: D('12:00'), reason: 'r' });
  assert.deepEqual((await get(`/statement?snapshot=${first.snapshot}&limit=50`, t.ada)).body, paged);
  // a fresh read uses the new layout
  const fresh = (await get('/statement', t.ada)).body;
  assert.ok(fresh.entries.every((e) => 'refund_of' in e.payment));
  // the snapshot layout survives a stage-4 export/import
  const again = await call('GET', '/_test/export');
  assert.equal((await call('POST', '/_test/import', { body: again.text })).status, 204);
  assert.deepEqual((await get(`/statement?snapshot=${first.snapshot}&limit=50`, t.ada)).body, paged);
  assert.ok('refund_of' in (await get(`/statement?snapshot=${fresh.snapshot}&limit=50`, t.ada)).body.entries[0].payment);
});

test('export/import keeps refunds and their links; tampered refunds are refused', async () => {
  const t = await setup();
  const r = (await refund(t.cy, 'p3', { amount: 700 }, 'rk')).body;
  const exp = await call('GET', '/_test/export');
  assert.equal((await call('POST', '/_test/import', { body: exp.text })).status, 204);
  assert.equal((await refund(t.cy, 'p3', { amount: 700 }, 'rk')).status, 200);
  err(await refund(t.cy, 'p3', { amount: 4301 }), 422, 'refund_exceeds_payment');
  assert.equal((await refund(t.cy, 'p3', { amount: 4300 })).status, 201);
  const before = await me(t.ada);
  const tamper = [
    (d) => { d.state.payments.find((p) => p.id === r.payment_id).refund_of = 'ghost'; },
    (d) => { d.state.payments.find((p) => p.id === r.payment_id).amount = 9999; },
    (d) => { d.state.payments.find((p) => p.id === r.payment_id).settlement_id = 'st_1'; },
    (d) => { d.state.payments.find((p) => p.id === 'p1').refund_of = r.payment_id; },
    (d) => { d.state.payments.find((p) => p.id === r.payment_id).refund_of = r.payment_id; },
    (d) => { const p = d.state.payments.find((x) => x.id === r.payment_id); [p.from, p.to] = [p.to, p.from]; },
  ];
  for (const mutate of tamper) {
    const d = JSON.parse(exp.text);
    mutate(d);
    err(await call('POST', '/_test/import', { body: d }), 422, 'validation_failed');
  }
  assert.deepEqual(await me(t.ada), before);
});
