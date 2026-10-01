import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { setup, k, balanceSum } from './helper.js';

let c, t;
before(async () => ({ c, t } = await setup()));
after(() => c.stop());
const err = (r, status, code) => { assert.equal(r.status, status, r.text); assert.equal(r.json.error.code, code); };
const all = () => [t.ada, t.bob, t.cy, t.op];

// One request per idempotent path; `again` is a different valid body.
const paths = () => [
  ['/payments', t.ada, { to_handle: 'bob', amount: 10 }, { to_handle: 'bob', amount: 11 }],
  ['/requests', t.bob, { payer_handle: 'ada', amount: 10 }, { payer_handle: 'ada', amount: 11 }],
  ['/splits', t.ada, { amount: 10, participant_handles: ['bob', 'cy'] }, { amount: 11, participant_handles: ['bob', 'cy'] }],
  ['/settlements', t.op, { transfers: [{ from_handle: 'ada', to_handle: 'bob', amount: 10 }] }, { transfers: [{ from_handle: 'ada', to_handle: 'bob', amount: 11 }] }],
];

test('F1-F5/D5/D6: every path', async () => {
  for (const [path, tok, body, other] of paths()) {
    err(await c.post(path, { token: tok, body }), 400, 'missing_idempotency_key');
    err(await c.post(path, { token: tok, body, key: '' }), 400, 'missing_idempotency_key');
    err(await c.post(path, { token: tok, body, key: 'x'.repeat(256) }), 422, 'validation_failed');
    err(await c.post(path, { token: tok, body, key: 'x'.repeat(10000) }), 422, 'validation_failed');
    assert.equal((await c.post(path, { token: tok, body: {}, key: 'x'.repeat(255) })).status === 201, false);
    const key = k();
    const a = await c.post(path, { token: tok, body, key });
    assert.equal(a.status, 201, a.text);
    const b = await c.post(path, { token: tok, body, key });
    assert.equal(b.status, 200);
    assert.equal(b.text, a.text);
    // key order / whitespace / number spelling irrelevant
    const reordered = await c.post(path, { token: tok, key, raw: ' ' + JSON.stringify(body).replace(/(\d+)(?=[},])/g, '$1.0').split('').join('') });
    assert.equal(reordered.status, 200);
    assert.deepEqual(reordered.json, a.json);
    err(await c.post(path, { token: tok, body: other, key }), 409, 'idempotency_key_reuse');
    err(await c.post(path, { token: tok, body: { nonsense: 1 }, key }), 409, 'idempotency_key_reuse');
    err(await c.post(path, { token: tok, body: { ...body, extra: 1 }, key }), 409, 'idempotency_key_reuse');
    // failed request does not claim the key
    const key2 = k();
    err(await c.post(path, { token: tok, body: {}, key: key2 }), 422, 'validation_failed');
    assert.equal((await c.post(path, { token: tok, body, key: key2 })).status, 201);
  }
});

test('F4: key scoped to user', async () => {
  const key = k();
  const a = await c.post('/requests', { token: t.bob, key, body: { payer_handle: 'ada', amount: 1 } });
  const b = await c.post('/requests', { token: t.cy, key, body: { payer_handle: 'ada', amount: 1 } });
  assert.equal(a.status, 201); assert.equal(b.status, 201);
  assert.notEqual(a.json.request_id, b.json.request_id);
});

test('F5: same key, different path is a new request', async () => {
  const key = k();
  const r1 = (await c.post('/requests', { token: t.bob, key: k(), body: { payer_handle: 'ada', amount: 20 } })).json.request_id;
  const r2 = (await c.post('/requests', { token: t.bob, key: k(), body: { payer_handle: 'ada', amount: 20 } })).json.request_id;
  const a = await c.post(`/requests/${r1}/pay`, { token: t.ada, key, body: {} });
  const b = await c.post(`/requests/${r2}/pay`, { token: t.ada, key, body: {} });
  assert.equal(a.status, 201); assert.equal(b.status, 201);
  const p = await c.post('/payments', { token: t.ada, key, body: { to_handle: 'bob', amount: 20 } });
  assert.equal(p.status, 201);
  const q = await c.post('/requests', { token: t.ada, key, body: { payer_handle: 'bob', amount: 20 } });
  assert.equal(q.status, 201);
});

