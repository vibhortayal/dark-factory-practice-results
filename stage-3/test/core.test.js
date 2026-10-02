'use strict';

const { test, before, after, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const h = require('./helpers');
const { call } = h;

let t;
before(h.start);
after(h.stop);
beforeEach(async () => {
  await h.reset();
  t = await h.tokens();
});

const err = (r, status, code) => {
  assert.equal(r.status, status, r.text);
  assert.equal(r.body.error.code, code);
  assert.equal(typeof r.body.error.message, 'string');
};

test('health, content type and unknown routes', async () => {
  const r = await call('GET', '/health');
  assert.deepEqual(r.body, { status: 'ok' });
  assert.equal(r.headers.get('content-type'), 'application/json; charset=utf-8');
  err(await call('GET', '/nope'), 404, 'not_found');
  err(await call('DELETE', '/health'), 404, 'not_found');
  err(await call('GET', '/me'), 401, 'unauthenticated');
  err(await call('GET', '/me', { headers: { Authorization: 'Basic abc' } }), 401, 'unauthenticated');
  err(await call('GET', '/me', { token: 'bogus' }), 401, 'unauthenticated');
});

test('reset: seeded state, balances final, bad fixtures change nothing', async () => {
  const me = await call('GET', '/me', { token: t.ada });
  assert.deepEqual(me.body, { user_id: 'u_ada', display_name: 'Ada', handle: 'ada', balance: 10000, total: 10000, available: 10000, held: 0, currency: 'EUR', minor_units: 2 });
  const bad = { ...h.FIXTURE, users: [{ ...h.FIXTURE.users[0], balance: -1 }] };
  err(await call('POST', '/_test/reset', { body: bad }), 422, 'validation_failed');
  err(await call('POST', '/_test/reset', { body: '{nope' }), 400, 'malformed_request');
  err(await call('POST', '/_test/reset', { body: [] }), 422, 'validation_failed');
  err(await call('POST', '/_test/reset', { body: { users: [h.FIXTURE.users[0], h.FIXTURE.users[0]] } }), 422, 'validation_failed');
  err(await call('POST', '/_test/reset', { body: { minor_units: 4, users: [] } }), 422, 'validation_failed');
  assert.equal((await call('GET', '/me', { token: t.ada })).body.balance, 10000);
  await h.reset({ currency: 'JPY', minor_units: 0, users: [h.FIXTURE.users[0]] });
  err(await call('GET', '/me', { token: t.ada }), 401, 'unauthenticated');
  const jpy = await call('GET', '/me', { token: await h.login('ada@example.com') });
  assert.equal(jpy.body.currency, 'JPY');
  assert.equal(jpy.body.minor_units, 0);
});

test('signup derives handle, rejects duplicates and bad input', async () => {
  const su = (email, extra = {}) => call('POST', '/auth/signup', { body: { email, password: 'longenough', display_name: 'X', ...extra } });
  const ok = await su('Dee.Ann+tag@Example.com', { handle: 'ignored' });
  assert.equal(ok.status, 201);
  const me = await call('GET', '/me', { token: ok.body.token });
  assert.equal(me.body.handle, 'dee_ann_tag');
  assert.equal(me.body.balance, 0);
  err(await su('Dee.Ann+tag@Example.com'), 409, 'email_taken');
  err(await su('dee.ann+tag@other.com'), 409, 'handle_taken');
  assert.equal((await call('POST', '/auth/login', { body: { email: 'dee.ann+tag@other.com', password: 'longenough' } })).status, 401);
  err(await su('ada@other.com'), 409, 'handle_taken');
  assert.equal((await su('a'.repeat(30) + '@x.io')).status, 201);
  assert.equal((await call('GET', '/me', { token: (await call('POST', '/auth/login', { body: { email: 'a'.repeat(30) + '@x.io', password: 'longenough' } })).body.token })).body.handle, 'a'.repeat(20));
  err(await su('nodomain'), 422, 'validation_failed');
  err(await su('@x.io'), 422, 'validation_failed');
  err(await su('a@'), 422, 'validation_failed');
  err(await call('POST', '/auth/signup', { body: { email: 'z@x.io', password: 'short', display_name: 'Z' } }), 422, 'validation_failed');
  err(await call('POST', '/auth/signup', { body: { email: 5, password: 'longenough', display_name: 'Z' } }), 400, 'malformed_request');
  err(await call('POST', '/auth/signup', { body: { email: 'z@x.io', display_name: 'Z' } }), 422, 'validation_failed');
  const a = await call('POST', '/auth/login', { body: { email: 'ada@example.com', password: 'correct horse' } });
  const b = await call('POST', '/auth/login', { body: { email: 'ada@example.com', password: 'correct horse' } });
  assert.notEqual(a.body.token, b.body.token);
  assert.equal((await call('GET', '/me', { token: a.body.token })).status, 200);
  err(await call('POST', '/auth/login', { body: { email: 'ada@example.com', password: 'wrong' } }), 401, 'unauthenticated');
});

test('payments: shape, atomicity, errors and precedence', async () => {
  const pay = (body, token = t.ada, key = Math.random().toString()) => call('POST', '/payments', { token, key, body });
  const r = await pay({ to_handle: 'bob', amount: 1500, note: 'dinner 🍝', visibility: 'private' });
  assert.equal(r.status, 201);
  assert.deepEqual(Object.keys(r.body), ['payment_id', 'from_user_id', 'from_handle', 'to_user_id', 'to_handle', 'amount', 'currency', 'note', 'visibility', 'request_id', 'settlement_id', 'authorization_id', 'created_at']);
  assert.equal(r.body.note, 'dinner 🍝');
  assert.match(r.body.created_at, /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d{3})?\+00:00$/);
  assert.deepEqual(await h.balances(t), { ada: 8500, bob: 4000, cy: 0 });
  err(await pay({ to_handle: 'bob', amount: 8501 }), 409, 'insufficient_funds');
  assert.equal((await pay({ to_handle: 'bob', amount: 8500 })).status, 201);
  assert.equal((await h.balances(t)).ada, 0);
  err(await pay({ to_handle: 'bob', amount: 1 }), 409, 'insufficient_funds');
  assert.deepEqual(await h.balances(t), { ada: 0, bob: 12500, cy: 0 });
});

