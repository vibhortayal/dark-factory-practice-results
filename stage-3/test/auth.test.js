import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { startServer, FX, k, login, balanceSum } from './helper.js';

let c, t;
const err = (r, status, code) => { assert.equal(r.status, status, r.text); assert.equal(r.json.error.code, code); };
const iso = (deltaSec) => new Date(Date.now() + deltaSec * 1000).toISOString().replace('Z', '+00:00');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const me = async (tok) => (await c.get('/me', { token: tok })).json;
const create = (tok, body, key = k()) => c.post('/authorizations', { token: tok, key, body });
const capture = (tok, id, body, key = k()) => c.post(`/authorizations/${id}/capture`, { token: tok, key, body });
const all = () => [t.ada, t.bob, t.cy, t.op];

async function fresh(extra = {}) {
  assert.equal((await c.reset(FX(extra))).status, 204);
  t = {};
  for (const n of ['ada', 'bob', 'cy', 'op']) t[n] = await login(c, `${n}@example.com`);
}
before(async () => { c = await startServer(); await fresh(); });
after(() => c.stop());

const RFC = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}\+00:00$/;

test('T3/T8/T14: /me fields with seeded holds; seeded values returned verbatim', async () => {
  await fresh({ authorizations: [
    { id: 'a_1', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 2000, note: 'deposit', visibility: 'public', status: 'open', expires_at: iso(7200) },
    { id: 'a_old', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 9000, status: 'open', expires_at: iso(-7200) },
    { id: 'a_cap', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 9000, status: 'captured', expires_at: '2030-01-01T00:00:00.123456789Z' },
    { id: 'a_void', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 9000, status: 'voided', expires_at: '2030-01-01T05:00:00+05:00' },
  ] });
  assert.deepEqual(await me(t.ada), { user_id: 'u_ada', display_name: 'Ada', handle: 'ada', balance: 10000, total: 10000, available: 8000, held: 2000, currency: 'EUR', minor_units: 2 });
  assert.deepEqual(Object.keys(await me(t.bob)).sort(), ['available', 'balance', 'currency', 'display_name', 'handle', 'held', 'minor_units', 'total', 'user_id']);
  const list = (await c.get('/authorizations?limit=200', { token: t.ada })).json.authorizations;
  const byId = Object.fromEntries(list.map((a) => [a.authorization_id, a]));
  assert.equal(byId.a_old.status, 'expired'); assert.equal(byId.a_old.remaining_amount, 0);
  assert.equal(byId.a_cap.expires_at, '2030-01-01T00:00:00.123456789Z');
  assert.equal(byId.a_cap.captured_amount, 9000);
  assert.equal(byId.a_void.expires_at, '2030-01-01T05:00:00+05:00');
  assert.equal(byId.a_1.remaining_amount, 2000); assert.deepEqual(byId.a_1.payment_ids, []);
  assert.deepEqual(Object.keys(byId.a_1), ['authorization_id', 'from_user_id', 'from_handle', 'to_user_id', 'to_handle', 'amount', 'captured_amount', 'remaining_amount', 'currency', 'note', 'visibility', 'status', 'expires_at', 'payment_id', 'payment_ids', 'created_at', 'closed_at']);
});

