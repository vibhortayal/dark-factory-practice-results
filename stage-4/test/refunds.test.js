import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { startServer, FX, k, login, balanceSum } from './helper.js';

let c, t;
const err = (r, status, code) => { assert.equal(r.status, status, r.text); assert.equal(r.json.error.code, code); };
const enc = encodeURIComponent;
const at = (d) => new Date(Date.now() + d * 1000).toISOString().replace('Z', '+00:00');
const all = () => [t.ada, t.bob, t.cy, t.op];
const me = async (tok, qs = '') => (await c.get('/me' + qs, { token: tok })).json;

async function fresh(extra = {}) {
  assert.equal((await c.reset(FX(extra))).status, 204);
  t = {};
  for (const n of ['ada', 'bob', 'cy', 'op']) t[n] = await login(c, `${n}@example.com`);
}
before(async () => { c = await startServer(); await fresh(); });
after(() => c.stop());

const pay = async (tok, to, amount, extra = {}) => (await c.post('/payments', { token: tok, key: k(), body: { to_handle: to, amount, ...extra } })).json;
const refund = (tok, id, body, key = k()) => c.post(`/payments/${id}/refunds`, { token: tok, key, body });
const correct = (tok, id, body, key = k()) => c.post(`/payments/${id}/corrections`, { token: tok, key, body });
const goodBody = (o = {}) => ({ expected_revision: 1, amount: 400, effective_at: at(-5), reason: 'corrected amount', ...o });

test('BB1/BB6/BB9: a refund is a new payment in the opposite direction', async () => {
  await fresh();
  const p = await pay(t.ada, 'bob', 1000, { note: 'dinner 😀', visibility: 'private' });
  assert.equal(p.refund_of, null);
  const key = k();
  const r = await refund(t.bob, p.payment_id, { amount: 300 }, key);
  assert.equal(r.status, 201, r.text);
  assert.deepEqual(Object.keys(r.json), ['payment_id', 'from_user_id', 'from_handle', 'to_user_id', 'to_handle', 'amount', 'currency', 'note', 'visibility', 'request_id', 'settlement_id', 'authorization_id', 'refund_of', 'created_at']);
  assert.deepEqual([r.json.from_handle, r.json.to_handle, r.json.amount, r.json.refund_of, r.json.request_id, r.json.authorization_id, r.json.settlement_id], ['bob', 'ada', 300, p.payment_id, null, null, null]);
  assert.equal(r.json.note, 'dinner 😀'); assert.equal(r.json.visibility, 'private'); assert.notEqual(r.json.payment_id, p.payment_id);
  assert.deepEqual([(await me(t.ada)).balance, (await me(t.bob)).balance], [9300, 3200]);
  // ordinary feed rule, statements, revision 1
  assert.ok((await c.get('/activity', { token: t.ada })).json.payments.some((x) => x.payment_id === r.json.payment_id));
  assert.ok(!(await c.get('/activity', { token: t.cy })).json.payments.some((x) => x.payment_id === r.json.payment_id));
  for (const tok of [t.ada, t.bob]) {
    const s = (await c.get('/statement?limit=200', { token: tok })).json;
    assert.equal(s.entries.filter((e) => e.payment.refund_of === p.payment_id).length, 1);
    assert.equal(s.opening_balance + s.entries.reduce((a, e) => a + e.delta, 0), s.closing_balance);
  }
  const revs = (await c.get(`/payments/${r.json.payment_id}/revisions`, { token: t.ada })).json.revisions;
  assert.equal(revs.length, 1); assert.equal(revs[0].effective_at, r.json.created_at); assert.equal(revs[0].recorded_at, r.json.created_at);
  assert.ok(Date.parse(r.json.created_at) <= Date.now() + 1);
  // the original receipt never changes
  const feed = (await c.get('/activity', { token: t.ada })).json.payments.find((x) => x.payment_id === p.payment_id);
  assert.equal(feed.amount, 1000); assert.equal(feed.refund_of, null);
  // replay / reuse / missing key / long key
  const rep = await refund(t.bob, p.payment_id, { amount: 300 }, key);
  assert.equal(rep.status, 200); assert.equal(rep.text, r.text);
  err(await refund(t.bob, p.payment_id, { amount: 301 }, key), 409, 'idempotency_key_reuse');
  err(await c.post(`/payments/${p.payment_id}/refunds`, { token: t.bob, body: { amount: 1 } }), 400, 'missing_idempotency_key');
  err(await refund(t.bob, p.payment_id, { amount: 1 }, 'x'.repeat(256)), 422, 'validation_failed');
  assert.deepEqual([(await me(t.ada)).balance, (await me(t.bob)).balance], [9300, 3200], 'replays moved nothing');
  assert.equal(await balanceSum(c, all()), 12500);
});