test('payments: validation rules', async () => {
  const pay = (body, key = Math.random().toString()) => call('POST', '/payments', { token: t.ada, key, body });
  const v = (body) => pay({ to_handle: 'bob', amount: 10, ...body });
  assert.equal((await v({ amount: 1000.0 })).status, 201);
  assert.equal((await pay('{"to_handle":"bob","amount":1e3}')).status, 201);
  assert.equal((await v({ amount: 1000000000 })).status, 409);
  for (const amount of [0, -1, 1000000001, 1.5, '10', true, null, [], {}]) err(await v({ amount }), 422, 'validation_failed');
  err(await pay('{"to_handle":"bob","amount":1e400}'), 422, 'validation_failed');
  err(await pay({ to_handle: 'bob' }), 422, 'validation_failed');
  err(await pay({ amount: 5 }), 422, 'validation_failed');
  for (const to_handle of [5, null, [], {}]) err(await v({ to_handle }), 400, 'malformed_request');
  for (const note of [5, null, 'x'.repeat(201), '😀'.repeat(201)]) err(await v({ note }), 422, 'validation_failed');
  assert.equal((await v({ note: '😀'.repeat(200) })).status, 201);
  assert.equal((await v({ note: '  <b>&amp;  ' })).body.note, '  <b>&amp;  ');
  for (const visibility of [null, '', 'Public', 5, 'friends']) err(await v({ visibility }), 422, 'validation_failed');
  err(await v({ to_handle: 'ada' }), 422, 'self_payment');
  for (const to_handle of ['nobody', '', 'ADA', '@ada']) err(await v({ to_handle }), 404, 'not_found');
  err(await v({ to_handle: 'ghost', amount: 0 }), 422, 'validation_failed');
  err(await v({ to_handle: 'ghost', amount: 10 ** 9 }), 404, 'not_found');
  assert.equal((await v({ extra: 1 })).status, 201);
  err(await pay('[]'), 400, 'malformed_request');
  err(await pay('"x"'), 400, 'malformed_request');
  err(await pay('null'), 400, 'malformed_request');
  err(await pay(''), 400, 'malformed_request');
  err(await pay('{bad'), 400, 'malformed_request');
  err(await pay(Buffer.from([0x7b, 0xff, 0x7d])), 400, 'malformed_request');
  assert.equal((await call('POST', '/payments', { token: t.ada, key: 'ct', body: '{"to_handle":"bob","amount":1}', headers: { 'Content-Type': 'text/plain' } })).status, 201);
});