test('T1/T4/T5: fixture rules for ttl and authorizations', async () => {
  await fresh();
  const tok = t.ada;
  const base = { id: 'a', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 100, status: 'open', expires_at: iso(7200) };
  const bad = [
    { authorization_ttl_seconds: 0 }, { authorization_ttl_seconds: -1 }, { authorization_ttl_seconds: 1.5 }, { authorization_ttl_seconds: '5' }, { authorization_ttl_seconds: null }, { authorization_ttl_seconds: true },
    { authorizations: [{ ...base, amount: 10001 }] },
    { authorizations: [{ ...base, amount: 6000 }, { ...base, id: 'b', amount: 6000 }] },
    { authorizations: [{ ...base, from_user_id: 'ghost' }] }, { authorizations: [{ ...base, to_user_id: 'u_ada' }] },
    { authorizations: [{ ...base, amount: 0 }] }, { authorizations: [{ ...base, amount: 1.5 }] }, { authorizations: [{ ...base, status: 'weird' }] },
    { authorizations: [{ ...base, visibility: 'x' }] }, { authorizations: [{ ...base, expires_at: 'tomorrow' }] }, { authorizations: [base, base] }, { authorizations: 'x' },
  ];
  for (const extra of bad) {
    err(await c.reset(FX(extra)), 422, 'validation_failed');
    assert.equal((await c.get('/me', { token: tok })).status, 200, 'failed reset changes nothing');
  }
  // expired holds do not count toward the cap; the sum may equal the balance
  assert.equal((await c.reset(FX({ authorizations: [{ ...base, amount: 10000 }, { ...base, id: 'x', amount: 99999, expires_at: iso(-4000) }] }))).status, 204);
  assert.equal((await c.reset(FX({ authorization_ttl_seconds: 5 }))).status, 204);
  assert.equal((await c.reset(FX())).status, 204);
  // seeded defaults
  await fresh({ authorizations: [{ ...base, status: 'captured' }] });
  const a = (await c.get('/authorizations', { token: t.ada })).json.authorizations[0];
  assert.equal(a.note, ''); assert.equal(a.visibility, 'public'); assert.equal(a.captured_amount, 100); assert.match(a.created_at, RFC);
});

test('U1-U3/T13: create', async () => {
  await fresh();
  const r = await create(t.ada, { to_handle: 'bob', amount: 2000, note: 'deposit', visibility: 'private' });
  assert.equal(r.status, 201, r.text);
  const a = r.json;
  assert.match(a.authorization_id, /\S/);
  assert.equal(a.captured_amount, 0); assert.equal(a.remaining_amount, 2000); assert.equal(a.status, 'open');
  assert.equal(a.payment_id, null); assert.deepEqual(a.payment_ids, []); assert.equal(a.visibility, 'private'); assert.equal(a.currency, 'EUR');
  assert.match(a.created_at, RFC); assert.match(a.expires_at, RFC);
  assert.equal(Date.parse(a.expires_at) - Date.parse(a.created_at), 600000);
  assert.deepEqual(Object.keys(a), ['authorization_id', 'from_user_id', 'from_handle', 'to_user_id', 'to_handle', 'amount', 'captured_amount', 'remaining_amount', 'currency', 'note', 'visibility', 'status', 'expires_at', 'payment_id', 'payment_ids', 'created_at', 'closed_at']);
  assert.deepEqual(await me(t.ada), { user_id: 'u_ada', display_name: 'Ada', handle: 'ada', balance: 10000, total: 10000, available: 8000, held: 2000, currency: 'EUR', minor_units: 2 });
  assert.equal((await me(t.bob)).available, 2500);
  assert.equal((await c.get('/activity', { token: t.ada })).json.payments.length, 0);
  const d = await create(t.ada, { to_handle: 'bob', amount: 1 });
  assert.equal(d.json.note, ''); assert.equal(d.json.visibility, 'public');
  const bad = async (body, st, code) => err(await create(t.ada, body), st, code);
  await bad({ to_handle: 'bob', amount: 8000 }, 409, 'insufficient_funds'); // available is 7999
  assert.equal((await create(t.ada, { to_handle: 'bob', amount: 7999 })).status, 201);
  for (const amt of [0, -1, 1000000001, 1.5, '5', true, null]) await bad({ to_handle: 'bob', amount: amt }, 422, 'validation_failed');
  await bad({ to_handle: 'bob' }, 422, 'validation_failed');
  await bad({ to_handle: 'ada', amount: 1 }, 422, 'self_payment');
  await bad({ to_handle: 'ghost', amount: 1 }, 404, 'not_found');
  await bad({ to_handle: 5, amount: 1 }, 400, 'malformed_request');
  await bad({ to_handle: 'bob', amount: 1, note: 'x'.repeat(201) }, 422, 'validation_failed');
  await bad({ to_handle: 'bob', amount: 1, visibility: 'x' }, 422, 'validation_failed');
  await bad({ to_handle: 'bob', amount: 1, note: null }, 422, 'validation_failed');
  err(await c.post('/authorizations', { token: t.ada, body: { to_handle: 'bob', amount: 1 } }), 400, 'missing_idempotency_key');
  err(await c.post('/authorizations', { token: t.ada, key: 'x'.repeat(256), body: { to_handle: 'bob', amount: 1 } }), 422, 'validation_failed');
  err(await c.post('/authorizations', { body: {}, key: k() }), 401, 'unauthenticated');
  assert.equal(await balanceSum(c, all()), 12500);
});

