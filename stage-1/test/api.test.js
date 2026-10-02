'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const { createServer } = require('../server');

let base;
const server = createServer();
test.before(() => new Promise((r) => server.listen(0, '127.0.0.1', () => { base = `http://127.0.0.1:${server.address().port}`; r(); })));
test.after(() => { server.closeAllConnections(); server.close(); });

let kc = 0;
const key = () => 'k' + (++kc) + Math.random();
async function call(method, path, { token, body, raw, headers = {}, k } = {}) {
  const h = { ...headers };
  if (token) h.Authorization = 'Bearer ' + token;
  if (k !== undefined) h['Idempotency-Key'] = k;
  let payload;
  if (raw !== undefined) payload = raw; else if (body !== undefined) payload = JSON.stringify(body);
  const r = await fetch(base + path, { method, headers: h, body: payload });
  const text = await r.text();
  let json; try { json = text ? JSON.parse(text) : undefined; } catch { json = undefined; }
  return { status: r.status, json, text, headers: r.headers };
}
const post = (path, token, body, k) => call('POST', path, { token, body, k: k === undefined ? key() : k });
const get = (path, token) => call('GET', path, { token });

const U = (id, handle, balance, extra = {}) => ({ id, email: `${handle}@example.com`, password: 'correct horse', display_name: handle, handle, balance, ...extra });
async function world(extra = {}) {
  const fx = { currency: 'EUR', minor_units: 2, users: [U('u_ada', 'ada', 10000), U('u_bob', 'bob', 2500), U('u_cy', 'cy', 500), U('u_op', 'op', 0)], ...extra };
  const r = await call('POST', '/_test/reset', { body: fx });
  assert.equal(r.status, 204, r.text);
  const t = {};
  for (const u of fx.users) t[u.handle] = (await call('POST', '/auth/login', { body: { email: u.email, password: u.password } })).json.token;
  return t;
}
const bal = async (t) => (await get('/me', t)).json.balance;
const err = (r, status, code) => { assert.equal(r.status, status, r.text); assert.equal(r.json.error.code, code); assert.equal(typeof r.json.error.message, 'string'); };

test('health, headers, 404/405 envelope', async () => {
  const r = await get('/health');
  assert.deepEqual(r.json, { status: 'ok' });
  assert.equal(r.headers.get('content-type'), 'application/json; charset=utf-8');
  err(await get('/nope'), 404, 'not_found');
  err(await call('DELETE', '/me'), 405, 'method_not_allowed');
  err(await call('POST', '/payments', { raw: '{bad' }), 401, 'unauthenticated');
});

test('reset validation and atomicity (B16, B17)', async () => {
  const t = await world();
  const bad = [
    { currency: 'EUR', minor_units: 2, users: [U('a', 'a', -1)] },
    { currency: 'EUR', minor_units: 2, users: [U('a', 'a', 1.5)] },
    { currency: 'EUR', minor_units: 1, users: [] },
    { currency: 'EUR', users: [] },
    { currency: 'EUR', minor_units: 2, users: [U('a', 'a', 1), U('a', 'b', 1)] },
    { currency: 'EUR', minor_units: 2, users: [U('a', 'a', 1), U('b', 'a', 1)] },
    { currency: 'EUR', minor_units: 2, users: [U('a', 'a', 1)], payments: [{ id: 'p', from_user_id: 'a', to_user_id: 'zz', amount: 1 }] },
    { currency: 'EUR', minor_units: 2, users: [U('a', 'a', 1)], requests: [{ id: 'r', requester_id: 'a', payer_id: 'a', amount: 1, status: 'weird' }] },
    { currency: 'EUR', minor_units: 2, users: [U('a', 'a', 1)], payments: [{ id: 'p', from_user_id: 'a', to_user_id: 'a', amount: 1, visibility: 'x' }] },
  ];
  for (const b of bad) err(await call('POST', '/_test/reset', { body: b }), 422, 'validation_failed');
  err(await call('POST', '/_test/reset', { raw: '{' }), 400, 'malformed_request');
  assert.equal(await bal(t.ada), 10000); // untouched
  assert.equal((await call('POST', '/_test/reset', { body: { currency: 'JPY', minor_units: 0, users: [] }, headers: { Authorization: 'Bearer stale' } })).status, 204);
  err(await get('/me', t.ada), 401, 'unauthenticated');
});

