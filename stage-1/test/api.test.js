'use strict';
// Black-box tests against a running service: BASE_URL=http://localhost:8080 node --test test/
const test = require('node:test');
const assert = require('node:assert/strict');

const BASE = process.env.BASE_URL || 'http://localhost:8080';
let keyN = 0;
const newKey = () => 'k-' + Date.now() + '-' + (++keyN);
const RFC3339 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$/;

async function call(method, path, { token, key, body, raw, headers } = {}) {
  const h = Object.assign({}, headers);
  if (token) h.Authorization = 'Bearer ' + token;
  if (key !== undefined) h['Idempotency-Key'] = key;
  let data;
  if (raw !== undefined) { data = raw; h['Content-Type'] = 'application/json'; }
  else if (body !== undefined) { data = JSON.stringify(body); h['Content-Type'] = 'application/json'; }
  const res = await fetch(BASE + path, { method, headers: h, body: data });
  const text = await res.text();
  let json = null;
  try { json = text === '' ? null : JSON.parse(text); } catch (e) { json = undefined; }
  return { status: res.status, json, text, type: res.headers.get('content-type') };
}

function expectErr(r, status, code) {
  assert.equal(r.status, status, 'status for ' + r.text);
  assert.equal(r.json.error.code, code, r.text);
  assert.equal(typeof r.json.error.message, 'string');
  assert.equal(r.type, 'application/json; charset=utf-8');
}

const user = (id, handle, balance, extra) => Object.assign({ id, email: handle + '@example.com', password: 'correct horse',
  display_name: handle[0].toUpperCase() + handle.slice(1), handle, balance }, extra);

const FIXTURE = () => ({
  currency: 'EUR', minor_units: 2,
  users: [user('u_ada', 'ada', 10000), user('u_bob', 'bob', 2500), user('u_cy', 'cy', 0), user('u_op', 'op', 5000)],
  payments: [
    { id: 'p_1', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 500, note: 'coffee', visibility: 'public' },
    { id: 'p_2', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 700, note: 'secret', visibility: 'private' },
  ],
  requests: [{ id: 'rq_1', requester_id: 'u_bob', payer_id: 'u_ada', amount: 1200, note: 'taxi', status: 'pending' }],
  settlement_operator_ids: ['u_op'],
});

async function reset(fx = FIXTURE()) {
  const r = await call('POST', '/_test/reset', { body: fx });
  assert.equal(r.status, 204, r.text);
}
async function login(handle) {
  const r = await call('POST', '/auth/login', { body: { email: handle + '@example.com', password: 'correct horse' } });
  assert.equal(r.status, 200, r.text);
  return r.json.token;
}
async function world() {
  await reset();
  return { ada: await login('ada'), bob: await login('bob'), cy: await login('cy'), op: await login('op') };
}
const bal = async (t) => (await call('GET', '/me', { token: t })).json.balance;
const pay = (token, body, key = newKey()) => call('POST', '/payments', { token, key, body });

test('health, headers, unknown routes', async () => {
  const r = await call('GET', '/health');
  assert.equal(r.status, 200);
  assert.deepEqual(r.json, { status: 'ok' });
  assert.equal(r.type, 'application/json; charset=utf-8');
  expectErr(await call('GET', '/nope'), 404, 'not_found');
  expectErr(await call('DELETE', '/me'), 405, 'method_not_allowed');
  expectErr(await call('GET', '/me'), 401, 'unauthenticated');
});

test('reset: repeatable, replaces everything, rejects negative balance without change', async () => {
  const w = await world();
  await pay(w.ada, { to_handle: 'bob', amount: 1 });
  const bad = FIXTURE(); bad.users[0].balance = -1;
  expectErr(await call('POST', '/_test/reset', { body: bad }), 422, 'validation_failed');
  assert.equal(await bal(w.ada), 9999, 'state unchanged by failed reset');
  await reset();
  expectErr(await call('GET', '/me', { token: w.ada }), 401, 'unauthenticated');
  const t = await login('ada');
  assert.equal(await bal(t), 10000);
  await reset({ currency: 'JPY', minor_units: 0, users: [user('u_x', 'x', 5)] });
  const me = (await call('GET', '/me', { token: await login('x') })).json;
  assert.deepEqual(me, { user_id: 'u_x', display_name: 'X', handle: 'x', balance: 5, currency: 'JPY', minor_units: 0 });
});

test('seeded state: balances final, feed and requests', async () => {
  const w = await world();
  assert.equal(await bal(w.ada), 10000);
  assert.equal(await bal(w.bob), 2500);
  const feedCy = (await call('GET', '/activity', { token: w.cy })).json.payments;
  assert.deepEqual(feedCy.map((p) => p.payment_id), ['p_1']);
  const feedBob = (await call('GET', '/activity', { token: w.bob })).json.payments;
  assert.deepEqual(feedBob.map((p) => p.payment_id), ['p_2', 'p_1']);
  assert.equal(feedBob[0].visibility, 'private');
  assert.match(feedBob[0].created_at, RFC3339);
  assert.equal(feedBob[0].settlement_id, null);
  const rq = (await call('GET', '/requests', { token: w.ada })).json;
  assert.equal(rq.requests.length, 1);
  assert.equal(rq.requests[0].status, 'pending');
  assert.equal((await call('GET', '/requests', { token: w.cy })).json.requests.length, 0);
  assert.equal((await call('POST', '/requests/rq_1/pay', { token: w.ada, key: newKey(), body: {} })).status, 201);
  await reset({ currency: 'EUR', minor_units: 2, users: [user('u_a', 'a', 1)] });
  assert.equal((await call('GET', '/me', { token: await login('a') })).json.balance, 1);
});