test('T11: replay, reuse and concurrent identical on the two new paths', async () => {
  await fresh();
  const key = k();
  const body = { to_handle: 'bob', amount: 100 };
  const a = await create(t.ada, body, key);
  const b = await create(t.ada, body, key);
  assert.equal(b.status, 200); assert.equal(b.text, a.text);
  err(await create(t.ada, { to_handle: 'bob', amount: 101 }, key), 409, 'idempotency_key_reuse');
  err(await create(t.ada, { to_handle: 'bob', amount: 'x' }, key), 409, 'idempotency_key_reuse');
  assert.equal((await create(t.bob, { to_handle: 'ada', amount: 100 }, key)).status, 201, 'key is per user');
  const ck = k();
  const first = await capture(t.bob, a.json.authorization_id, { amount: 40, final: false }, ck);
  assert.equal(first.status, 201);
  const again = await capture(t.bob, a.json.authorization_id, { amount: 40, final: false }, ck);
  assert.equal(again.status, 200); assert.equal(again.text, first.text);
  assert.equal((await me(t.bob)).total, 2540, 'replay moved nothing');
  err(await capture(t.bob, a.json.authorization_id, { amount: 40 }, ck), 409, 'idempotency_key_reuse');
  err(await capture(t.bob, a.json.authorization_id, { amount: 40, final: true }, ck), 409, 'idempotency_key_reuse');
  err(await capture(t.bob, a.json.authorization_id, { amount: 41, final: false }, ck), 409, 'idempotency_key_reuse');
  err(await c.post(`/authorizations/${a.json.authorization_id}/capture`, { token: t.bob, body: {} }), 400, 'missing_idempotency_key');
  // same key on another path is a new request
  const other = await create(t.ada, { to_handle: 'bob', amount: 5 });
  assert.equal((await capture(t.bob, other.json.authorization_id, { amount: 5 }, ck)).status, 201);
  // {} and {amount: N} are different bodies; empty body is {}
  const x = await create(t.ada, { to_handle: 'cy', amount: 50 });
  const xk = k();
  assert.equal((await capture(t.cy, x.json.authorization_id, {}, xk)).status, 201);
  err(await capture(t.cy, x.json.authorization_id, { amount: 50 }, xk), 409, 'idempotency_key_reuse');
  assert.equal((await c.post(`/authorizations/${x.json.authorization_id}/capture`, { token: t.cy, key: xk, raw: '' })).status, 200);
  // failed first use does not claim the key
  const y = await create(t.ada, { to_handle: 'cy', amount: 50 });
  const yk = k();
  err(await capture(t.cy, y.json.authorization_id, { amount: 51 }, yk), 422, 'capture_exceeds_authorization');
  assert.equal((await capture(t.cy, y.json.authorization_id, { amount: 50 }, yk)).status, 201);
});