test('idempotency key rules and ordering', async () => {
  const pay = (key, body, token = t.ada, path = '/payments') => call('POST', path, { token, key, body });
  const body = { to_handle: 'bob', amount: 100 };
  err(await call('POST', '/payments', { token: t.ada, body }), 400, 'missing_idempotency_key');
  err(await pay('', body), 400, 'missing_idempotency_key');
  err(await pay('k'.repeat(256), body), 422, 'validation_failed');
  const first = await pay('k'.repeat(255), body);
  assert.equal(first.status, 201);
  const replay = await pay('k'.repeat(255), { amount: 100, to_handle: 'bob' });
  assert.equal(replay.status, 200);
  assert.deepEqual(replay.body, first.body);
  assert.equal((await pay('k'.repeat(255), '{"to_handle":"bob","amount":1e2}')).status, 200);
  err(await pay('k'.repeat(255), { ...body, extra: 1 }), 409, 'idempotency_key_reuse');
  err(await pay('k'.repeat(255), { to_handle: 'bob', amount: -5 }), 409, 'idempotency_key_reuse');
  err(await pay('k'.repeat(255), { to_handle: 'nobody', amount: 5 }), 409, 'idempotency_key_reuse');
  assert.equal((await h.balances(t)).ada, 9900);
  // other user, same key string: independent
  assert.equal((await pay('k'.repeat(255), { to_handle: 'ada', amount: 100 }, t.bob)).status, 201);
  // same key on another path is a first use
  assert.equal((await pay('k'.repeat(255), { payer_handle: 'bob', amount: 100 }, t.ada, '/requests')).status, 201);
  // a key whose first attempt failed with 4xx is still free
  err(await pay('fail', { to_handle: 'bob', amount: 10 ** 12 }), 422, 'validation_failed');
  assert.equal((await pay('fail', body)).status, 201);
  err(await pay('bad', { to_handle: 'nobody', amount: 1 }), 404, 'not_found');
  assert.equal((await pay('bad', { to_handle: 'cy', amount: 1 })).status, 201);
  // unauthenticated is checked before the key
  err(await call('POST', '/payments', { body }), 401, 'unauthenticated');
});

test('requests: lifecycle, pay replay, permissions, visibility', async () => {
  const k = () => Math.random().toString();
  const rq = await call('POST', '/requests', { token: t.cy, key: k(), body: { payer_handle: 'bob', amount: 3000, note: 'big' } });
  assert.equal(rq.status, 201);
  assert.deepEqual(Object.keys(rq.body), ['request_id', 'requester_id', 'requester_handle', 'payer_id', 'payer_handle', 'amount', 'currency', 'note', 'status', 'payment_id', 'created_at']);
  const id = rq.body.request_id;
  const pay = (token, key, body) => call('POST', `/requests/${id}/pay`, { token, key, body });
  err(await pay(t.bob, k(), {}), 409, 'insufficient_funds');
  assert.equal((await call('GET', '/requests', { token: t.bob })).body.requests.find((r) => r.request_id === id).status, 'pending');
  err(await pay(t.cy, k(), {}), 403, 'forbidden');
  err(await pay(t.ada, k(), {}), 403, 'forbidden');
  err(await call('POST', '/requests/nope/pay', { token: t.bob, key: k(), body: {} }), 404, 'not_found');
  err(await pay(t.bob, k(), { visibility: 'x' }), 422, 'validation_failed');
  await call('POST', '/payments', { token: t.ada, key: k(), body: { to_handle: 'bob', amount: 1000 } });
  const first = await pay(t.bob, 'pk', { visibility: 'private' });
  assert.equal(first.status, 201);
  assert.equal(first.body.request_id, id);
  assert.equal(first.body.visibility, 'private');
  assert.equal(first.body.note, 'big');
  assert.deepEqual(await h.balances(t), { ada: 9000, bob: 500, cy: 3000 });
  const replay = await pay(t.bob, 'pk', { visibility: 'private' });
  assert.equal(replay.status, 200);
  assert.deepEqual(replay.body, first.body);
  err(await pay(t.bob, 'pk', {}), 409, 'idempotency_key_reuse');
  err(await pay(t.bob, k(), {}), 409, 'request_not_pending');
  err(await call('POST', `/requests/${id}/decline`, { token: t.bob }), 409, 'request_not_pending');
  err(await call('POST', `/requests/${id}/cancel`, { token: t.cy }), 409, 'request_not_pending');
  // private payment: visible to the parties only
  const feed = async (tok) => (await call('GET', '/activity', { token: tok })).body.payments.map((p) => p.payment_id);
  assert.ok((await feed(t.bob)).includes(first.body.payment_id));
  assert.ok((await feed(t.cy)).includes(first.body.payment_id));
  assert.ok(!(await feed(t.ada)).includes(first.body.payment_id));
  // requests never in the feed; seeded request only for its parties
  assert.ok(!(await call('GET', '/activity', { token: t.ada })).text.includes('"status"'));
  assert.equal((await call('GET', '/requests', { token: t.cy })).body.requests.some((r) => r.request_id === 'rq_1'), false);
  // decline / cancel semantics
  assert.equal((await call('POST', '/requests/rq_1/decline', { token: t.ada })).body.status, 'declined');
  assert.equal((await call('POST', '/requests/rq_1/decline', { token: t.ada, body: 'garbage' })).status, 200);
  err(await call('POST', '/requests/rq_1/cancel', { token: t.bob }), 409, 'request_not_pending');
  err(await call('POST', '/requests/rq_1/decline', { token: t.bob }), 403, 'forbidden');
  const r2 = await call('POST', '/requests', { token: t.bob, key: k(), body: { payer_handle: 'ada', amount: 5 } });
  err(await call('POST', `/requests/${r2.body.request_id}/cancel`, { token: t.ada }), 403, 'forbidden');
  assert.equal((await call('POST', `/requests/${r2.body.request_id}/cancel`, { token: t.bob })).body.status, 'cancelled');
  assert.equal((await call('POST', `/requests/${r2.body.request_id}/cancel`, { token: t.bob })).status, 200);
  err(await call('POST', `/requests/${r2.body.request_id}/pay`, { token: t.ada, key: k(), body: {} }), 409, 'request_not_pending');
  err(await call('POST', '/requests', { token: t.bob, key: k(), body: { payer_handle: 'bob', amount: 5 } }), 422, 'self_request');
  err(await call('POST', '/requests', { token: t.bob, key: k(), body: { payer_handle: 'zzz', amount: 5 } }), 404, 'not_found');
});