test('payments: success, rejections, amount forms, note verbatim', async () => {
  const t = await world();
  const r = await post('/payments', t.ada, { to_handle: 'bob', amount: 1500, note: 'dinner' });
  assert.equal(r.status, 201);
  assert.equal(r.json.request_id, null); assert.equal(r.json.settlement_id, null);
  assert.equal(r.json.visibility, 'public'); assert.equal(r.json.currency, 'EUR');
  assert.match(r.json.created_at, /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?\+00:00$/);
  assert.equal(await bal(t.ada), 8500); assert.equal(await bal(t.bob), 4000);
  assert.match((await post('/payments', t.ada, { to_handle: 'bob', amount: 1e3 })).text, /"amount":1000[,}]/);
  assert.equal((await post('/payments', t.ada, { to_handle: 'bob', amount: 1000.0 })).status, 201);
  assert.equal((await call('POST', '/payments', { token: t.ada, k: key(), raw: '{"to_handle":"bob","amount":1e3}' })).status, 201);
  for (const amount of [0, -1, 1.5, '5', true, null, 1000000001, 1e400]) {
    const raw = amount === 1e400 ? '{"to_handle":"bob","amount":1e400}' : JSON.stringify({ to_handle: 'bob', amount });
    err(await call('POST', '/payments', { token: t.ada, k: key(), raw }), 422, 'validation_failed');
  }
  err(await post('/payments', t.ada, { to_handle: 'ada', amount: 1 }), 422, 'self_payment');
  err(await post('/payments', t.ada, { to_handle: 'nobody', amount: 1 }), 404, 'not_found');
  err(await post('/payments', t.ada, { amount: 1 }), 422, 'validation_failed');
  err(await post('/payments', t.ada, { to_handle: 5, amount: 1 }), 400, 'malformed_request');
  err(await post('/payments', t.ada, { to_handle: 'bob' }), 422, 'validation_failed');
  for (const note of [null, 5, 'x'.repeat(201)]) err(await post('/payments', t.ada, { to_handle: 'bob', amount: 1, note }), 422, 'validation_failed');
  for (const visibility of ['Public', '', null, 1]) err(await post('/payments', t.ada, { to_handle: 'bob', amount: 1, visibility }), 422, 'validation_failed');
  assert.equal((await post('/payments', t.ada, { to_handle: 'bob', amount: 1, note: '😀'.repeat(200) })).status, 201);
  err(await post('/payments', t.ada, { to_handle: 'bob', amount: 1, note: '😀'.repeat(201) }), 422, 'validation_failed');
  const odd = '  <b>é\u0000 \u{1F600}  ';
  assert.equal((await post('/payments', t.ada, { to_handle: 'bob', amount: 1, note: odd })).json.note, odd);
  const bal0 = await bal(t.cy);
  err(await post('/payments', t.cy, { to_handle: 'bob', amount: bal0 + 1 }), 409, 'insufficient_funds');
  assert.equal((await post('/payments', t.cy, { to_handle: 'bob', amount: bal0 })).status, 201);
  assert.equal(await bal(t.cy), 0);
  err(await call('POST', '/payments', { token: t.ada, raw: '{"to_handle":"bob","amount":1}' }), 400, 'missing_idempotency_key');
  err(await call('POST', '/payments', { token: t.ada, raw: '{}', k: '' }), 400, 'missing_idempotency_key');
  err(await post('/payments', t.ada, { to_handle: 'bob', amount: 1 }, 'x'.repeat(10000)), 422, 'validation_failed');
  assert.equal((await post('/payments', t.ada, { to_handle: 'bob', amount: 1 }, 'x'.repeat(255))).status, 201);
  err(await call('POST', '/payments', { token: t.ada, k: key(), raw: '[1]' }), 400, 'malformed_request');
  err(await call('POST', '/payments', { token: t.ada, k: key(), raw: Buffer.from([0x7b, 0xff, 0x7d]) }), 400, 'malformed_request');
});