test('auth: signup, login, errors, handle derivation', async () => {
  await world();
  const s = await call('POST', '/auth/signup', { body: { email: 'Ada.Smith+x@Example.com', password: 'longenough', display_name: 'D', handle: 'zzz' } });
  assert.equal(s.status, 201);
  assert.deepEqual(Object.keys(s.json).sort(), ['display_name', 'token', 'user_id']);
  const me = (await call('GET', '/me', { token: s.json.token })).json;
  assert.equal(me.handle, 'ada_smith_x');
  assert.equal(me.balance, 0);
  const long = await call('POST', '/auth/signup', { body: { email: 'abcdefghijklmnopqrstuvwxyz0123456789@e.com', password: 'longenough', display_name: 'L' } });
  assert.equal((await call('GET', '/me', { token: long.json.token })).json.handle, 'abcdefghijklmnopqrst');
  expectErr(await call('POST', '/auth/signup', { body: { email: 'Ada.Smith+x@Example.com', password: 'longenough', display_name: 'D' } }), 409, 'email_taken');
  expectErr(await call('POST', '/auth/signup', { body: { email: 'ADA@other.com', password: 'longenough', display_name: 'D' } }), 409, 'handle_taken');
  expectErr(await call('POST', '/auth/login', { body: { email: 'ADA@other.com', password: 'longenough' } }), 401, 'unauthenticated');
  expectErr(await call('POST', '/auth/signup', { body: { email: 'q@e.com', password: 'short', display_name: 'D' } }), 422, 'validation_failed');
  expectErr(await call('POST', '/auth/signup', { body: { email: 'nope', password: 'longenough', display_name: 'D' } }), 422, 'validation_failed');
  expectErr(await call('POST', '/auth/signup', { body: { password: 'longenough', display_name: 'D' } }), 422, 'validation_failed');
  expectErr(await call('POST', '/auth/signup', { body: { email: 5, password: 'longenough', display_name: 'D' } }), 400, 'malformed_request');
  expectErr(await call('POST', '/auth/login', { body: { email: 'ada@example.com', password: 'wrong' } }), 401, 'unauthenticated');
  expectErr(await call('POST', '/auth/login', { body: { email: 'nobody@example.com', password: 'wrong' } }), 401, 'unauthenticated');
  const a = await login('ada'); const b = await login('ada');
  assert.notEqual(a, b);
  assert.equal(await bal(a), 10000); assert.equal(await bal(b), 10000);
  expectErr(await call('GET', '/me', { headers: { Authorization: 'Token ' + a } }), 401, 'unauthenticated');
  expectErr(await call('GET', '/me', { token: 'bogus' }), 401, 'unauthenticated');
  expectErr(await call('POST', '/auth/signup', { raw: '{nope' }), 400, 'malformed_request');
  expectErr(await call('POST', '/auth/signup', { raw: '[]' }), 400, 'malformed_request');
});

test('payments: shape, boundaries, errors, note fidelity', async () => {
  const w = await world();
  const r = await pay(w.ada, { to_handle: 'bob', amount: 1500, note: 'dinner', visibility: 'public', extra: 1 });
  assert.equal(r.status, 201);
  assert.match(r.json.payment_id, /^.{1,64}$/);
  assert.deepEqual({ ...r.json, payment_id: 0, created_at: 0 }, { payment_id: 0, from_user_id: 'u_ada', from_handle: 'ada', to_user_id: 'u_bob',
    to_handle: 'bob', amount: 1500, currency: 'EUR', note: 'dinner', visibility: 'public', request_id: null, settlement_id: null, created_at: 0 });
  assert.match(r.json.created_at, RFC3339);
  assert.equal(await bal(w.ada), 8500);
  const d = (await pay(w.ada, { to_handle: 'bob', amount: 1 })).json;
  assert.equal(d.note, ''); assert.equal(d.visibility, 'public');
  for (const amount of [0, -5, 1000000001, 1.5, '10', true, null, [], {}]) {
    expectErr(await pay(w.ada, { to_handle: 'bob', amount }), 422, 'validation_failed');
  }
  expectErr(await pay(w.ada, { to_handle: 'bob' }), 422, 'validation_failed');
  for (const amount of [1000.0, 1e3]) assert.equal((await pay(w.ada, { to_handle: 'bob', amount })).json.amount, 1000);
  expectErr(await pay(w.ada, { to_handle: 'ada', amount: 1 }), 422, 'self_payment');
  expectErr(await pay(w.ada, { to_handle: 'ghost', amount: 1 }), 404, 'not_found');
  expectErr(await pay(w.ada, { to_handle: 5, amount: 1 }), 400, 'malformed_request');
  expectErr(await pay(w.ada, { amount: 1 }), 422, 'validation_failed');
  expectErr(await pay(w.ada, { to_handle: 'bob', amount: 1, note: null }), 422, 'validation_failed');
  expectErr(await pay(w.ada, { to_handle: 'bob', amount: 1, note: 5 }), 422, 'validation_failed');
  expectErr(await pay(w.ada, { to_handle: 'bob', amount: 1, note: 'x'.repeat(201) }), 422, 'validation_failed');
  assert.equal((await pay(w.ada, { to_handle: 'bob', amount: 1, note: 'x'.repeat(200) })).status, 201);
  assert.equal((await pay(w.ada, { to_handle: 'bob', amount: 1, note: '😀'.repeat(200) })).status, 201);
  expectErr(await pay(w.ada, { to_handle: 'bob', amount: 1, visibility: 'friends' }), 422, 'validation_failed');
  expectErr(await pay(w.ada, { to_handle: 'bob', amount: 1, visibility: 5 }), 422, 'validation_failed');
  expectErr(await pay(w.ada, { to_handle: 'bob', amount: 1, visibility: null }), 422, 'validation_failed');
  const note = '  <b>é́ 😀 "q" \\ </b>  ';
  assert.equal((await pay(w.ada, { to_handle: 'bob', amount: 1, note })).json.note, note);
  // exact balance, then insufficient funds changes nothing
  const before = await bal(w.cy);
  expectErr(await pay(w.cy, { to_handle: 'bob', amount: before + 1 }), 409, 'insufficient_funds');
  const all = await bal(w.ada);
  assert.equal((await pay(w.ada, { to_handle: 'cy', amount: Math.min(all, 1e9) })).status, 201);
  assert.equal(await bal(w.ada), all - Math.min(all, 1e9));
  expectErr(await pay(w.cy, { to_handle: 'bob', amount: 1e9 }), 409, 'insufficient_funds');
  const feed = (await call('GET', '/activity', { token: w.cy })).json.payments;
  assert.ok(!feed.some((p) => p.from_handle === 'cy'), 'failed payment leaves no trace');
});