test('request listing: filters, paging and parameter rules', async () => {
  const k = () => Math.random().toString();
  for (let i = 0; i < 5; i++) await call('POST', '/requests', { token: t.bob, key: k(), body: { payer_handle: 'ada', amount: i + 1, note: `n${i}` } });
  const list = (q, tok = t.ada) => call('GET', `/requests${q}`, { token: tok });
  const all = await list('');
  assert.equal(all.body.requests.length, 6);
  assert.equal(all.body.requests[0].note, 'n4');
  assert.equal((await list('?limit=2&offset=1')).body.requests.map((r) => r.note).join(), 'n3,n2');
  assert.equal((await list('?limit=2&offset=4')).body.has_more, false);
  assert.equal((await list('?limit=2&offset=3')).body.has_more, true);
  assert.deepEqual((await list('?offset=99')).body, { requests: [], has_more: false });
  assert.equal((await list('?direction=outgoing')).body.requests.length, 0);
  assert.equal((await list('?direction=incoming&status=pending&junk=1')).body.requests.length, 6);
  assert.equal((await list('?status=paid')).body.requests.length, 0);
  for (const q of ['limit=0', 'limit=201', 'limit=-5', 'limit=abc', 'limit=1e2', 'limit=4.0', 'limit=%2B4', 'limit=', 'offset=-1', 'offset=1.0', 'direction=sideways', 'direction=', 'status=open', 'status=']) {
    err(await list(`?${q}`), 422, 'validation_failed');
  }
  assert.equal((await list('?limit=200')).status, 200);
  err(await call('GET', '/activity?limit=0', { token: t.ada }), 422, 'validation_failed');
  assert.equal((await call('GET', '/activity?direction=bogus', { token: t.ada })).status, 200);
});