test('U4-U10: capture semantics', async () => {
  await fresh();
  const a = (await create(t.ada, { to_handle: 'bob', amount: 2000, note: 'dep', visibility: 'private' })).json;
  const id = a.authorization_id;
  const p = await capture(t.bob, id, { amount: 1500 });
  assert.equal(p.status, 201, p.text);
  assert.deepEqual(Object.keys(p.json), ['payment_id', 'from_user_id', 'from_handle', 'to_user_id', 'to_handle', 'amount', 'currency', 'note', 'visibility', 'request_id', 'settlement_id', 'authorization_id', 'created_at']);
  assert.equal(p.json.amount, 1500); assert.equal(p.json.authorization_id, id); assert.equal(p.json.request_id, null); assert.equal(p.json.settlement_id, null);
  assert.equal(p.json.note, 'dep'); assert.equal(p.json.visibility, 'private'); assert.equal(p.json.from_handle, 'ada'); assert.equal(p.json.to_handle, 'bob');
  assert.equal(p.json.created_at.length, 29);
  // remainder released in the same step; totals moved
  assert.deepEqual([(await me(t.ada)).total, (await me(t.ada)).available, (await me(t.ada)).held], [8500, 8500, 0]);
  assert.equal((await me(t.bob)).total, 4000);
  const got = (await c.get('/authorizations?direction=outgoing', { token: t.ada })).json.authorizations[0];
  assert.equal(got.status, 'captured'); assert.equal(got.captured_amount, 1500); assert.equal(got.payment_id, p.json.payment_id); assert.deepEqual(got.payment_ids, [p.json.payment_id]); assert.equal(got.remaining_amount, 0);
  // visible in the feed by the ordinary rule: private -> parties only
  assert.ok((await c.get('/activity', { token: t.bob })).json.payments.some((x) => x.payment_id === p.json.payment_id));
  assert.ok(!(await c.get('/activity', { token: t.cy })).json.payments.some((x) => x.payment_id === p.json.payment_id));
  err(await capture(t.bob, id, { amount: 1 }), 409, 'authorization_not_open');
  err(await capture(t.bob, id, {}), 409, 'authorization_not_open');
  // extended mode
  const b = (await create(t.ada, { to_handle: 'bob', amount: 1000 })).json;
  const c1 = await capture(t.bob, b.authorization_id, { amount: 300, final: false });
  assert.equal(c1.status, 201);
  let cur = (await c.get('/authorizations?status=open', { token: t.ada })).json.authorizations[0];
  assert.deepEqual([cur.status, cur.captured_amount, cur.remaining_amount, cur.payment_id], ['open', 300, 700, c1.json.payment_id]);
  assert.equal((await me(t.ada)).held, 700);
  err(await capture(t.bob, b.authorization_id, { amount: 701, final: false }), 422, 'capture_exceeds_authorization');
  const c2 = await capture(t.bob, b.authorization_id, { amount: 200, final: false });
  assert.equal(c2.status, 201);
  const c3 = await capture(t.bob, b.authorization_id, { final: false }); // whole remainder closes it
  assert.equal(c3.json.amount, 500);
  cur = (await c.get('/authorizations?status=captured&limit=1', { token: t.ada })).json.authorizations[0];
  assert.deepEqual([cur.status, cur.captured_amount, cur.remaining_amount, cur.payment_id], ['captured', 1000, 0, c3.json.payment_id]);
  assert.deepEqual(cur.payment_ids, [c1.json.payment_id, c2.json.payment_id, c3.json.payment_id]);
  // final capture releases the rest
  const d = (await create(t.ada, { to_handle: 'bob', amount: 1000 })).json;
  await capture(t.bob, d.authorization_id, { amount: 100, final: false });
  assert.equal((await me(t.ada)).held, 900);
  await capture(t.bob, d.authorization_id, { amount: 100, final: true });
  assert.equal((await me(t.ada)).held, 0);
  // U10: capture works with available 0
  await fresh();
  const all0 = (await create(t.ada, { to_handle: 'bob', amount: 10000 })).json;
  assert.equal((await me(t.ada)).available, 0);
  err(await c.post('/payments', { token: t.ada, key: k(), body: { to_handle: 'bob', amount: 1 } }), 409, 'insufficient_funds');
  assert.equal((await capture(t.bob, all0.authorization_id, { amount: 10000 })).status, 201);
  assert.deepEqual([(await me(t.ada)).total, (await me(t.bob)).total], [0, 12500]);
  assert.equal(await balanceSum(c, all()), 12500);
});

test('U7/U8: capture rejections and precedence', async () => {
  await fresh();
  const a = (await create(t.ada, { to_handle: 'bob', amount: 100 })).json.authorization_id;
  err(await capture(t.ada, a, { amount: 1 }), 403, 'forbidden');
  err(await capture(t.cy, a, { amount: 1 }), 403, 'forbidden');
  err(await capture(t.op, a, {}), 403, 'forbidden');
  err(await capture(t.bob, 'nope', { amount: 1 }), 404, 'not_found');
  for (const amt of [0, -5, 1.5, '5', true, null]) err(await capture(t.bob, a, { amount: amt }), 422, 'validation_failed');
  err(await capture(t.bob, a, { amount: 1, final: 'yes' }), 400, 'malformed_request');
  err(await capture(t.bob, a, { amount: 1, final: null }), 400, 'malformed_request');
  err(await capture(t.bob, a, { amount: 'x', final: 1 }), 400, 'malformed_request');
  err(await capture(t.bob, a, { amount: 101 }), 422, 'capture_exceeds_authorization');
  err(await c.post(`/authorizations/${a}/capture`, { token: t.bob, key: k(), raw: '[1]' }), 400, 'malformed_request');
  // validation before 404/403; 404 before 403 before state
  err(await capture(t.cy, 'nope', { amount: 0 }), 422, 'validation_failed');
  assert.equal((await capture(t.bob, a, { amount: 100 })).status, 201);
  err(await capture(t.bob, a, { amount: 5000 }), 409, 'authorization_not_open'); // state before exceeds
  // voided is "not open"
  const v = (await create(t.ada, { to_handle: 'bob', amount: 100 })).json.authorization_id;
  await c.post(`/authorizations/${v}/void`, { token: t.ada });
  err(await capture(t.bob, v, { amount: 5000 }), 409, 'authorization_not_open');
});