test('large balances stay exact', async () => {
  const fx = FIXTURE(); fx.users[0].balance = 9007199254740000; fx.payments = []; fx.requests = [];
  await reset(fx);
  const ada = await login('ada');
  assert.equal((await pay(ada, { to_handle: 'bob', amount: 1000000000 })).status, 201);
  assert.equal(await bal(ada), 9007199254740000 - 1000000000);
  assert.equal(await bal(await login('bob')), 2500 + 1000000000);
});

test('idempotency on payments', async () => {
  const w = await world();
  const key = newKey();
  const body = { to_handle: 'bob', amount: 100, note: 'a' };
  const first = await pay(w.ada, body, key);
  assert.equal(first.status, 201);
  const again = await pay(w.ada, { note: 'a', amount: 100.0, to_handle: 'bob' }, key);
  assert.equal(again.status, 200);
  assert.deepEqual(again.json, first.json);
  assert.equal(await bal(w.ada), 9900);
  expectErr(await pay(w.ada, { ...body, amount: 101 }, key), 409, 'idempotency_key_reuse');
  expectErr(await pay(w.ada, { to_handle: 'bob', amount: 'bad' }, key), 409, 'idempotency_key_reuse');
  expectErr(await pay(w.ada, { ...body, extra: 1 }, key), 409, 'idempotency_key_reuse');
  // another user, same key string
  assert.equal((await pay(w.bob, { to_handle: 'ada', amount: 5 }, key)).status, 201);
  // same key, same body, different path = new request
  assert.equal((await call('POST', '/requests', { token: w.ada, key, body: { payer_handle: 'bob', amount: 100 } })).status, 201);
  // failed 4xx does not claim the key
  const k2 = newKey();
  expectErr(await pay(w.ada, { to_handle: 'bob', amount: 0 }, k2), 422, 'validation_failed');
  assert.equal((await pay(w.ada, { to_handle: 'bob', amount: 7 }, k2)).status, 201);
  // headers
  expectErr(await call('POST', '/payments', { token: w.ada, body }), 400, 'missing_idempotency_key');
  expectErr(await call('POST', '/payments', { token: w.ada, body, key: '' }), 400, 'missing_idempotency_key');
  expectErr(await pay(w.ada, body, 'k'.repeat(256)), 422, 'validation_failed');
  assert.equal((await pay(w.ada, body, 'k'.repeat(255))).status, 201);
});