test('splits: rounding, shapes and errors', async () => {
  const split = (body, token = t.ada, key = Math.random().toString()) => call('POST', '/splits', { token, key, body });
  const shares = async (amount, handles) => (await split({ amount, participant_handles: handles })).body.shares.map((s) => s.amount);
  assert.deepEqual(await shares(1000, ['ada', 'bob', 'cy']), [334, 333, 333]);
  assert.deepEqual(await shares(1, ['ada', 'bob', 'cy']), [1, 0, 0]);
  assert.deepEqual(await shares(10, ['bob', 'cy', 'ada']), [4, 3, 3]);
  assert.deepEqual(await shares(999, ['ada', 'bob', 'cy']), [333, 333, 333]);
  assert.deepEqual(await shares(1, ['cy', 'bob', 'ada']), [1, 0, 0]);
  const r = await split({ amount: 1, participant_handles: ['ada', 'bob', 'cy'], note: 'x' });
  assert.deepEqual(r.body.requests.map((q) => [q.payer_handle, q.amount, q.status, q.note, q.requester_handle]), [['bob', 0, 'pending', 'x', 'ada'], ['cy', 0, 'pending', 'x', 'ada']]);
  assert.deepEqual(Object.keys(r.body), ['split_id', 'amount', 'currency', 'note', 'shares', 'requests', 'created_at']);
  // caller omitted: divided among listed only
  const o = await split({ amount: 1001, participant_handles: ['bob', 'cy'] });
  assert.deepEqual(o.body.shares, [{ handle: 'bob', amount: 501 }, { handle: 'cy', amount: 500 }]);
  assert.equal(o.body.requests.length, 2);
  const solo = await split({ amount: 50, participant_handles: ['ada'] });
  assert.equal(solo.status, 201);
  assert.deepEqual(solo.body.requests, []);
  assert.deepEqual(solo.body.shares, [{ handle: 'ada', amount: 50 }]);
  // zero share can be paid and moves nothing
  const zero = r.body.requests[0].request_id;
  const paid = await call('POST', `/requests/${zero}/pay`, { token: t.bob, key: 'z', body: {} });
  assert.equal(paid.status, 201);
  assert.equal(paid.body.amount, 0);
  // no balance moved and splits are not feed items
  assert.deepEqual(await h.balances(t), { ada: 10000, bob: 2500, cy: 0 });
  assert.equal((await call('GET', '/activity', { token: t.ada })).body.payments.length, 2);
  const bad = (body) => split(body);
  err(await bad({ amount: 0, participant_handles: ['bob'] }), 422, 'validation_failed');
  err(await bad({ amount: 10, participant_handles: [] }), 422, 'validation_failed');
  err(await bad({ amount: 10, participant_handles: ['bob', 'bob'] }), 422, 'validation_failed');
  err(await bad({ amount: 10, participant_handles: ['bob', 'ghost'] }), 404, 'not_found');
  err(await bad({ amount: 10, participant_handles: 'bob' }), 400, 'malformed_request');
  err(await bad({ amount: 10, participant_handles: ['bob', 3] }), 400, 'malformed_request');
  err(await bad({ amount: 10 }), 422, 'validation_failed');
  err(await bad({ amount: 10, participant_handles: ['bob'], note: 'x'.repeat(201) }), 422, 'validation_failed');
  err(await bad({ amount: 10, participant_handles: ['ghost', 'bob', 'bob'] }), 422, 'validation_failed');
  const requestsBefore = (await call('GET', '/requests?limit=200', { token: t.ada })).body.requests.length;
  err(await bad({ amount: 10, participant_handles: ['bob', 'ghost'] }), 404, 'not_found');
  assert.equal((await call('GET', '/requests?limit=200', { token: t.ada })).body.requests.length, requestsBefore);
  const many = Array.from({ length: 1000 }, (_, i) => `u${i}`);
  err(await bad({ amount: 10, participant_handles: many }), 404, 'not_found');
  err(await bad({ amount: 10, participant_handles: [...many, 'u1'] }), 422, 'validation_failed');
});