test('idempotency semantics (E01-E11)', async () => {
  const t = await world();
  const k = key();
  const b = { to_handle: 'bob', amount: 100 };
  const first = await post('/payments', t.ada, b, k);
  assert.equal(first.status, 201);
  const rep = await call('POST', '/payments', { token: t.ada, k, raw: ' {"amount": 100.0 , "to_handle":"bob"} ' });
  assert.equal(rep.status, 200); assert.deepEqual(rep.json, first.json);
  assert.equal(await bal(t.ada), 9900);
  err(await post('/payments', t.ada, { to_handle: 'bob', amount: 101 }, k), 409, 'idempotency_key_reuse');
  err(await post('/payments', t.ada, { to_handle: 'nobody', amount: -1 }, k), 409, 'idempotency_key_reuse'); // E10
  assert.equal((await post('/payments', t.bob, { to_handle: 'ada', amount: 100 }, k)).status, 201); // E06
  assert.equal((await post('/requests', t.ada, { payer_handle: 'bob', amount: 100 }, k)).status, 201); // E07 other path
  // E05
  const k2 = key();
  err(await post('/payments', t.cy, { to_handle: 'bob', amount: 600 }, k2), 409, 'insufficient_funds');
  await post('/payments', t.ada, { to_handle: 'cy', amount: 1000 });
  assert.equal((await post('/payments', t.cy, { to_handle: 'bob', amount: 600 }, k2)).status, 201);
  assert.equal((await post('/payments', t.cy, { to_handle: 'bob', amount: 600 }, k2)).status, 200);
  // 4xx failed validation claims nothing
  const k3 = key();
  err(await post('/payments', t.ada, { to_handle: 'bob', amount: 0 }, k3), 422, 'validation_failed');
  assert.equal((await post('/payments', t.ada, { to_handle: 'bob', amount: 1 }, k3)).status, 201);
});

test('requests lifecycle (B10, B11, F05-F11, E11)', async () => {
  const t = await world();
  const rq = await post('/requests', t.bob, { payer_handle: 'ada', amount: 20000, note: 'big' });
  assert.equal(rq.status, 201);
  assert.deepEqual(Object.keys(rq.json).sort(), ['amount', 'created_at', 'currency', 'note', 'payer_handle', 'payer_id', 'payment_id', 'request_id', 'requester_handle', 'requester_id', 'status']);
  assert.equal(rq.json.status, 'pending'); assert.equal(rq.json.payment_id, null);
  const id = rq.json.request_id;
  err(await post(`/requests/${id}/pay`, t.ada, {}), 409, 'insufficient_funds');
  err(await post(`/requests/${id}/pay`, t.bob, {}), 403, 'forbidden');
  err(await post(`/requests/${id}/pay`, t.cy, {}), 403, 'forbidden');
  err(await post('/requests/zzz/pay', t.ada, {}), 404, 'not_found');
  err(await post('/requests', t.bob, { payer_handle: 'bob', amount: 5 }), 422, 'self_request');
  err(await post('/requests', t.bob, { payer_handle: 'nobody', amount: 5 }), 404, 'not_found');
  await post('/payments', t.cy, { to_handle: 'ada', amount: 500 });
  await post('/payments', t.bob, { to_handle: 'ada', amount: 2500 });
  // fund ada to 13000? she has 10000+500+2500
  const rq2 = await post('/requests', t.bob, { payer_handle: 'ada', amount: 1200 });
  const k = key();
  const paid = await call('POST', `/requests/${rq2.json.request_id}/pay`, { token: t.ada, k }); // empty body = {}
  assert.equal(paid.status, 201); assert.equal(paid.json.request_id, rq2.json.request_id);
  assert.equal(paid.json.from_handle, 'ada'); assert.equal(paid.json.visibility, 'public');
  const rep = await call('POST', `/requests/${rq2.json.request_id}/pay`, { token: t.ada, k });
  assert.equal(rep.status, 200); assert.deepEqual(rep.json, paid.json);
  err(await post(`/requests/${rq2.json.request_id}/pay`, t.ada, { visibility: 'public' }, k), 409, 'idempotency_key_reuse');
  err(await post(`/requests/${rq2.json.request_id}/pay`, t.ada, {}), 409, 'request_not_pending');
  err(await post(`/requests/${rq2.json.request_id}/decline`, t.ada), 409, 'request_not_pending');
  err(await post(`/requests/${rq2.json.request_id}/cancel`, t.bob), 409, 'request_not_pending');
  const d = await post(`/requests/${id}/decline`, t.ada);
  assert.equal(d.status, 200); assert.equal(d.json.status, 'declined');
  assert.equal((await post(`/requests/${id}/decline`, t.ada)).status, 200);
  err(await post(`/requests/${id}/cancel`, t.bob), 409, 'request_not_pending');
  err(await post(`/requests/${id}/decline`, t.bob), 403, 'forbidden');
  const rq3 = await post('/requests', t.bob, { payer_handle: 'ada', amount: 5 });
  err(await post(`/requests/${rq3.json.request_id}/cancel`, t.ada), 403, 'forbidden');
  assert.equal((await post(`/requests/${rq3.json.request_id}/cancel`, t.bob)).json.status, 'cancelled');
  assert.equal((await post(`/requests/${rq3.json.request_id}/cancel`, t.bob)).status, 200);
  err(await post(`/requests/${rq3.json.request_id}/decline`, t.ada), 409, 'request_not_pending');
  // listing
  const all = await get('/requests', t.ada);
  assert.equal(all.json.requests.length, 3); assert.equal(all.json.requests[0].request_id, rq3.json.request_id);
  assert.equal((await get('/requests?direction=outgoing', t.ada)).json.requests.length, 0);
  assert.equal((await get('/requests?direction=incoming&status=paid', t.bob)).json.requests.length, 0);
  assert.equal((await get('/requests?direction=outgoing&status=paid', t.bob)).json.requests.length, 1);
  assert.equal((await get('/requests', t.cy)).json.requests.length, 0);
  const pg = (await get('/requests?limit=2', t.ada)).json; assert.equal(pg.requests.length, 2); assert.equal(pg.has_more, true);
  const pg2 = (await get('/requests?limit=2&offset=2', t.ada)).json; assert.equal(pg2.requests.length, 1); assert.equal(pg2.has_more, false);
  for (const q of ['limit=0', 'limit=201', 'limit=1e1', 'limit=4.0', 'limit=+4', 'limit=-1', 'limit=abc', 'limit=', 'offset=-1', 'offset=1e9', 'direction=x', 'status=x', 'limit=' + '9'.repeat(400)]) {
    err(await get('/requests?' + q, t.ada), 422, 'validation_failed');
  }
  assert.equal((await get('/requests?offset=' + '9'.repeat(400), t.ada)).json.requests.length, 0);
  assert.equal((await get('/requests?limit=200&bogus=1', t.ada)).status, 200);
  err(await get('/requests?limit=0'), 401, 'unauthenticated');
});