test('U12: void', async () => {
  await fresh();
  const a = (await create(t.ada, { to_handle: 'bob', amount: 1000 })).json.authorization_id;
  err(await c.post(`/authorizations/${a}/void`, { token: t.bob }), 403, 'forbidden');
  err(await c.post(`/authorizations/${a}/void`, { token: t.cy }), 403, 'forbidden');
  err(await c.post(`/authorizations/${a}/void`, { token: t.op }), 403, 'forbidden');
  err(await c.post(`/authorizations/nope/void`, { token: t.ada }), 404, 'not_found');
  err(await c.post(`/authorizations/${a}/void`, {}), 401, 'unauthenticated');
  await capture(t.bob, a, { amount: 300, final: false });
  assert.equal((await me(t.ada)).held, 700);
  const r = await c.post(`/authorizations/${a}/void`, { token: t.ada, key: 'ignored' });
  assert.equal(r.status, 200);
  assert.deepEqual([r.json.status, r.json.captured_amount, r.json.remaining_amount, r.json.payment_ids.length], ['voided', 300, 0, 1]);
  assert.deepEqual([(await me(t.ada)).held, (await me(t.ada)).available, (await me(t.ada)).total], [0, 9700, 9700]);
  assert.equal((await c.post(`/authorizations/${a}/void`, { token: t.ada })).status, 200);
  err(await capture(t.bob, a, { amount: 1 }), 409, 'authorization_not_open');
  const b = (await create(t.ada, { to_handle: 'bob', amount: 5 })).json.authorization_id;
  await capture(t.bob, b, {});
  err(await c.post(`/authorizations/${b}/void`, { token: t.ada }), 409, 'authorization_not_open');
  // T14: void instant recorded internally, never in a response
  const ex = (await c.get('/_test/export')).json.state.authorizations.find((x) => x.authorization_id === a);
  assert.match(ex.voided_at, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}\+00:00$/);
  await sleep(20);
  await c.post(`/authorizations/${a}/void`, { token: t.ada });
  assert.equal((await c.get('/_test/export')).json.state.authorizations.find((x) => x.authorization_id === a).voided_at, ex.voided_at, 'repeat void keeps the first instant');
  assert.ok(!('voided_at' in r.json)); assert.equal(r.json.closed_at, ex.voided_at);
  assert.equal(await balanceSum(c, all()), 12500);
});