test('requests: lifecycle, errors, replay', async () => {
  const w = await world();
  const key = newKey();
  const mk = (token, body, k = newKey()) => call('POST', '/requests', { token, key: k, body });
  const r = await mk(w.cy, { payer_handle: 'ada', amount: 99999999, note: 'big' }, key);
  assert.equal(r.status, 201);
  assert.deepEqual({ ...r.json, request_id: 0, created_at: 0 }, { request_id: 0, requester_id: 'u_cy', requester_handle: 'cy', payer_id: 'u_ada',
    payer_handle: 'ada', amount: 99999999, currency: 'EUR', note: 'big', status: 'pending', payment_id: null, created_at: 0 });
  expectErr(await call('POST', `/requests/${r.json.request_id}/pay`, { token: w.ada, key: newKey(), body: {} }), 409, 'insufficient_funds');
  assert.equal((await call('GET', '/requests', { token: w.ada })).json.requests.find((x) => x.request_id === r.json.request_id).status, 'pending');
  expectErr(await mk(w.cy, { payer_handle: 'cy', amount: 5 }), 422, 'self_request');
  expectErr(await mk(w.cy, { payer_handle: 'ghost', amount: 5 }), 404, 'not_found');
  expectErr(await mk(w.cy, { payer_handle: 'ada', amount: 0 }), 422, 'validation_failed');
  expectErr(await mk(w.cy, { payer_handle: 'ada', amount: 5, note: 'x'.repeat(201) }), 422, 'validation_failed');
  expectErr(await mk(w.cy, { payer_handle: 7, amount: 5 }), 400, 'malformed_request');
  // money arrives later, same request becomes payable
  await pay(w.bob, { to_handle: 'ada', amount: 1 });
  const rq = (await mk(w.cy, { payer_handle: 'bob', amount: 2000 })).json;
  const k = newKey();
  const paid = await call('POST', `/requests/${rq.request_id}/pay`, { token: w.bob, key: k, body: { visibility: 'private' } });
  assert.equal(paid.status, 201);
  assert.equal(paid.json.request_id, rq.request_id);
  assert.equal(paid.json.visibility, 'private');
  assert.equal(paid.json.from_handle, 'bob'); assert.equal(paid.json.to_handle, 'cy'); assert.equal(paid.json.amount, 2000);
  assert.equal(await bal(w.cy), 2000);
  const replay = await call('POST', `/requests/${rq.request_id}/pay`, { token: w.bob, key: k, body: { visibility: 'private' } });
  assert.equal(replay.status, 200); assert.deepEqual(replay.json, paid.json);
  assert.equal(await bal(w.cy), 2000);
  expectErr(await call('POST', `/requests/${rq.request_id}/pay`, { token: w.bob, key: k, body: {} }), 409, 'idempotency_key_reuse');
  expectErr(await call('POST', `/requests/${rq.request_id}/pay`, { token: w.bob, key: newKey(), body: {} }), 409, 'request_not_pending');
  expectErr(await call('POST', `/requests/${rq.request_id}/cancel`, { token: w.cy }), 409, 'request_not_pending');
  expectErr(await call('POST', `/requests/${rq.request_id}/decline`, { token: w.bob }), 409, 'request_not_pending');
  const listed = (await call('GET', '/requests?status=paid', { token: w.cy })).json.requests;
  assert.equal(listed[0].payment_id, paid.json.payment_id);
  // pay: 403/404/422 and key across different requests
  const a = (await mk(w.cy, { payer_handle: 'ada', amount: 1 })).json.request_id;
  const b = (await mk(w.cy, { payer_handle: 'ada', amount: 1 })).json.request_id;
  expectErr(await call('POST', `/requests/${a}/pay`, { token: w.bob, key: newKey(), body: {} }), 403, 'forbidden');
  expectErr(await call('POST', `/requests/${a}/pay`, { token: w.cy, key: newKey(), body: {} }), 403, 'forbidden');
  expectErr(await call('POST', '/requests/zzz/pay', { token: w.ada, key: newKey(), body: {} }), 404, 'not_found');
  expectErr(await call('POST', `/requests/${a}/pay`, { token: w.ada, key: newKey(), body: { visibility: 'x' } }), 422, 'validation_failed');
  expectErr(await call('POST', `/requests/${a}/pay`, { token: w.ada, body: {} }), 400, 'missing_idempotency_key');
  const same = newKey();
  assert.equal((await call('POST', `/requests/${a}/pay`, { token: w.ada, key: same })).status, 201);
  assert.equal((await call('POST', `/requests/${b}/pay`, { token: w.ada, key: same })).status, 201);
  // decline / cancel
  const c = (await mk(w.cy, { payer_handle: 'ada', amount: 1 })).json.request_id;
  expectErr(await call('POST', `/requests/${c}/decline`, { token: w.cy }), 403, 'forbidden');
  expectErr(await call('POST', `/requests/${c}/cancel`, { token: w.ada }), 403, 'forbidden');
  expectErr(await call('POST', `/requests/${c}/cancel`, { token: w.bob }), 403, 'forbidden');
  expectErr(await call('POST', '/requests/zzz/cancel', { token: w.ada }), 404, 'not_found');
  expectErr(await call('POST', '/requests/zzz/decline', { token: w.ada }), 404, 'not_found');
  const dec = await call('POST', `/requests/${c}/decline`, { token: w.ada });
  assert.equal(dec.json.status, 'declined');
  assert.equal((await call('POST', `/requests/${c}/decline`, { token: w.ada })).status, 200);
  expectErr(await call('POST', `/requests/${c}/cancel`, { token: w.cy }), 409, 'request_not_pending');
  expectErr(await call('POST', `/requests/${c}/pay`, { token: w.ada, key: newKey(), body: {} }), 409, 'request_not_pending');
  const d = (await mk(w.cy, { payer_handle: 'ada', amount: 1 })).json.request_id;
  assert.equal((await call('POST', `/requests/${d}/cancel`, { token: w.cy })).json.status, 'cancelled');
  assert.equal((await call('POST', `/requests/${d}/cancel`, { token: w.cy })).status, 200);
  expectErr(await call('POST', `/requests/${d}/decline`, { token: w.ada }), 409, 'request_not_pending');
  // replay of original creation after the resource changed
  const rep = await mk(w.cy, { payer_handle: 'ada', amount: 99999999, note: 'big' }, key);
  assert.equal(rep.status, 200); assert.equal(rep.json.status, 'pending');
  // requests never in the feed
  assert.ok(!(await call('GET', '/activity?limit=200', { token: w.cy })).text.includes('requester_id'));
});

test('GET /requests and /activity: filters, paging, validation', async () => {
  const w = await world();
  for (let i = 0; i < 5; i++) await call('POST', '/requests', { token: w.cy, key: newKey(), body: { payer_handle: 'ada', amount: i + 1 } });
  const walk = [];
  let off = 0;
  for (;;) {
    const r = (await call('GET', `/requests?limit=2&offset=${off}&direction=incoming&unknown=1`, { token: w.ada })).json;
    walk.push(...r.requests.map((x) => x.amount));
    if (!r.has_more) break;
    off += 2;
  }
  assert.deepEqual(walk, [5, 4, 3, 2, 1, 1200]);
  assert.equal((await call('GET', '/requests?limit=6&direction=incoming', { token: w.ada })).json.has_more, false);
  assert.equal((await call('GET', '/requests?limit=5&direction=incoming', { token: w.ada })).json.has_more, true);
  assert.equal((await call('GET', '/requests?direction=outgoing', { token: w.ada })).json.requests.length, 0);
  assert.equal((await call('GET', '/requests?direction=outgoing', { token: w.cy })).json.requests.length, 5);
  assert.equal((await call('GET', '/requests?status=paid', { token: w.ada })).json.requests.length, 0);
  for (const q of ['limit=0', 'limit=201', 'limit=1e1', 'limit=4.0', 'limit=+4', 'limit=-1', 'limit=', 'limit=abc', 'offset=-1', 'offset=1e1',
    'offset=', 'direction=sideways', 'status=bogus', 'status=']) {
    for (const p of ['/requests?', '/activity?']) {
      if (p === '/activity?' && /direction|status/.test(q)) continue;
      expectErr(await call('GET', p + q, { token: w.ada }), 422, 'validation_failed');
    }
  }
  assert.equal((await call('GET', '/activity?limit=200&offset=999999', { token: w.ada })).json.payments.length, 0);
  assert.equal((await call('GET', '/activity?limit=1', { token: w.ada })).json.has_more, true);
});