test('feed rule and private visibility (B12, B13, F15)', async () => {
  const t = await world({ settlement_operator_ids: ['u_op'] });
  await post('/payments', t.ada, { to_handle: 'bob', amount: 10, visibility: 'private', note: 'secret' });
  await post('/payments', t.ada, { to_handle: 'bob', amount: 11 });
  await post('/requests', t.bob, { payer_handle: 'ada', amount: 5 });
  const feed = async (tok, q = '') => (await get('/activity' + q, tok)).json;
  assert.equal((await feed(t.ada)).payments.length, 2);
  assert.equal((await feed(t.bob)).payments.length, 2);
  const cy = await feed(t.cy); assert.equal(cy.payments.length, 1); assert.equal(cy.payments[0].amount, 11);
  assert.equal((await feed(t.op)).payments.length, 1);
  assert.equal((await feed(t.ada, '?limit=1')).has_more, true);
  assert.equal((await feed(t.ada, '?direction=zzz')).payments.length, 2);
  err(await get('/activity?limit=0', t.ada), 422, 'validation_failed');
  assert.equal((await get('/requests', t.op)).json.requests.length, 0);
});

test('splits (F12-F14, G01-G03)', async () => {
  const t = await world();
  const split = async (amount, hs, tok = t.ada) => post('/splits', tok, { amount, participant_handles: hs, note: 'n' });
  const rows = [[1000, 3, [334, 333, 333]], [1, 3, [1, 0, 0]], [10, 3, [4, 3, 3]], [999, 3, [333, 333, 333]], [5, 5, [1, 1, 1, 1, 1]]];
  for (const [amount, n, shares] of rows) {
    const r = await split(amount, ['ada', 'bob', 'cy', 'op', 'ada2'].slice(0, n).map((h) => h === 'ada2' ? 'op' : h).slice(0, n));
    if (n === 5) continue;
    assert.deepEqual(r.json.shares.map((s) => s.amount), shares);
  }
  const r = await split(1000, ['bob', 'ada', 'cy']);
  assert.equal(r.status, 201);
  assert.deepEqual(r.json.shares, [{ handle: 'bob', amount: 334 }, { handle: 'ada', amount: 333 }, { handle: 'cy', amount: 333 }]);
  assert.deepEqual(r.json.requests.map((x) => [x.payer_handle, x.amount, x.requester_handle, x.status]), [['bob', 334, 'ada', 'pending'], ['cy', 333, 'ada', 'pending']]);
  const z = await split(1, ['ada', 'bob', 'cy']);
  assert.equal(z.json.requests[0].amount, 0);
  assert.equal((await post(`/requests/${z.json.requests[0].request_id}/pay`, t.bob, {})).status, 201);
  const only = await split(7, ['ada']);
  assert.equal(only.status, 201); assert.deepEqual(only.json.requests, []); assert.equal(only.json.shares[0].amount, 7);
  err(await split(0, ['bob']), 422, 'validation_failed');
  err(await split(5, []), 422, 'validation_failed');
  err(await split(5, ['bob', 'bob']), 422, 'validation_failed');
  err(await split(5, ['bob', 'ghost']), 404, 'not_found');
  err(await post('/splits', t.ada, { amount: 5, participant_handles: 'ada' }), 400, 'malformed_request');
  err(await post('/splits', t.ada, { amount: 5, participant_handles: ['bob'], note: 'x'.repeat(201) }), 422, 'validation_failed');
  err(await post('/splits', t.ada, { amount: 5 }), 422, 'validation_failed');
  err(await split(5, Array.from({ length: 1000 }, (_, i) => 'h' + i)), 404, 'not_found');
  const sum = (await bal(t.ada)) + (await bal(t.bob)) + (await bal(t.cy)) + (await bal(t.op));
  assert.equal(sum, 13000);
});