test('T6/U13/T13: expiry by the clock', async () => {
  await fresh({ authorization_ttl_seconds: 1 });
  // created and captured/voided right away must succeed; still open at 0.4 s
  const quick = (await create(t.ada, { to_handle: 'bob', amount: 100 })).json;
  assert.equal(Date.parse(quick.expires_at) - Date.parse(quick.created_at), 1000);
  assert.equal((await capture(t.bob, quick.authorization_id, { amount: 100 })).status, 201);
  const a = (await create(t.ada, { to_handle: 'bob', amount: 1000 })).json;
  const partial = (await create(t.ada, { to_handle: 'bob', amount: 500 })).json;
  assert.equal((await capture(t.bob, partial.authorization_id, { amount: 100, final: false })).status, 201);
  assert.equal((await me(t.ada)).held, 1400);
  await sleep(400);
  assert.equal((await c.get('/authorizations?status=open', { token: t.ada })).json.authorizations.length, 2);
  const wait = Date.parse(a.expires_at) - Date.now() + 80;
  await sleep(Math.max(wait, 0));
  const list = (await c.get('/authorizations?limit=200', { token: t.ada })).json.authorizations;
  assert.ok(list.every((x) => x.status !== 'open'));
  assert.equal((await c.get('/authorizations?status=open', { token: t.ada })).json.authorizations.length, 0);
  assert.equal((await c.get('/authorizations?status=expired', { token: t.ada })).json.authorizations.length, 2);
  assert.deepEqual([(await me(t.ada)).held, (await me(t.ada)).available, (await me(t.ada)).total], [0, 9800, 9800]);
  const p = list.find((x) => x.authorization_id === partial.authorization_id);
  assert.deepEqual([p.status, p.captured_amount, p.remaining_amount, p.payment_ids.length], ['expired', 100, 0, 1]);
  err(await capture(t.bob, a.authorization_id, { amount: 1 }), 409, 'authorization_expired');
  err(await capture(t.bob, a.authorization_id, { amount: 99999 }), 409, 'authorization_expired');
  err(await c.post(`/authorizations/${a.authorization_id}/void`, { token: t.ada }), 409, 'authorization_not_open');
  // released funds are spendable
  assert.equal((await c.post('/payments', { token: t.ada, key: k(), body: { to_handle: 'cy', amount: 9800 } })).status, 201);
  assert.equal(await balanceSum(c, all()), 12500);
  // timestamps of other records carry milliseconds too (T13)
  const pay = (await c.post('/payments', { token: t.bob, key: k(), body: { to_handle: 'cy', amount: 1 } })).json;
  assert.match(pay.created_at, RFC);
  const rq = (await c.post('/requests', { token: t.bob, key: k(), body: { payer_handle: 'cy', amount: 1 } })).json;
  assert.match(rq.created_at, RFC);
});

test('T9/T10: holds do not fund payments, request pay, settlements; payments stay immediate', async () => {
  await fresh();
  await create(t.ada, { to_handle: 'bob', amount: 9000 });
  const bad = async (r) => err(r, 409, 'insufficient_funds');
  await bad(await c.post('/payments', { token: t.ada, key: k(), body: { to_handle: 'cy', amount: 1001 } }));
  assert.equal((await c.post('/payments', { token: t.ada, key: k(), body: { to_handle: 'cy', amount: 1000 } })).status, 201);
  const rq = (await c.post('/requests', { token: t.cy, key: k(), body: { payer_handle: 'ada', amount: 1 } })).json;
  await bad(await c.post(`/requests/${rq.request_id}/pay`, { token: t.ada, key: k(), body: {} }));
  await bad(await create(t.ada, { to_handle: 'cy', amount: 1 }));
  await bad(await c.post('/settlements', { token: t.op, key: k(), body: { transfers: [{ from_handle: 'ada', to_handle: 'bob', amount: 1 }] } }));
  // net settlement credit lets a held wallet pass money through
  assert.equal((await c.post('/settlements', { token: t.op, key: k(), body: { transfers: [{ from_handle: 'bob', to_handle: 'ada', amount: 100 }, { from_handle: 'ada', to_handle: 'cy', amount: 100 }] } })).status, 201);
  // /payments leaves no authorization behind
  const before = (await c.get('/authorizations?limit=200', { token: t.ada })).json.authorizations.length;
  await c.post('/payments', { token: t.bob, key: k(), body: { to_handle: 'ada', amount: 5 } });
  assert.equal((await c.get('/authorizations?limit=200', { token: t.ada })).json.authorizations.length, before);
  assert.equal(await balanceSum(c, all()), 12500);
});