test('feed visibility rule', async () => {
  const w = await world();
  const priv = (await pay(w.ada, { to_handle: 'bob', amount: 10, visibility: 'private' })).json;
  const pub = (await pay(w.ada, { to_handle: 'bob', amount: 11 })).json;
  const ids = async (t) => (await call('GET', '/activity?limit=200', { token: t })).json.payments.map((p) => p.payment_id);
  assert.ok((await ids(w.ada)).includes(priv.payment_id));
  assert.ok((await ids(w.bob)).includes(priv.payment_id));
  assert.ok(!(await ids(w.cy)).includes(priv.payment_id));
  assert.ok(!(await ids(w.op)).includes(priv.payment_id), 'operator does not see private items');
  assert.ok((await ids(w.cy)).includes(pub.payment_id));
  assert.deepEqual((await ids(w.bob)).slice(0, 2), [pub.payment_id, priv.payment_id]);
});

test('splits and rounding', async () => {
  const w = await world();
  const split = (token, body, k = newKey()) => call('POST', '/splits', { token, key: k, body });
  const table = [[1000, 3, [334, 333, 333]], [1, 3, [1, 0, 0]], [10, 3, [4, 3, 3]], [999, 3, [333, 333, 333]], [5, 5, [1, 1, 1, 1, 1]]];
  const pool = ['ada', 'bob', 'cy', 'op'];
  const extra = [];
  for (let i = 0; i < 2; i++) {
    const r = await call('POST', '/auth/signup', { body: { email: 'e' + i + '@example.com', password: 'longenough', display_name: 'E' } });
    extra.push('e' + i); assert.equal(r.status, 201);
  }
  const names = pool.concat(extra);
  for (const [amount, n, shares] of table) {
    const handles = names.slice(0, n);
    const r = await split(w.ada, { amount, participant_handles: handles, note: 'n' });
    assert.equal(r.status, 201, r.text);
    assert.deepEqual(r.json.shares, handles.map((handle, i) => ({ handle, amount: shares[i] })));
    assert.equal(r.json.requests.length, n - 1);
    assert.deepEqual(r.json.requests.map((x) => x.payer_handle), handles.slice(1));
    assert.deepEqual(r.json.requests.map((x) => x.amount), shares.slice(1));
    assert.ok(r.json.requests.every((x) => x.requester_handle === 'ada' && x.status === 'pending' && x.note === 'n'));
    assert.equal(r.json.amount, amount); assert.equal(r.json.currency, 'EUR'); assert.match(r.json.created_at, RFC3339);
  }
  // caller omitted: every participant gets a request
  const r = await split(w.ada, { amount: 10, participant_handles: ['bob', 'cy', 'op'] });
  assert.deepEqual(r.json.shares.map((s) => s.amount), [4, 3, 3]);
  assert.equal(r.json.requests.length, 3);
  // reorder moves the extra unit
  const r2 = await split(w.ada, { amount: 10, participant_handles: ['cy', 'bob', 'op'] });
  assert.deepEqual(r2.json.shares, [{ handle: 'cy', amount: 4 }, { handle: 'bob', amount: 3 }, { handle: 'op', amount: 3 }]);
  // a zero share still produces a payable request
  const z = (await split(w.ada, { amount: 1, participant_handles: ['bob', 'cy', 'op'] })).json;
  assert.deepEqual(z.requests.map((x) => x.amount), [1, 0, 0]);
  const zr = z.requests[2].request_id;
  assert.equal((await call('POST', `/requests/${zr}/pay`, { token: w.op, key: newKey(), body: {} })).status, 201);
  // only the caller
  const only = await split(w.ada, { amount: 50, participant_handles: ['ada'] });
  assert.equal(only.status, 201); assert.deepEqual(only.json.requests, []); assert.deepEqual(only.json.shares, [{ handle: 'ada', amount: 50 }]);
  // errors
  expectErr(await split(w.ada, { amount: 0, participant_handles: ['bob'] }), 422, 'validation_failed');
  expectErr(await split(w.ada, { amount: 5.5, participant_handles: ['bob'] }), 422, 'validation_failed');
  expectErr(await split(w.ada, { amount: 5, participant_handles: [] }), 422, 'validation_failed');
  expectErr(await split(w.ada, { amount: 5, participant_handles: ['bob', 'bob'] }), 422, 'validation_failed');
  expectErr(await split(w.ada, { amount: 5 }), 422, 'validation_failed');
  expectErr(await split(w.ada, { amount: 5, participant_handles: 'bob' }), 400, 'malformed_request');
  expectErr(await split(w.ada, { amount: 5, participant_handles: ['bob', 3] }), 400, 'malformed_request');
  expectErr(await split(w.ada, { amount: 5, participant_handles: ['bob'], note: 'x'.repeat(201) }), 422, 'validation_failed');
  expectErr(await split(w.ada, { amount: 5, participant_handles: ['bob', 'ghost'] }), 404, 'not_found');
  const before = (await call('GET', '/requests?limit=200', { token: w.bob })).json.requests.length;
  expectErr(await split(w.ada, { amount: 5, participant_handles: ['bob', 'ghost'] }), 404, 'not_found');
  assert.equal((await call('GET', '/requests?limit=200', { token: w.bob })).json.requests.length, before);
  // replay
  const k = newKey();
  const f = await split(w.cy, { amount: 9, participant_handles: ['ada', 'bob'] }, k);
  const g = await split(w.cy, { participant_handles: ['ada', 'bob'], amount: 9 }, k);
  assert.equal(f.status, 201); assert.equal(g.status, 200); assert.deepEqual(g.json, f.json);
  expectErr(await split(w.cy, { amount: 9, participant_handles: ['bob', 'ada'] }, k), 409, 'idempotency_key_reuse');
  // splits are not feed items
  assert.ok(!(await call('GET', '/activity?limit=200', { token: w.ada })).text.includes('sp_'));
  // paying everything keeps the total
  for (const t of [w.ada, w.bob, w.cy, w.op]) {
    const incoming = (await call('GET', '/requests?direction=incoming&status=pending&limit=200', { token: t })).json.requests;
    for (const q of incoming) await call('POST', `/requests/${q.request_id}/pay`, { token: t, key: newKey(), body: {} });
  }
  let total = 0;
  for (const t of [w.ada, w.bob, w.cy, w.op]) total += await bal(t);
  assert.equal(total, 10000 + 2500 + 5000, 'the four seeded wallets still hold the seeded total; new users hold 0');
});