test('BB2-BB5/BB10: rejection table and precedence', async () => {
  await fresh();
  const p = await pay(t.ada, 'bob', 1000);
  const id = p.payment_id;
  err(await c.post(`/payments/${id}/refunds`, { body: { amount: 1 }, key: k() }), 401, 'unauthenticated');
  err(await c.post(`/payments/${id}/refunds`, { token: t.bob, raw: '{', key: k() }), 400, 'malformed_request');
  err(await c.post(`/payments/${id}/refunds`, { token: t.bob, raw: '[1]', key: k() }), 400, 'malformed_request');
  for (const bad of [{}, { amount: 0 }, { amount: -1 }, { amount: 1.5 }, { amount: '5' }, { amount: true }, { amount: null }, { amount: 1000000001 }]) err(await refund(t.bob, id, bad), 422, 'validation_failed');
  err(await c.post(`/payments/${id}/refunds`, { token: t.bob, key: k(), raw: '{"amount":1.0000000000000000000001}' }), 422, 'validation_failed');
  assert.equal((await c.post(`/payments/${id}/refunds`, { token: t.bob, key: k(), raw: '{"amount":1e1}' })).status, 201);
  // 422 amount before 404; 404 before 403; 403 for anyone but the receiver
  err(await refund(t.bob, 'nope', { amount: 0 }), 422, 'validation_failed');
  err(await refund(t.bob, 'nope', { amount: 5 }), 404, 'not_found');
  for (const who of [t.ada, t.cy, t.op]) err(await refund(who, id, { amount: 5 }), 403, 'forbidden');
  // refund of a refund, then the bound, then funds
  const r = (await refund(t.bob, id, { amount: 100 })).json;
  err(await refund(t.ada, r.payment_id, { amount: 1 }), 422, 'invalid_refund_target');
  err(await refund(t.bob, r.payment_id, { amount: 1 }), 403, 'forbidden');
  err(await refund(t.cy, r.payment_id, { amount: 1 }), 403, 'forbidden');
  err(await refund(t.bob, id, { amount: 891 }), 422, 'refund_exceeds_payment'); // 10 + 100 refunded so far
  assert.equal((await refund(t.bob, id, { amount: 890 })).status, 201, 'exactly reaching the amount is allowed');
  err(await refund(t.bob, id, { amount: 1 }), 422, 'refund_exceeds_payment');
  // failed attempts do not claim a key
  const key = k();
  err(await refund(t.bob, id, { amount: 1 }, key), 422, 'refund_exceeds_payment');
  const q = await pay(t.ada, 'bob', 50);
  assert.equal((await refund(t.bob, q.payment_id, { amount: 1 }, key)).status, 201);
  assert.equal(await balanceSum(c, all()), 12500);
});