test('currencies and minor units (B04)', async () => {
  for (const [c, mu] of [['JPY', 0], ['BHD', 3], ['EUR', 2]]) {
    await call('POST', '/_test/reset', { body: { currency: c, minor_units: mu, users: [U('u_a', 'a', 100), U('u_b', 'b', 0)] } });
    const tok = (await call('POST', '/auth/login', { body: { email: 'a@example.com', password: 'correct horse' } })).json.token;
    const me = (await get('/me', tok)).json;
    assert.deepEqual([me.currency, me.minor_units, me.handle, me.user_id, me.display_name], [c, mu, 'a', 'u_a', 'a']);
    assert.equal((await post('/payments', tok, { to_handle: 'b', amount: 1 })).json.currency, c);
  }
});

test('auth (D01-D11)', async () => {
  await world();
  const su = (b) => call('POST', '/auth/signup', { body: b });
  const ok = await su({ email: 'Dee.Ann+tag@example.com', password: '12345678', display_name: 'Dee', extra: 1 });
  assert.equal(ok.status, 201); assert.deepEqual(Object.keys(ok.json).sort(), ['display_name', 'token', 'user_id']);
  assert.equal((await get('/me', ok.json.token)).json.handle, 'dee_ann_tag');
  assert.equal((await get('/me', ok.json.token)).json.balance, 0);
  err(await su({ email: 'Dee.Ann+tag@example.com', password: '12345678', display_name: 'x' }), 409, 'email_taken');
  err(await su({ email: 'dee.ann+tag@example.org', password: '12345678', display_name: 'x' }), 409, 'handle_taken');
  assert.equal((await call('POST', '/auth/login', { body: { email: 'dee.ann+tag@example.org', password: '12345678' } })).status, 401);
  const long = await su({ email: 'abcdefghijklmnopqrstuvwxyz@example.com', password: '12345678', display_name: 'L' });
  assert.equal((await get('/me', long.json.token)).json.handle, 'abcdefghijklmnopqrst');
  err(await su({ email: 'q@example.com', password: '1234567', display_name: 'x' }), 422, 'validation_failed');
  for (const email of ['noat', '@x.com', 'a@', 'a@b@c']) err(await su({ email, password: '12345678', display_name: 'x' }), 422, 'validation_failed');
  err(await su({ email: 'q@example.com', password: '12345678' }), 422, 'validation_failed');
  err(await su({ email: 5, password: '12345678', display_name: 'x' }), 400, 'malformed_request');
  err(await call('POST', '/auth/login', { body: { email: 'ada@example.com', password: 'wrong' } }), 401, 'unauthenticated');
  err(await call('POST', '/auth/login', { body: { email: 'x@y.z', password: 'wrong' } }), 401, 'unauthenticated');
  err(await call('POST', '/auth/login', { body: { email: 'ada@example.com' } }), 422, 'validation_failed');
  const l1 = await call('POST', '/auth/login', { body: { email: 'ada@example.com', password: 'correct horse' } });
  const l2 = await call('POST', '/auth/login', { body: { email: 'ada@example.com', password: 'correct horse' } });
  assert.notEqual(l1.json.token, l2.json.token);
  assert.equal((await get('/me', l1.json.token)).status, 200); assert.equal((await get('/me', l2.json.token)).status, 200);
  for (const h of [undefined, 'Bearer', 'Bearer nope', 'Basic abc']) {
    const r = await call('GET', '/me', { headers: h ? { Authorization: h } : {} });
    err(r, 401, 'unauthenticated');
  }
  for (const [m, p] of [['GET', '/activity'], ['GET', '/requests'], ['POST', '/splits'], ['POST', '/settlements'], ['POST', '/requests/x/decline']]) err(await call(m, p, {}), 401, 'unauthenticated');
});