test('settlements', async () => {
  const w = await world();
  const st = (token, body, k = newKey()) => call('POST', '/settlements', { token, key: k, body });
  const tr = (from_handle, to_handle, amount, extra) => Object.assign({ from_handle, to_handle, amount }, extra);
  expectErr(await call('POST', '/settlements', { key: newKey(), body: { transfers: [tr('ada', 'bob', 1)] } }), 401, 'unauthenticated');
  expectErr(await st(w.ada, { transfers: [tr('ada', 'bob', 1)] }), 403, 'forbidden');
  expectErr(await call('POST', '/settlements', { token: w.op, body: { transfers: [tr('ada', 'bob', 1)] } }), 400, 'missing_idempotency_key');
  for (const transfers of [undefined, 'x', [], Array(33).fill(tr('ada', 'bob', 1)), [5], [null]]) {
    expectErr(await st(w.op, { transfers }), 422, 'validation_failed');
  }
  assert.equal((await st(w.op, { transfers: Array(32).fill(tr('ada', 'bob', 1)) })).status, 201);
  // net affordability: cy has 0, receives 100 and passes 50 on
  const k = newKey();
  const body = { transfers: [tr('ada', 'cy', 100, { note: 'a', unknown: 1 }), tr('cy', 'bob', 50, { visibility: 'private' })] };
  const r = await st(w.op, body, k);
  assert.equal(r.status, 201, r.text);
  assert.equal(r.json.payments.length, 2);
  assert.match(r.json.committed_at, RFC3339);
  assert.ok(r.json.payments.every((p) => p.settlement_id === r.json.settlement_id && p.request_id === null && p.created_at === r.json.committed_at));
  assert.deepEqual(r.json.payments.map((p) => [p.from_handle, p.to_handle, p.amount, p.visibility, p.note]),
    [['ada', 'cy', 100, 'public', 'a'], ['cy', 'bob', 50, 'private', '']]);
  assert.equal(await bal(w.cy), 50);
  const rep = await st(w.op, body, k);
  assert.equal(rep.status, 200); assert.deepEqual(rep.json, r.json);
  expectErr(await st(w.op, { transfers: [tr('ada', 'cy', 1)] }, k), 409, 'idempotency_key_reuse');
  // feed: operator sees only public members; cy sees both; non-member payments have null
  const opFeed = (await call('GET', '/activity?limit=200', { token: w.op })).json.payments;
  assert.ok(opFeed.some((p) => p.payment_id === r.json.payments[0].payment_id));
  assert.ok(!opFeed.some((p) => p.payment_id === r.json.payments[1].payment_id));
  const bobFeed = (await call('GET', '/activity?limit=200', { token: w.bob })).json.payments;
  assert.ok(bobFeed.some((p) => p.payment_id === r.json.payments[1].payment_id));
  assert.equal((await pay(w.ada, { to_handle: 'bob', amount: 1 })).json.settlement_id, null);
  expectErr(await call('GET', '/requests/rq_1/pay', { token: w.op }), 405, 'method_not_allowed');
  expectErr(await call('POST', '/requests/rq_1/cancel', { token: w.op }), 403, 'forbidden');
  // failure: collective funds, nothing commits, key stays free
  const k2 = newKey();
  const before = [await bal(w.ada), await bal(w.bob), await bal(w.cy)];
  expectErr(await st(w.op, { transfers: [tr('cy', 'bob', 40), tr('cy', 'ada', 20)] }, k2), 409, 'insufficient_funds');
  assert.deepEqual([await bal(w.ada), await bal(w.bob), await bal(w.cy)], before);
  assert.equal((await st(w.op, { transfers: [tr('cy', 'bob', 40)] }, k2)).status, 201);
  // precedence
  expectErr(await st(w.op, { transfers: [tr('ada', 'bob', 0), tr('ada', 'ghost', 5)] }), 422, 'validation_failed');
  expectErr(await st(w.op, { transfers: [tr('ada', 'ghost', 5), tr('ada', 'bob', 0)] }), 404, 'not_found');
  expectErr(await st(w.op, { transfers: [tr('ada', 'ada', 5)] }), 422, 'self_payment');
  expectErr(await st(w.op, { transfers: [tr('ada', 'bob', 99999999), tr('ada', 'ghost', 1)] }), 404, 'not_found');
  expectErr(await st(w.op, { transfers: [tr('ada', 'bob', 99999999)] }), 409, 'insufficient_funds');
  expectErr(await st(w.op, { transfers: [tr('ada', 'bob', 1, { note: 'x'.repeat(201) })] }), 422, 'validation_failed');
  expectErr(await st(w.op, { transfers: [tr('ada', 'bob', 1, { visibility: 'nope' })] }), 422, 'validation_failed');
  expectErr(await st(w.op, { transfers: [{ from_handle: 'ada', amount: 1 }] }), 422, 'validation_failed');
});