test('U14/U17: list filters, paging, access', async () => {
  await fresh();
  const ids = [];
  for (let i = 1; i <= 4; i++) ids.push((await create(t.ada, { to_handle: i % 2 ? 'bob' : 'cy', amount: i })).json.authorization_id);
  await capture(t.bob, ids[0], {});
  await c.post(`/authorizations/${ids[1]}/void`, { token: t.ada });
  const q = async (tok, qs) => (await c.get('/authorizations' + qs, { token: tok })).json.authorizations.map((a) => a.authorization_id);
  assert.deepEqual(await q(t.ada, ''), [...ids].reverse());
  assert.deepEqual(await q(t.bob, ''), [ids[2], ids[0]]);
  assert.deepEqual(await q(t.bob, '?direction=incoming'), [ids[2], ids[0]]);
  assert.deepEqual(await q(t.bob, '?direction=outgoing'), []);
  assert.deepEqual(await q(t.ada, '?direction=outgoing&status=open'), [ids[3], ids[2]]);
  assert.deepEqual(await q(t.ada, '?status=captured'), [ids[0]]);
  assert.deepEqual(await q(t.ada, '?status=voided'), [ids[1]]);
  assert.deepEqual(await q(t.op, ''), []);
  const pg = await c.get('/authorizations?limit=2&offset=1', { token: t.ada });
  assert.equal(pg.json.authorizations.length, 2); assert.equal(pg.json.has_more, true);
  assert.equal((await c.get('/authorizations?offset=99', { token: t.ada })).json.has_more, false);
  for (const s of ['limit=0', 'limit=201', 'limit=1e1', 'offset=-1', 'direction=x', 'status=x', 'limit=+4']) err(await c.get('/authorizations?' + s, { token: t.ada }), 422, 'validation_failed');
  err(await c.get('/authorizations'), 401, 'unauthenticated');
  assert.equal((await c.get('/authorizations?foo=1', { token: t.ada })).status, 200);
});

test('X1/U11/T11: concurrency', async () => {
  await fresh();
  const total = 12500;
  // identical creates race once
  const key = k();
  const rs = await Promise.all(Array.from({ length: 20 }, () => create(t.ada, { to_handle: 'bob', amount: 100 }, key)));
  assert.equal(rs.filter((r) => r.status === 201).length, 1); assert.equal(rs.filter((r) => r.status === 200).length, 19);
  assert.equal((await me(t.ada)).held, 100);
  // final/final race on one authorization, different keys
  const a = (await create(t.ada, { to_handle: 'bob', amount: 500 })).json.authorization_id;
  const fin = await Promise.all(Array.from({ length: 20 }, () => capture(t.bob, a, { amount: 500 })));
  assert.equal(fin.filter((r) => r.status === 201).length, 1);
  assert.ok(fin.filter((r) => r.status !== 201).every((r) => r.status === 409 && r.json.error.code === 'authorization_not_open'));
  // partial captures never exceed the authorization
  const b = (await create(t.ada, { to_handle: 'bob', amount: 1000 })).json.authorization_id;
  const parts = await Promise.all(Array.from({ length: 30 }, () => capture(t.bob, b, { amount: 70, final: false })));
  const okN = parts.filter((r) => r.status === 201).length;
  assert.equal(okN, 14);
  assert.ok(parts.filter((r) => r.status !== 201).every((r) => r.status === 422 || r.status === 409));
  const got = (await c.get('/authorizations?limit=200&direction=outgoing', { token: t.ada })).json.authorizations.find((x) => x.authorization_id === b);
  assert.equal(got.captured_amount, 980); assert.equal(got.remaining_amount, 20);
  // capture vs void race
  const d = (await create(t.ada, { to_handle: 'bob', amount: 10 })).json.authorization_id;
  const [cap, vd] = await Promise.all([capture(t.bob, d, { amount: 10 }), c.post(`/authorizations/${d}/void`, { token: t.ada })]);
  assert.equal([cap.status === 201, vd.status === 200].filter(Boolean).length, 1);
  // 50-way mixed burst with invariant reads interleaved
  await fresh();
  const seed = [];
  for (let i = 0; i < 10; i++) seed.push((await create(t.ada, { to_handle: 'bob', amount: 500 })).json.authorization_id);
  const jobs = [];
  const reads = [];
  for (let i = 0; i < 50; i++) {
    const m = i % 5;
    if (m === 0) jobs.push(c.post('/payments', { token: t.ada, key: k(), body: { to_handle: 'cy', amount: 700 } }));
    else if (m === 1) jobs.push(create(t.ada, { to_handle: 'bob', amount: 600 }));
    else if (m === 2) jobs.push(capture(t.bob, seed[i % 10], { amount: 250, final: i % 2 === 0 }));
    else if (m === 3) jobs.push(c.post(`/authorizations/${seed[(i + 3) % 10]}/void`, { token: t.ada }));
    else jobs.push(c.post('/settlements', { token: t.op, key: k(), body: { transfers: [{ from_handle: 'ada', to_handle: 'cy', amount: 300 }, { from_handle: 'cy', to_handle: 'bob', amount: 100 }] } }));
    reads.push(c.get('/me', { token: t.ada }), c.get('/me', { token: t.bob }), c.get('/me', { token: t.cy }));
  }
  const res = await Promise.all([...jobs, ...reads]);
  assert.ok(res.every((r) => r.status < 500));
  const mine = res.slice(jobs.length).map((r) => r.json);
  for (const m of mine) { assert.ok(m.available >= 0); assert.equal(m.available, m.total - m.held); assert.equal(m.balance, m.total); assert.ok(m.held >= 0); }
  assert.equal(await balanceSum(c, all()), total);
  const open = (await c.get('/authorizations?limit=200&direction=outgoing&status=open', { token: t.ada })).json.authorizations;
  assert.equal((await me(t.ada)).held, open.reduce((s, x) => s + x.remaining_amount, 0));
  for (const x of open) assert.ok(x.captured_amount + x.remaining_amount === x.amount);
});