test('BB5/BC3/BC4: refunds, corrections and the corrected amount bound each other', async () => {
  await fresh();
  const p = await pay(t.ada, 'bob', 1000);
  assert.equal((await correct(t.ada, p.payment_id, goodBody({ amount: 400 }))).status, 201);
  err(await refund(t.bob, p.payment_id, { amount: 401 }), 422, 'refund_exceeds_payment');
  assert.equal((await refund(t.bob, p.payment_id, { amount: 150 })).status, 201);
  err(await correct(t.ada, p.payment_id, goodBody({ expected_revision: 2, amount: 149 })), 422, 'refund_exceeds_payment');
  assert.equal((await correct(t.ada, p.payment_id, goodBody({ expected_revision: 2, amount: 150, reason: 'equal to refunded' }))).status, 201, 'down to exactly the refunded amount is allowed');
  err(await refund(t.bob, p.payment_id, { amount: 1 }), 422, 'refund_exceeds_payment');
  // a payment corrected to 0 cannot be refunded at all
  const z = await pay(t.ada, 'bob', 50);
  await correct(t.ada, z.payment_id, goodBody({ amount: 0 }));
  err(await refund(t.bob, z.payment_id, { amount: 1 }), 422, 'refund_exceeds_payment');
  // refunds cannot be corrected (precedence: linked before stale)
  const r = (await refund(t.bob, (await pay(t.ada, 'bob', 20)).payment_id, { amount: 5 })).json;
  err(await correct(t.bob, r.payment_id, goodBody({ amount: 1 })), 422, 'linked_payment_immutable');
  err(await correct(t.ada, r.payment_id, goodBody({ amount: 1, expected_revision: 9 })), 403, 'forbidden');
  err(await correct(t.bob, r.payment_id, goodBody({ amount: 1, expected_revision: 9 })), 422, 'linked_payment_immutable');
  assert.equal(await balanceSum(c, all()), 12500);
});

test('BB3/BB8: request payments, captures and settlement members are refundable; nothing is reopened', async () => {
  await fresh();
  const rq = (await c.post('/requests', { token: t.bob, key: k(), body: { payer_handle: 'ada', amount: 200 } })).json;
  const rp = (await c.post(`/requests/${rq.request_id}/pay`, { token: t.ada, key: k(), body: {} })).json;
  const rr = await refund(t.bob, rp.payment_id, { amount: 200 });
  assert.equal(rr.status, 201); assert.equal(rr.json.request_id, null);
  const reqs = (await c.get('/requests?limit=200', { token: t.bob })).json.requests.find((x) => x.request_id === rq.request_id);
  assert.equal(reqs.status, 'paid'); assert.equal(reqs.payment_id, rp.payment_id);
  // capture
  const a = (await c.post('/authorizations', { token: t.ada, key: k(), body: { to_handle: 'bob', amount: 1000 } })).json;
  const cap = (await c.post(`/authorizations/${a.authorization_id}/capture`, { token: t.bob, key: k(), body: { amount: 400 } })).json;
  const heldBefore = (await me(t.ada)).held;
  const cr = await refund(t.bob, cap.payment_id, { amount: 100 });
  assert.equal(cr.status, 201); assert.equal(cr.json.authorization_id, null);
  const after = (await c.get('/authorizations?limit=200', { token: t.ada })).json.authorizations.find((x) => x.authorization_id === a.authorization_id);
  assert.equal(after.status, 'captured'); assert.equal(after.captured_amount, 400); assert.equal((await me(t.ada)).held, heldBefore, 'a released hold is not restored');
  // settlement member
  const st = (await c.post('/settlements', { token: t.op, key: k(), body: { transfers: [{ from_handle: 'ada', to_handle: 'cy', amount: 300 }, { from_handle: 'cy', to_handle: 'bob', amount: 50 }] } })).json;
  const sr = await refund(t.cy, st.payments[0].payment_id, { amount: 250 });
  assert.equal(sr.status, 201); assert.equal(sr.json.settlement_id, null);
  const members = (await c.get('/_test/export')).json.state.settlements.find((x) => x.id === st.settlement_id).payment_ids;
  assert.deepEqual(members, st.payments.map((x) => x.payment_id), 'membership unchanged');
  // refunded members are still correctable only through a batch, and the bound applies there too
  err(await correct(t.ada, st.payments[0].payment_id, goodBody({ amount: 1 })), 422, 'linked_payment_immutable');
  assert.equal(await balanceSum(c, all()), 12500);
});

