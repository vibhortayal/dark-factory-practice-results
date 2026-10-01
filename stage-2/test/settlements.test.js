import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { setup, k, balanceSum } from './helper.js';

let c, t;
before(async () => ({ c, t } = await setup()));
after(() => c.stop());
const err = (r, status, code) => { assert.equal(r.status, status, r.text); assert.equal(r.json.error.code, code); };
const tr = (from_handle, to_handle, amount, extra = {}) => ({ from_handle, to_handle, amount, ...extra });
const settle = (transfers, o = {}) => c.post('/settlements', { token: t.op, key: k(), body: { transfers }, ...o });
const all = () => [t.ada, t.bob, t.cy, t.op];
const bal = async (tok) => (await c.get('/me', { token: tok })).json.balance;

test('J2/J3: access and batch shape', async () => {
  err(await c.post('/settlements', { key: k(), body: {} }), 401, 'unauthenticated');
  err(await c.post('/settlements', { token: t.ada, key: k(), body: { transfers: [tr('ada', 'bob', 1)] } }), 403, 'forbidden');
  for (const bad of [undefined, 'x', {}, [], Array.from({ length: 33 }, () => tr('ada', 'bob', 1)), [1], [null], [[]], ['x']]) {
    err(await c.post('/settlements', { token: t.op, key: k(), body: bad === undefined ? {} : { transfers: bad } }), 422, 'validation_failed');
  }
  assert.equal((await settle([tr('ada', 'bob', 1)])).status, 201);
  assert.equal((await settle(Array.from({ length: 32 }, () => tr('ada', 'bob', 1)))).status, 201);
  err(await c.post('/settlements', { token: t.op, key: k(), raw: '[]' }), 400, 'malformed_request');
});

test('J4/J5: entry rules and ordering', async () => {
  const before = await bal(t.ada);
  const feed = (await c.get('/activity?limit=200', { token: t.ada })).json.payments.length;
  err(await settle([tr('ada', 'bob', 1), { to_handle: 'bob', amount: 1 }]), 422, 'validation_failed');
  err(await settle([tr('ada', 'bob', 1), tr('ada', 'ghost', 1)]), 404, 'not_found');
  err(await settle([tr('ghost', 'bob', 1)]), 404, 'not_found');
  err(await settle([tr('ada', 'ada', 1)]), 422, 'self_payment');
  err(await settle([tr('ada', 'bob', 0)]), 422, 'validation_failed');
  err(await settle([tr('ada', 'bob', 1, { visibility: 'x' })]), 422, 'validation_failed');
  err(await settle([tr('ada', 'bob', 1, { note: 'x'.repeat(201) })]), 422, 'validation_failed');
  err(await settle([tr('ada', 5, 1)]), 400, 'malformed_request');
  // first bad entry wins, and always before insufficient funds
  err(await settle([tr('ada', 'bob', 99999999), tr('cy', 'cy', 5), tr('ada', 'ghost', 1)]), 422, 'self_payment');
  err(await settle([tr('ada', 'bob', 99999999), tr('ada', 'ghost', 1)]), 404, 'not_found');
  err(await settle([tr('ada', 'bob', 99999999)]), 409, 'insufficient_funds');
  assert.equal(await bal(t.ada), before);
  assert.equal((await c.get('/activity?limit=200', { token: t.ada })).json.payments.length, feed);
});

test('J6-J10/J12: net affordability, receipts, visibility', async () => {
  // cy has 0, passes 100 through: ada->cy 100, cy->bob 100
  const key = k();
  const body = { transfers: [tr('ada', 'cy', 100), tr('cy', 'bob', 100, { visibility: 'private', note: 'n' })] };
  const r = await c.post('/settlements', { token: t.op, key, body });
  assert.equal(r.status, 201, r.text);
  assert.deepEqual(Object.keys(r.json), ['settlement_id', 'committed_at', 'payments']);
  assert.equal(r.json.payments.length, 2);
  for (const p of r.json.payments) {
    assert.equal(p.settlement_id, r.json.settlement_id);
    assert.equal(p.request_id, null);
    assert.equal(p.created_at, r.json.committed_at);
  }
  assert.deepEqual(r.json.payments.map((p) => [p.from_handle, p.to_handle, p.visibility, p.note]), [['ada', 'cy', 'public', ''], ['cy', 'bob', 'private', 'n']]);
  assert.equal(await bal(t.cy), 0);
  // ordinary visibility: private member hidden from ada? ada is not a party of it; op not a party
  const ids = (res) => res.json.payments.map((p) => p.payment_id);
  assert.ok(!ids(await c.get('/activity', { token: t.ada })).includes(r.json.payments[1].payment_id));
  assert.ok(!ids(await c.get('/activity', { token: t.op })).includes(r.json.payments[1].payment_id));
  assert.ok(ids(await c.get('/activity', { token: t.op })).includes(r.json.payments[0].payment_id));
  assert.ok(ids(await c.get('/activity', { token: t.cy })).includes(r.json.payments[1].payment_id));
  assert.ok(ids(await c.get('/activity', { token: t.bob })).includes(r.json.payments[1].payment_id));
  // operator gets no access to others' requests
  const rq = await c.post('/requests', { token: t.bob, key: k(), body: { payer_handle: 'ada', amount: 1 } });
  assert.equal((await c.get('/requests', { token: t.op })).json.requests.length, 0);
  err(await c.post(`/requests/${rq.json.request_id}/cancel`, { token: t.op }), 403, 'forbidden');
  // replay, reuse, plain payments expose settlement_id: null
  const rep = await c.post('/settlements', { token: t.op, key, body });
  assert.equal(rep.status, 200); assert.equal(rep.text, r.text);
  err(await c.post('/settlements', { token: t.op, key, body: { transfers: [tr('ada', 'bob', 1)] } }), 409, 'idempotency_key_reuse');
  const pay = await c.post('/payments', { token: t.ada, key: k(), body: { to_handle: 'bob', amount: 1 } });
  assert.equal(pay.json.settlement_id, null);
  // unaffordable net: bob 2500+100, send 3000 through cy who only gets 0
  const sum = await balanceSum(c, all());
  const b = await bal(t.bob);
  err(await settle([tr('bob', 'cy', b + 1)]), 409, 'insufficient_funds');
  err(await settle([tr('ada', 'cy', 50), tr('cy', 'bob', 60)]), 409, 'insufficient_funds');
  assert.equal(await balanceSum(c, all()), sum);
  // failure claims no key
  const k2 = k();
  err(await c.post('/settlements', { token: t.op, key: k2, body: { transfers: [tr('cy', 'bob', 5)] } }), 409, 'insufficient_funds');
  assert.equal((await c.post('/settlements', { token: t.op, key: k2, body: { transfers: [tr('bob', 'cy', 5)] } })).status, 201);
  // operator as a party; round robin cycle where everyone passes through
  const cyc = await settle([tr('op', 'ada', 1)]);
  err(cyc, 409, 'insufficient_funds');
  assert.equal((await settle([tr('ada', 'op', 5), tr('op', 'bob', 5)])).status, 201);
  // feed visibility of a settlement payment with ordinary payments listing
  assert.equal(await balanceSum(c, all()), sum);
});