test('settlements: permissions, net affordability, atomicity, visibility, replay', async () => {
  const st = (body, token = t.cy, key = Math.random().toString()) => call('POST', '/settlements', { token, key, body });
  const tr = (from_handle, to_handle, amount, extra = {}) => ({ from_handle, to_handle, amount, ...extra });
  err(await call('POST', '/settlements', { key: 'a', body: {} }), 401, 'unauthenticated');
  err(await st({ transfers: [tr('ada', 'bob', 1)] }, t.ada), 403, 'forbidden');
  err(await call('POST', '/settlements', { token: t.ada, body: {} }), 403, 'forbidden');
  const su = await call('POST', '/auth/signup', { body: { email: 'new@x.io', password: 'longenough', display_name: 'N' } });
  err(await st({ transfers: [tr('ada', 'bob', 1)] }, su.body.token), 403, 'forbidden');
  err(await call('POST', '/settlements', { token: t.cy, body: { transfers: [tr('ada', 'bob', 1)] } }), 400, 'missing_idempotency_key');
  for (const transfers of [undefined, 'x', [], Array.from({ length: 33 }, () => tr('ada', 'bob', 1)), [5], [null]]) {
    err(await st({ transfers }), 422, 'validation_failed');
  }
  assert.equal((await st({ transfers: Array.from({ length: 32 }, () => tr('ada', 'bob', 1)) })).status, 201);
  const before = await h.balances(t);
  // chain through bob/cy where cy starts at 0
  const chain = await st({ transfers: [tr('cy', 'bob', 100), tr('ada', 'cy', 100, { visibility: 'private', note: 'n' })] });
  assert.equal(chain.status, 201);
  assert.deepEqual(Object.keys(chain.body), ['settlement_id', 'committed_at', 'payments']);
  assert.equal(chain.body.payments.length, 2);
  for (const p of chain.body.payments) {
    assert.equal(p.settlement_id, chain.body.settlement_id);
    assert.equal(p.created_at, chain.body.committed_at);
    assert.equal(p.request_id, null);
  }
  assert.deepEqual(await h.balances(t), { ada: before.ada - 100, bob: before.bob + 100, cy: before.cy });
  // visibility: operator cy is a party of both; ada/bob parties of one
  const feedIds = async (tok) => (await call('GET', '/activity', { token: tok })).body.payments.map((p) => p.payment_id);
  const [pub, priv] = chain.body.payments.map((p) => p.payment_id);
  assert.ok((await feedIds(t.bob)).includes(pub) && !(await feedIds(t.bob)).includes(priv));
  assert.ok((await feedIds(t.ada)).includes(priv));
  // operator not party sees a public one but not a private one
  const third = await st({ transfers: [tr('ada', 'bob', 5, { visibility: 'private' }), tr('ada', 'bob', 5)] });
  const [tp, tpub] = third.body.payments.map((p) => p.payment_id);
  assert.ok(!(await feedIds(t.cy)).includes(tp) && (await feedIds(t.cy)).includes(tpub));
  assert.equal((await call('GET', '/requests', { token: t.cy })).body.requests.length, 0);
  err(await call('POST', '/requests/rq_1/decline', { token: t.cy }), 403, 'forbidden');
  // not affordable: nothing changes, key not claimed
  const snap = await h.balances(t);
  const k = 'unaff';
  err(await st({ transfers: [tr('cy', 'ada', 1), tr('ada', 'bob', 999999)] }, t.cy, k), 409, 'insufficient_funds');
  err(await st({ transfers: [tr('bob', 'ada', 5000), tr('ada', 'cy', 1)] }, t.cy, k), 409, 'insufficient_funds');
  assert.deepEqual(await h.balances(t), snap);
  // entry errors first, in input order, before funds
  err(await st({ transfers: [tr('ada', 'bob', 10 ** 8), tr('ada', 'ghost', 1)] }), 404, 'not_found');
  err(await st({ transfers: [tr('ada', 'ada', 1), tr('ada', 'ghost', 1)] }), 422, 'self_payment');
  err(await st({ transfers: [tr('ada', 'ghost', 1), tr('ada', 'ada', 1)] }), 404, 'not_found');
  err(await st({ transfers: [tr('ada', 'bob', 0)] }), 422, 'validation_failed');
  err(await st({ transfers: [tr(5, 'bob', 1)] }), 400, 'malformed_request');
  err(await st({ transfers: [{ to_handle: 'bob', amount: 1 }] }), 422, 'validation_failed');
  err(await st({ transfers: [tr('ada', 'bob', 1, { visibility: 'x' })] }), 422, 'validation_failed');
  // exact net: ada sends everything and gets some back
  const exact = await st({ transfers: [tr('ada', 'bob', snap.ada + 5), tr('bob', 'ada', 5)] }, t.cy, 'exact');
  assert.equal(exact.status, 201);
  assert.equal((await h.balances(t)).ada, 0);
  const rep = await st({ transfers: [tr('ada', 'bob', snap.ada + 5), tr('bob', 'ada', 5)] }, t.cy, 'exact');
  assert.equal(rep.status, 200);
  assert.deepEqual(rep.body, exact.body);
  err(await st({ transfers: [tr('ada', 'bob', 1)] }, t.cy, 'exact'), 409, 'idempotency_key_reuse');
  const total = Object.values(await h.balances(t)).reduce((a, b) => a + b, 0);
  assert.equal(total, 12500);
});