test('BB7: held funds cannot fund a refund', async () => {
  await fresh();
  const p = await pay(t.ada, 'bob', 1000);
  const bal = (await me(t.bob)).balance;
  const hold = (await c.post('/authorizations', { token: t.bob, key: k(), body: { to_handle: 'cy', amount: bal } })).json;
  assert.equal((await me(t.bob)).available, 0);
  const before = JSON.stringify((await c.get('/_test/export')).json.state);
  const key = k();
  err(await refund(t.bob, p.payment_id, { amount: 1 }, key), 409, 'insufficient_funds');
  assert.equal(JSON.stringify((await c.get('/_test/export')).json.state), before, 'nothing changed');
  await c.post(`/authorizations/${hold.authorization_id}/void`, { token: t.bob });
  assert.equal((await refund(t.bob, p.payment_id, { amount: 1 }, key)).status, 201);
});

test('BB11/BB12/BA3: concurrent refunds, conservation, race on one key', async () => {
  await fresh();
  const p = await pay(t.ada, 'bob', 1000);
  const rs = await Promise.all(Array.from({ length: 30 }, () => refund(t.bob, p.payment_id, { amount: 100 })));
  assert.equal(rs.filter((r) => r.status === 201).length, 10);
  assert.ok(rs.filter((r) => r.status !== 201).every((r) => r.status === 422 && r.json.error.code === 'refund_exceeds_payment'));
  const q = await pay(t.ada, 'bob', 500);
  const key = k();
  const same = await Promise.all(Array.from({ length: 20 }, () => refund(t.bob, q.payment_id, { amount: 70 }, key)));
  assert.equal(same.filter((r) => r.status === 201).length, 1); assert.equal(same.filter((r) => r.status === 200).length, 19);
  assert.equal(new Set(same.map((r) => r.text)).size, 1);
  // refund and correction racing for one payment: the bound holds either way
  const z = await pay(t.ada, 'bob', 600);
  const race = await Promise.all([
    ...Array.from({ length: 6 }, () => refund(t.bob, z.payment_id, { amount: 100 })),
    correct(t.ada, z.payment_id, goodBody({ amount: 250 })),
  ]);
  const okRefunds = race.slice(0, 6).filter((r) => r.status === 201).length;
  const corrected = race[6].status === 201;
  const final = (await c.get(`/payments/${z.payment_id}/revisions`, { token: t.ada })).json.revisions.at(-1).amount;
  assert.ok(okRefunds * 100 <= final, `${okRefunds} refunds of 100 against a final amount of ${final}`);
  assert.equal(final, corrected ? 250 : 600);
  for (const as of [Date.now() - 100000, Date.now(), Date.now() + 1000]) {
    let sum = 0;
    for (const tok of all()) sum += (await me(tok, `?as_of=${enc(new Date(as).toISOString())}`)).total;
    assert.equal(sum, 12500);
  }
  assert.equal(await balanceSum(c, all()), 12500);
});

test('BA6: client-now instants, refunds and reads at once', async () => {
  await fresh();
  const p = await pay(t.ada, 'bob', 5000);
  for (let i = 0; i < 100; i++) {
    const r = await refund(t.bob, p.payment_id, { amount: 1 });
    assert.equal(r.status, 201);
    assert.ok(Date.parse(r.json.created_at) <= Date.now() + 1);
    const cur = (await me(t.bob)).balance;
    const s = (await c.get('/statement?limit=1', { token: t.bob })).json;
    assert.equal(s.closing_balance, cur);
    assert.equal((await me(t.bob, `?as_of=${enc(new Date(Date.now() + 1).toISOString())}`)).balance, cur);
  }
});