test('export / import', async () => {
  const w = await world();
  const k = newKey();
  const p = await pay(w.ada, { to_handle: 'bob', amount: 321, note: 'keep', visibility: 'private' }, k);
  const failKey = newKey();
  expectErr(await pay(w.ada, { to_handle: 'bob', amount: 0 }, failKey), 422, 'validation_failed');
  const stl = await call('POST', '/settlements', { token: w.op, key: 'sk', body: { transfers: [{ from_handle: 'op', to_handle: 'cy', amount: 10 }] } });
  const rq = (await call('POST', '/requests', { token: w.cy, key: 'rk', body: { payer_handle: 'ada', amount: 5 } })).json;
  const exp = await call('GET', '/_test/export');
  assert.equal(exp.status, 200);
  assert.equal(exp.json.track, 'pocketful'); assert.equal(exp.json.format_version, 1);
  assert.ok(!exp.text.includes('correct horse'), 'no plaintext passwords');
  const snapshot = exp.text;
  const snap = async () => JSON.stringify([await Promise.all(['ada', 'bob', 'cy', 'op'].map(async (h) => (await call('GET', '/me', { token: w[h] })).json)),
    (await call('GET', '/activity?limit=200', { token: w.ada })).json, (await call('GET', '/requests?limit=200', { token: w.ada })).json]);
  const before = await snap();
  // mutate, then import
  await pay(w.ada, { to_handle: 'bob', amount: 9 });
  await reset({ currency: 'JPY', minor_units: 0, users: [user('u_z', 'zed', 1)] });
  const imp = await call('POST', '/_test/import', { raw: snapshot });
  assert.equal(imp.status, 204);
  assert.equal(await snap(), before);
  assert.equal(await snap(), before);
  assert.equal((await call('POST', '/_test/import', { raw: snapshot })).status, 204);
  assert.equal(await snap(), before, 'repeat import does not duplicate');
  const again = await pay(w.ada, { to_handle: 'bob', amount: 321, note: 'keep', visibility: 'private' }, k);
  assert.equal(again.status, 200); assert.deepEqual(again.json, p.json);
  expectErr(await pay(w.ada, { to_handle: 'bob', amount: 322 }, k), 409, 'idempotency_key_reuse');
  assert.equal((await pay(w.ada, { to_handle: 'bob', amount: 3 }, failKey)).status, 201);
  const sr = await call('POST', '/settlements', { token: w.op, key: 'sk', body: { transfers: [{ from_handle: 'op', to_handle: 'cy', amount: 10 }] } });
  assert.equal(sr.status, 200); assert.deepEqual(sr.json, stl.json);
  assert.equal((await call('POST', `/requests/${rq.request_id}/pay`, { token: w.ada, key: newKey(), body: {} })).status, 201);
  assert.equal((await call('POST', '/auth/login', { body: { email: 'ada@example.com', password: 'correct horse' } })).status, 200);
  const fresh = (await call('POST', '/auth/signup', { body: { email: 'new@example.com', password: 'longenough', display_name: 'N' } })).json;
  assert.ok(fresh.user_id);
  // invalid imports leave the destination untouched
  const state = JSON.parse(snapshot);
  const cur = await snap();
  expectErr(await call('POST', '/_test/import', { raw: '{bad' }), 400, 'malformed_request');
  expectErr(await call('POST', '/_test/import', { body: { ...state, track: 'other' } }), 422, 'validation_failed');
  expectErr(await call('POST', '/_test/import', { body: { ...state, format_version: 2 } }), 422, 'validation_failed');
  expectErr(await call('POST', '/_test/import', { body: { track: 'pocketful', format_version: 1 } }), 422, 'validation_failed');
  expectErr(await call('POST', '/_test/import', { body: { ...state, state: { ...state.state, users: 'x' } } }), 422, 'validation_failed');
  const skew = JSON.parse(snapshot); skew.state.users[0].balance += 1;
  expectErr(await call('POST', '/_test/import', { body: skew }), 422, 'validation_failed');
  assert.equal(await snap(), cur);
  // import replaces credentials; reset clears imported state
  await reset({ currency: 'EUR', minor_units: 2, users: [user('u_q', 'q', 1)] });
  assert.equal((await call('POST', '/_test/import', { raw: snapshot })).status, 204);
  expectErr(await call('GET', '/me', { token: fresh.token }), 401, 'unauthenticated');
  assert.equal((await call('GET', '/me', { token: w.ada })).status, 200);
  await reset();
  expectErr(await call('GET', '/me', { token: w.ada }), 401, 'unauthenticated');
});