test('U16/T12/T14: stage-2 export/import round trip', async () => {
  await fresh({ authorization_ttl_seconds: 7 });
  const k1 = k(), k2 = k();
  const a = await create(t.ada, { to_handle: 'bob', amount: 1000, note: 'é' }, k1);
  const cap = await capture(t.bob, a.json.authorization_id, { amount: 100, final: false }, k2);
  const v = (await create(t.ada, { to_handle: 'bob', amount: 20 })).json.authorization_id;
  await c.post(`/authorizations/${v}/void`, { token: t.ada });
  const fail = k();
  err(await create(t.ada, { to_handle: 'ghost', amount: 1 }, fail), 404, 'not_found');
  const e1 = (await c.get('/_test/export')).json;
  assert.equal(e1.format_version, 1); assert.equal(e1.state.schema_version, 3); assert.equal(e1.state.authorization_ttl_seconds, 7);
  assert.equal((await c.reset(FX())).status, 204);
  assert.equal((await c.post('/_test/import', { body: e1 })).status, 204);
  assert.deepEqual((await c.get('/_test/export')).json, e1);
  assert.equal((await me(t.ada)).held, 900);
  const rep = await create(t.ada, { to_handle: 'bob', amount: 1000, note: 'é' }, k1);
  assert.equal(rep.status, 200); assert.equal(rep.text, a.text);
  const rep2 = await capture(t.bob, a.json.authorization_id, { amount: 100, final: false }, k2);
  assert.equal(rep2.status, 200); assert.equal(rep2.text, cap.text);
  assert.equal((await create(t.ada, { to_handle: 'bob', amount: 1 }, fail)).status, 201, 'a failed key stays reusable after import');
  const z = (await create(t.ada, { to_handle: 'bob', amount: 1 })).json;
  assert.equal(Date.parse(z.expires_at) - Date.parse(z.created_at), 7000, 'ttl survives');
  assert.equal((await c.reset(FX())).status, 204);
  assert.equal((await c.get('/authorizations', { token: await login(c, 'ada@example.com') })).json.authorizations.length, 0, 'reset clears authorizations');
  // invalid imports change nothing
  const good = JSON.parse(JSON.stringify(e1));
  const mut = (f) => { const d = JSON.parse(JSON.stringify(good)); f(d); return d; };
  assert.equal((await c.post('/_test/import', { body: good })).status, 204);
  for (const bad of [mut((d) => { d.state.authorizations[0].amount = 0; }), mut((d) => { d.state.authorizations[0].status = 'x'; }), mut((d) => { d.state.authorizations[0].from_user_id = 'ghost'; }), mut((d) => { d.state.authorizations[0].amount = 99999999; d.state.authorizations[0].captured_amount = 0; }), mut((d) => { d.state.authorization_ttl_seconds = 0; }), mut((d) => { d.state.schema_version = 4; }), mut((d) => { d.state.authorizations = 5; })]) {
    err(await c.post('/_test/import', { body: bad }), 422, 'validation_failed');
  }
  assert.deepEqual((await c.get('/_test/export')).json, good);
});