test('seeded state (B14, B15)', async () => {
  const t = await world({
    payments: [{ id: 'p_1', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 500, note: 'coffee', visibility: 'public' }, { id: 'p_2', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 5, visibility: 'private' }],
    requests: [{ id: 'rq_1', requester_id: 'u_bob', payer_id: 'u_ada', amount: 1200, note: 'taxi', status: 'pending' }, { id: 'rq_2', requester_id: 'u_bob', payer_id: 'u_ada', amount: 1, status: 'declined' }],
  });
  assert.equal(await bal(t.ada), 10000);
  const f = (await get('/activity', t.cy)).json.payments; assert.deepEqual(f.map((p) => p.payment_id), ['p_1']);
  assert.equal(f[0].request_id, null); assert.equal(f[0].settlement_id, null);
  assert.equal((await get('/requests', t.bob)).json.requests.length, 2);
  err(await post('/requests/rq_2/pay', t.ada, {}), 409, 'request_not_pending');
  const p = await post('/requests/rq_1/pay', t.ada, {});
  assert.equal(p.status, 201);
  assert.notEqual(p.json.payment_id, 'p_1');
  const nr = await post('/requests', t.bob, { payer_handle: 'ada', amount: 1 });
  assert.ok(!['rq_1', 'rq_2'].includes(nr.json.request_id));
});

test('settlements (I01-I10)', async () => {
  const t = await world({ settlement_operator_ids: ['u_op', 'u_ghost'] });
  const st = (tok, transfers, k) => post('/settlements', tok, { transfers }, k);
  err(await call('POST', '/settlements', { body: { transfers: [] } }), 401, 'unauthenticated');
  err(await st(t.ada, [{ from_handle: 'ada', to_handle: 'bob', amount: 1 }]), 403, 'forbidden');
  err(await call('POST', '/settlements', { token: t.op, raw: '{"transfers":[{"from_handle":"ada","to_handle":"bob","amount":1}]}' }), 400, 'missing_idempotency_key');
  for (const bad of [undefined, 'x', [], Array.from({ length: 33 }, () => ({ from_handle: 'ada', to_handle: 'bob', amount: 1 })), [5]]) {
    err(await post('/settlements', t.op, bad === undefined ? {} : { transfers: bad }), 422, 'validation_failed');
  }
  err(await st(t.op, [{ from_handle: 'ada', to_handle: 'zz', amount: 1 }, { from_handle: 'ada', to_handle: 'ada', amount: 1 }]), 404, 'not_found');
  err(await st(t.op, [{ from_handle: 'ada', to_handle: 'ada', amount: 1 }]), 422, 'self_payment');
  err(await st(t.op, [{ from_handle: 'ada', to_handle: 'bob', amount: 0 }]), 422, 'validation_failed');
  err(await st(t.op, [{ from_handle: 'cy', to_handle: 'bob', amount: 99999999 }, { from_handle: 'ada', to_handle: 'bob', amount: 'x' }]), 422, 'validation_failed');
  err(await st(t.op, [{ from_handle: 'ada', to_handle: 'bob', amount: 1, visibility: 'x' }]), 422, 'validation_failed');
  err(await st(t.op, [{ from_handle: 7, to_handle: 'bob', amount: 1 }]), 422, 'validation_failed');
  // chain through the empty op wallet
  const k = key();
  const ok = await st(t.op, [{ from_handle: 'ada', to_handle: 'op', amount: 100, visibility: 'private', note: 'a' }, { from_handle: 'op', to_handle: 'cy', amount: 100, junk: 1 }], k);
  assert.equal(ok.status, 201, ok.text);
  assert.equal(ok.json.payments.length, 2);
  for (const p of ok.json.payments) { assert.equal(p.settlement_id, ok.json.settlement_id); assert.equal(p.request_id, null); assert.equal(p.created_at, ok.json.committed_at); }
  assert.equal(ok.json.payments[0].visibility, 'private'); assert.equal(ok.json.payments[1].visibility, 'public');
  assert.equal(await bal(t.op), 0); assert.equal(await bal(t.ada), 9900); assert.equal(await bal(t.cy), 600);
  const rep = await call('POST', '/settlements', { token: t.op, k, body: { transfers: [{ from_handle: 'ada', to_handle: 'op', amount: 100, visibility: 'private', note: 'a' }, { from_handle: 'op', to_handle: 'cy', amount: 100, junk: 1 }] } });
  assert.equal(rep.status, 200); assert.deepEqual(rep.json, ok.json);
  assert.equal((await get('/activity', t.op)).json.payments.length, 2); // op is party to both
  assert.equal((await get('/activity', t.bob)).json.payments.length, 1);
  // unaffordable leg rolls back everything and claims no key
  const k2 = key();
  err(await st(t.op, [{ from_handle: 'ada', to_handle: 'bob', amount: 10 }, { from_handle: 'cy', to_handle: 'bob', amount: 601 }], k2), 409, 'insufficient_funds');
  assert.equal(await bal(t.ada), 9900);
  assert.equal((await st(t.op, [{ from_handle: 'ada', to_handle: 'bob', amount: 10 }], k2)).status, 201);
  assert.equal((await get('/requests', t.op)).json.requests.length, 0);
});