test('export and import: replacement, preserved tokens and receipts, tamper rejection', async () => {
  const k = () => Math.random().toString();
  const p = await call('POST', '/payments', { token: t.ada, key: 'pp', body: { to_handle: 'bob', amount: 700, visibility: 'private' } });
  await call('POST', '/requests', { token: t.bob, key: 'rr', body: { payer_handle: 'ada', amount: 9 } });
  await call('POST', '/splits', { token: t.ada, key: 'ss', body: { amount: 10, participant_handles: ['ada', 'bob'] } });
  const s = await call('POST', '/settlements', { token: t.cy, key: 'tt', body: { transfers: [{ from_handle: 'ada', to_handle: 'bob', amount: 3 }] } });
  err(await call('POST', '/payments', { token: t.ada, key: 'failed', body: { to_handle: 'bob', amount: 10 ** 7 } }), 409, 'insufficient_funds');
  const exp = await call('GET', '/_test/export');
  assert.equal(exp.status, 200);
  assert.equal(exp.body.track, 'pocketful');
  assert.equal(exp.body.format_version, 1);
  assert.ok(!exp.text.includes('correct horse'));
  const feedBefore = (await call('GET', '/activity', { token: t.ada })).text;
  const sumBefore = await h.balances(t);

  await h.reset({ users: [{ id: 'u_other', email: 'o@x.io', password: 'password1', display_name: 'O', handle: 'o', balance: 5 }] });
  err(await call('GET', '/me', { token: t.ada }), 401, 'unauthenticated');
  for (let i = 0; i < 2; i++) assert.equal((await call('POST', '/_test/import', { body: exp.text })).status, 204);
  assert.deepEqual(await h.balances(t), sumBefore);
  assert.equal((await call('GET', '/activity', { token: t.ada })).text, feedBefore);
  assert.equal((await call('POST', '/auth/login', { body: { email: 'o@x.io', password: 'password1' } })).status, 401);
  assert.equal((await call('POST', '/auth/login', { body: { email: 'ada@example.com', password: 'correct horse' } })).status, 200);
  const rp = await call('POST', '/payments', { token: t.ada, key: 'pp', body: { to_handle: 'bob', amount: 700, visibility: 'private' } });
  assert.equal(rp.status, 200);
  assert.deepEqual(rp.body, p.body);
  const rs = await call('POST', '/settlements', { token: t.cy, key: 'tt', body: { transfers: [{ from_handle: 'ada', to_handle: 'bob', amount: 3 }] } });
  assert.deepEqual(rs.body, s.body);
  assert.equal((await call('POST', '/splits', { token: t.ada, key: 'ss', body: { amount: 10, participant_handles: ['ada', 'bob'] } })).status, 200);
  assert.equal((await call('POST', '/payments', { token: t.ada, key: 'failed', body: { to_handle: 'bob', amount: 10 } })).status, 201);
  const fresh = await call('POST', '/payments', { token: t.ada, key: k(), body: { to_handle: 'bob', amount: 1 } });
  assert.notEqual(fresh.body.payment_id, p.body.payment_id);
  assert.equal((await call('POST', '/settlements', { token: t.ada, key: k(), body: { transfers: [] } })).status, 403);

  // rejected imports leave the destination untouched
  const doc = JSON.parse(exp.text);
  const badDocs = [
    {}, [], { ...doc, track: 'other' }, { ...doc, format_version: 2 }, { track: 'pocketful', format_version: 1 },
    { ...doc, state: {} }, { ...doc, state: 'x' },
    (() => { const d = JSON.parse(exp.text); d.state.users[0].balance += 1; return d; })(),
    (() => { const d = JSON.parse(exp.text); d.state.payments[0].from = 'nobody'; return d; })(),
    (() => { const d = JSON.parse(exp.text); d.state.users[0].balance = -1; return d; })(),
    (() => { const d = JSON.parse(exp.text); delete d.state.tokens; return d; })(),
  ];
  const now = await h.balances(t);
  for (const d of badDocs) err(await call('POST', '/_test/import', { body: d }), 422, 'validation_failed');
  err(await call('POST', '/_test/import', { body: '{oops' }), 400, 'malformed_request');
  assert.deepEqual(await h.balances(t), now);
});