test('concurrency: no overspend, one pay per request, idempotent fan-in, conservation', async () => {
  const w = await world();
  const fx = FIXTURE(); fx.users[2].balance = 1000;
  await reset(fx);
  const t = { ada: await login('ada'), bob: await login('bob'), cy: await login('cy'), op: await login('op') };
  const total = 10000 + 2500 + 1000 + 5000;
  const sum = async () => (await Promise.all(Object.values(t).map(bal))).reduce((a, b) => a + b, 0);
  // overspend one wallet
  const rs = await Promise.all(Array.from({ length: 50 }, () => pay(t.cy, { to_handle: 'bob', amount: 300 })));
  assert.equal(rs.filter((r) => r.status === 201).length, 3);
  assert.ok(rs.every((r) => r.status === 201 || r.json.error.code === 'insufficient_funds'));
  assert.equal(await bal(t.cy), 100);
  // concurrent pay of one request, distinct keys
  const rq = (await call('POST', '/requests', { token: t.bob, key: newKey(), body: { payer_handle: 'ada', amount: 100 } })).json;
  const ps = await Promise.all(Array.from({ length: 30 }, () => call('POST', `/requests/${rq.request_id}/pay`, { token: t.ada, key: newKey(), body: {} })));
  assert.equal(ps.filter((r) => r.status === 201).length, 1);
  assert.ok(ps.every((r) => r.status === 201 || r.json.error.code === 'request_not_pending'));
  // pay vs cancel race
  const rq2 = (await call('POST', '/requests', { token: t.bob, key: newKey(), body: { payer_handle: 'ada', amount: 100 } })).json;
  const race = await Promise.all([call('POST', `/requests/${rq2.request_id}/pay`, { token: t.ada, key: newKey(), body: {} }),
    call('POST', `/requests/${rq2.request_id}/cancel`, { token: t.bob }), call('POST', `/requests/${rq2.request_id}/decline`, { token: t.ada })]);
  const final = (await call('GET', '/requests?limit=200', { token: t.bob })).json.requests.find((x) => x.request_id === rq2.request_id);
  assert.equal(race.filter((r) => r.status === 200 || r.status === 201).length, 1, 'exactly one of pay/cancel/decline wins: ' + final.status);
  // same key fan-in
  const key = newKey();
  const fan = await Promise.all(Array.from({ length: 40 }, () => pay(t.ada, { to_handle: 'bob', amount: 10 }, key)));
  assert.equal(fan.filter((r) => r.status === 201).length, 1);
  assert.equal(fan.filter((r) => r.status === 200).length, 39);
  assert.ok(fan.every((r) => r.json.payment_id === fan[0].json.payment_id));
  // mixed burst keeps the total
  const burst = [];
  for (let i = 0; i < 50; i++) {
    const from = ['ada', 'bob', 'cy', 'op'][i % 4], to = ['bob', 'cy', 'op', 'ada'][i % 4];
    burst.push(i % 7 === 0
      ? call('POST', '/settlements', { token: t.op, key: newKey(), body: { transfers: [{ from_handle: from, to_handle: to, amount: 400 }, { from_handle: to, to_handle: from, amount: 100 }] } })
      : pay(t[from], { to_handle: to, amount: 150 }));
  }
  const exportsDuring = Promise.all([call('GET', '/_test/export'), call('GET', '/_test/export')]);
  const out = await Promise.all(burst);
  assert.ok(out.every((r) => r.status < 500));
  for (const e of await exportsDuring) {
    const users = e.json.state.users;
    assert.equal(users.reduce((a, u) => a + u.balance, 0), total);
  }
  assert.equal(await sum(), total);
  for (const x of Object.values(t)) assert.ok((await bal(x)) >= 0);
});

test('robustness: no 5xx on garbage input', async () => {
  const w = await world();
  const cases = [
    () => call('POST', '/payments', { token: w.ada, key: newKey(), raw: 'nope' }),
    () => call('POST', '/payments', { token: w.ada, key: newKey(), raw: '' }),
    () => call('POST', '/payments', { token: w.ada, key: newKey(), raw: '[[[[' + '['.repeat(50000) }),
    () => call('POST', '/payments', { token: w.ada, key: newKey(), raw: '['.repeat(200000) + ']'.repeat(200000) }),
    () => call('POST', '/payments', { token: w.ada, key: newKey(), raw: '"str"' }),
    () => call('POST', '/payments', { token: w.ada, key: newKey(), raw: 'null' }),
    () => call('POST', '/payments', { token: w.ada, key: newKey(), raw: '{"to_handle":"bob","amount":1e999}' }),
    () => call('POST', '/payments', { token: w.ada, key: 'ü'.repeat(300), body: { to_handle: 'bob', amount: 1 } }),
    () => call('POST', '/splits', { token: w.ada, key: newKey(), body: { amount: 5, participant_handles: [null] } }),
    () => call('POST', '/settlements', { token: w.op, key: newKey(), body: { transfers: [{ from_handle: 1, to_handle: 2, amount: 'x' }] } }),
    () => call('POST', '/requests/%zz/pay', { token: w.ada, key: newKey() }),
    () => call('GET', '/requests?limit=' + '9'.repeat(400), { token: w.ada }),
    () => call('POST', '/_test/reset', { raw: '{"users":[{"id":1}]}' }),
    () => call('POST', '/_test/reset', { raw: '{"users":"x"}' }),
    () => call('POST', '/_test/reset', { raw: '[]' }),
    () => call('POST', '/_test/import', { raw: '{"track":"pocketful","format_version":1,"state":{"users":[[]]}}' }),
    () => call('POST', '/auth/login', { raw: '{}' }),
    () => call('GET', '/me', { headers: { Authorization: 'Bearer ' } }),
  ];
  for (const c of cases) {
    const r = await c();
    assert.ok(r.status >= 400 && r.status < 500, 'status ' + r.status + ' ' + r.text.slice(0, 100));
    assert.ok(r.json && r.json.error && r.json.error.code, 'error body ' + r.text.slice(0, 100));
  }
  assert.equal((await call('GET', '/activity?offset=' + '9'.repeat(400), { token: w.ada })).status, 200);
  assert.equal((await call('GET', '/health')).status, 200);
});

test('unknown fields and query params are ignored', async () => {
  const w = await world();
  assert.equal((await call('GET', '/me?x=1', { token: w.ada })).status, 200);
  assert.equal((await call('POST', '/requests/rq_1/decline', { token: w.ada, raw: '{"junk":true}' })).status, 200);
  assert.equal((await call('POST', '/requests/rq_1/cancel', { token: w.bob, raw: 'not json' })).status, 409);
  assert.equal((await call('POST', '/auth/login', { body: { email: 'ada@example.com', password: 'correct horse', zzz: 1 } })).status, 200);
});

test('currencies: BHD and JPY report their minor units', async () => {
  for (const [currency, minor_units] of [['BHD', 3], ['JPY', 0], ['EUR', 2]]) {
    await reset({ currency, minor_units, users: [user('u_a', 'a', 1000), user('u_b', 'b', 0)] });
    const a = await login('a');
    const me = (await call('GET', '/me', { token: a })).json;
    assert.equal(me.currency, currency); assert.equal(me.minor_units, minor_units);
    assert.equal((await pay(a, { to_handle: 'b', amount: 10 })).json.currency, currency);
  }
  const r = await call('POST', '/_test/reset', { body: { currency: 'EUR', minor_units: 5, users: [] } });
  expectErr(r, 422, 'validation_failed');
  await reset({ users: [user('u_a', 'a', 1)] });
});