test('export / import (H01-H08)', async () => {
  const t = await world({ settlement_operator_ids: ['u_op'] });
  const k = key(), kfail = key();
  const pay = await post('/payments', t.ada, { to_handle: 'bob', amount: 100, visibility: 'private' }, k);
  await post('/requests', t.bob, { payer_handle: 'ada', amount: 70 });
  err(await post('/payments', t.cy, { to_handle: 'bob', amount: 9999 }, kfail), 409, 'insufficient_funds');
  const e1 = await get('/_test/export');
  assert.equal(e1.status, 200); assert.equal(e1.json.track, 'pocketful'); assert.equal(e1.json.format_version, 1);
  assert.ok(!e1.text.includes('correct horse'));
  await post('/payments', t.ada, { to_handle: 'bob', amount: 5 });
  assert.equal((await call('POST', '/_test/import', { body: e1.json })).status, 204);
  assert.equal((await call('POST', '/_test/import', { body: e1.json })).status, 204);
  assert.deepEqual((await get('/_test/export')).json, e1.json);
  assert.equal(await bal(t.ada), 9900);
  const rep = await post('/payments', t.ada, { to_handle: 'bob', amount: 100, visibility: 'private' }, k);
  assert.equal(rep.status, 200); assert.deepEqual(rep.json, pay.json);
  err(await post('/payments', t.ada, { to_handle: 'bob', amount: 101 }, k), 409, 'idempotency_key_reuse');
  assert.equal((await post('/payments', t.cy, { to_handle: 'bob', amount: 10 }, kfail)).status, 201);
  const nxt = await post('/payments', t.ada, { to_handle: 'bob', amount: 1 });
  assert.notEqual(nxt.json.payment_id, pay.json.payment_id);
  assert.equal((await call('POST', '/auth/login', { body: { email: 'ada@example.com', password: 'correct horse' } })).status, 200);
  assert.equal((await post('/settlements', t.op, [{}].length && { transfers: [{ from_handle: 'ada', to_handle: 'bob', amount: 1 }] })).status, 201);
  // invalid imports leave state alone
  err(await call('POST', '/_test/import', { raw: '{' }), 400, 'malformed_request');
  for (const bad of [{}, { track: 'x', format_version: 1, state: e1.json.state }, { track: 'pocketful', format_version: 2, state: e1.json.state }, { track: 'pocketful', format_version: 1 }, { track: 'pocketful', format_version: 1, state: { users: [] } }, { track: 'pocketful', format_version: 1, state: { ...e1.json.state, users: [{ ...e1.json.state.users[0], balance: -1 }] } }]) {
    err(await call('POST', '/_test/import', { body: bad }), 422, 'validation_failed');
  }
  assert.equal((await get('/me', t.ada)).status, 200);
  // import replaces credentials
  await call('POST', '/_test/reset', { body: { currency: 'EUR', minor_units: 2, users: [U('u_z', 'zed', 1)] } });
  err(await get('/me', t.ada), 401, 'unauthenticated');
  assert.equal((await call('POST', '/_test/import', { body: e1.json })).status, 204);
  assert.equal((await get('/me', t.ada)).status, 200);
  const e2 = await get('/_test/export');
  assert.deepEqual(e2.json, e1.json);
});