test('F8/F9/F3: replay returns original after resource change; {} vs visibility', async () => {
  const rq = (await c.post('/requests', { token: t.bob, key: k(), body: { payer_handle: 'ada', amount: 7 } })).json;
  const key = k();
  const first = await c.post(`/requests/${rq.request_id}/pay`, { token: t.ada, key, body: {} });
  assert.equal(first.status, 201);
  const bal = (await c.get('/me', { token: t.ada })).json.balance;
  const again = await c.post(`/requests/${rq.request_id}/pay`, { token: t.ada, key, body: {} });
  assert.equal(again.status, 200); assert.equal(again.text, first.text);
  assert.equal((await c.get('/me', { token: t.ada })).json.balance, bal);
  err(await c.post(`/requests/${rq.request_id}/pay`, { token: t.ada, key, body: { visibility: 'public' } }), 409, 'idempotency_key_reuse');
  // fresh key on a paid request
  err(await c.post(`/requests/${rq.request_id}/pay`, { token: t.ada, key: k(), body: {} }), 409, 'request_not_pending');
  // replay of a created request after it was cancelled
  const k2 = k();
  const created = await c.post('/requests', { token: t.bob, key: k2, body: { payer_handle: 'ada', amount: 3 } });
  await c.post(`/requests/${created.json.request_id}/cancel`, { token: t.bob });
  const rep = await c.post('/requests', { token: t.bob, key: k2, body: { payer_handle: 'ada', amount: 3 } });
  assert.equal(rep.status, 200); assert.equal(rep.json.status, 'pending');
  // replay after the balance dropped below the amount still returns the original
  const k3 = k();
  const bal2 = (await c.get('/me', { token: t.cy })).json.balance;
  await c.post('/payments', { token: t.ada, key: k(), body: { to_handle: 'cy', amount: 5 } });
  const pk = k();
  assert.equal((await c.post('/payments', { token: t.cy, key: pk, body: { to_handle: 'bob', amount: bal2 + 5 } })).status, 201);
  const rp = await c.post('/payments', { token: t.cy, key: pk, body: { to_handle: 'bob', amount: bal2 + 5 } });
  assert.equal(rp.status, 200); void k3;
});

test('D10: precedence on idempotent writes', async () => {
  // 401 before everything, 400 key before body parse, parse before key resolution
  err(await c.post('/payments', { raw: '{' }), 401, 'unauthenticated');
  err(await c.post('/payments', { token: t.ada, raw: '{' }), 400, 'missing_idempotency_key');
  err(await c.post('/payments', { token: t.ada, key: k(), raw: '{' }), 400, 'malformed_request');
  err(await c.post('/payments', { token: t.ada, key: k(), raw: '[1]' }), 400, 'malformed_request');
  err(await c.post('/payments', { token: t.ada, key: k(), raw: '' }), 400, 'malformed_request');
  // amount wrong type (422) vs handle wrong type (400): types first
  err(await c.post('/payments', { token: t.ada, key: k(), body: { to_handle: 5, amount: 'x' } }), 400, 'malformed_request');
  // self_payment precedes unknown-handle and balance
  err(await c.post('/payments', { token: t.cy, key: k(), body: { to_handle: 'cy', amount: 5 } }), 422, 'self_payment');
  // 404 precedes insufficient funds
  err(await c.post('/payments', { token: t.cy, key: k(), body: { to_handle: 'ghost', amount: 5000000 } }), 404, 'not_found');
  // settlements: 403 for non-operator even without key
  err(await c.post('/settlements', { token: t.ada, body: {} }), 403, 'forbidden');
  err(await c.post('/settlements', { raw: '{}' }), 401, 'unauthenticated');
  err(await c.post('/settlements', { token: t.op, body: { transfers: [] } }), 400, 'missing_idempotency_key');
  // pay on someone else's request with unknown id: 404 first
  err(await c.post('/requests/none/pay', { token: t.cy, key: k(), body: {} }), 404, 'not_found');
  assert.equal(await balanceSum(c, all()), 12500);
});