test('concurrency: drain, double pay, idempotent bursts (B02, B03, E08, I10)', async () => {
  const t = await world({ settlement_operator_ids: ['u_op'] });
  const rs = await Promise.all(Array.from({ length: 50 }, () => post('/payments', t.cy, { to_handle: 'bob', amount: 100 })));
  assert.equal(rs.filter((r) => r.status === 201).length, 5);
  assert.ok(rs.filter((r) => r.status !== 201).every((r) => r.status === 409 && r.json.error.code === 'insufficient_funds'));
  assert.equal(await bal(t.cy), 0);
  const rq = (await post('/requests', t.bob, { payer_handle: 'ada', amount: 100 })).json.request_id;
  const ps = await Promise.all(Array.from({ length: 50 }, () => post(`/requests/${rq}/pay`, t.ada, {})));
  assert.equal(ps.filter((r) => r.status === 201).length, 1);
  assert.ok(ps.filter((r) => r.status !== 201).every((r) => r.json.error.code === 'request_not_pending'));
  const rq2 = (await post('/requests', t.bob, { payer_handle: 'ada', amount: 100 })).json.request_id;
  const mix = await Promise.all(Array.from({ length: 30 }, (_, i) => i % 3 === 0 ? post(`/requests/${rq2}/pay`, t.ada, {}) : i % 3 === 1 ? post(`/requests/${rq2}/decline`, t.ada) : post(`/requests/${rq2}/cancel`, t.bob)));
  const fin = (await get('/requests?status=paid', t.bob)).json.requests.length + (await get('/requests?status=declined', t.bob)).json.requests.length + (await get('/requests?status=cancelled', t.bob)).json.requests.length;
  assert.equal(fin, 2); // rq (paid) + rq2 (exactly one terminal state)
  const k = key();
  const same = await Promise.all(Array.from({ length: 50 }, () => post('/payments', t.ada, { to_handle: 'bob', amount: 7 }, k)));
  assert.equal(same.filter((r) => r.status === 201).length, 1);
  assert.equal(same.filter((r) => r.status === 200).length, 49);
  const ks = key();
  const sp = await Promise.all(Array.from({ length: 50 }, () => post('/splits', t.ada, { amount: 9, participant_handles: ['bob', 'cy'] }, ks)));
  assert.equal(sp.filter((r) => r.status === 201).length, 1);
  assert.equal((await get('/requests?direction=outgoing&limit=200', t.ada)).json.requests.length, 2);
  const kst = key();
  const sets = await Promise.all(Array.from({ length: 50 }, () => post('/settlements', t.op, { transfers: [{ from_handle: 'ada', to_handle: 'op', amount: 5 }, { from_handle: 'op', to_handle: 'bob', amount: 5 }] }, kst)));
  assert.equal(sets.filter((r) => r.status === 201).length, 1);
  const total = (await bal(t.ada)) + (await bal(t.bob)) + (await bal(t.cy)) + (await bal(t.op));
  assert.equal(total, 13000);
  const logins = await Promise.all(Array.from({ length: 50 }, () => call('POST', '/auth/login', { body: { email: 'ada@example.com', password: 'correct horse' } })));
  assert.ok(logins.every((r) => r.status === 200));
});

test('awkward input never 5xx (C10)', async () => {
  const t = await world();
  const deep = '['.repeat(100000) + ']'.repeat(100000);
  for (const raw of [deep, '{"to_handle":"bob","amount":1e400}', '{"to_handle":"\\ud800","amount":1}', '{"to_handle":"b\\u0000","amount":1}', '{"note":"\\ud83d","to_handle":"bob","amount":1}', '', 'null', '{"a":' + deep + '}']) {
    const r = await call('POST', '/payments', { token: t.ada, k: key(), raw });
    assert.ok(r.status < 500, raw.slice(0, 40) + r.text);
  }
  const big = await call('POST', '/payments', { token: t.ada, k: key(), raw: JSON.stringify({ to_handle: 'bob', amount: 1, junk: 'x'.repeat(2e6) }) });
  assert.equal(big.status, 201);
  for (const p of ['/deposits', '/topups', '/withdrawals', '/admin/balance', '/_test/balance']) err(await call('POST', p, { token: t.ada, body: {} }), 404, 'not_found');
  assert.equal((await call('GET', '/requests/%E0%A4', { token: t.ada })).status, 404);
  err(await post('/requests/%E0%A4/pay', t.ada, {}), 404, 'not_found');
});
