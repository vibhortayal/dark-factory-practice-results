'use strict';

const { test, before, after, beforeEach } = require('node:test');
const assert = require('node:assert/strict');
const h = require('./helpers');
const { call } = h;

let t;
before(h.start);
after(h.stop);

const future = (s) => new Date(Date.now() + s * 1000).toISOString().replace('Z', '+00:00');
const HOUR = 3600;
const k = () => Math.random().toString();
const err = (r, status, code) => {
  assert.equal(r.status, status, r.text);
  assert.equal(r.body.error.code, code);
};
const authorize = (token, body, key = k()) => call('POST', '/authorizations', { token, key, body });
const me = async (token) => (await call('GET', '/me', { token })).body;

beforeEach(async () => {
  await h.reset();
  t = await h.tokens();
});

test('/me exposes total, available and held; balance equals total', async () => {
  const a = await authorize(t.ada, { to_handle: 'bob', amount: 2000, note: 'deposit', visibility: 'private' });
  assert.equal(a.status, 201);
  assert.deepEqual(Object.keys(a.body), ['authorization_id', 'from_user_id', 'from_handle', 'to_user_id', 'to_handle', 'amount', 'captured_amount', 'remaining_amount', 'currency', 'note', 'visibility', 'status', 'expires_at', 'payment_id', 'payment_ids', 'created_at']);
  assert.equal(a.body.remaining_amount, 2000);
  assert.equal(Date.parse(a.body.expires_at) - Date.parse(a.body.created_at), 600000);
  assert.match(a.body.created_at, /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}\+00:00$/);
  const m = await me(t.ada);
  assert.deepEqual([m.balance, m.total, m.available, m.held], [10000, 10000, 8000, 2000]);
  assert.equal((await me(t.bob)).held, 0);
  // held funds cannot be spent by payments, request payments, settlements or new holds
  err(await call('POST', '/payments', { token: t.ada, key: k(), body: { to_handle: 'bob', amount: 8001 } }), 409, 'insufficient_funds');
  assert.equal((await call('POST', '/payments', { token: t.ada, key: k(), body: { to_handle: 'bob', amount: 8000 } })).status, 201);
  err(await authorize(t.ada, { to_handle: 'bob', amount: 1 }), 409, 'insufficient_funds');
  err(await call('POST', '/requests/rq_1/pay', { token: t.ada, key: k(), body: {} }), 409, 'insufficient_funds');
  const st = (amount) => call('POST', '/settlements', { token: t.cy, key: k(), body: { transfers: [{ from_handle: 'ada', to_handle: 'bob', amount }] } });
  err(await st(1), 409, 'insufficient_funds');
  // a feed never lists an open authorization
  assert.ok(!(await call('GET', '/activity', { token: t.ada })).text.includes(a.body.authorization_id));
});

test('capture: default final releases the remainder; payment shape; replay', async () => {
  const a = (await authorize(t.ada, { to_handle: 'bob', amount: 2000, note: 'dep', visibility: 'private' })).body;
  const id = a.authorization_id;
  const cap = (token, body, key) => call('POST', `/authorizations/${id}/capture`, { token, key, body });
  err(await cap(t.ada, { amount: 100 }, 'x'), 403, 'forbidden');
  err(await cap(t.cy, { amount: 100 }, 'x'), 403, 'forbidden');
  err(await cap(t.bob, { amount: 2001 }, 'x'), 422, 'capture_exceeds_authorization');
  err(await cap(t.bob, { amount: 0 }, 'x'), 422, 'validation_failed');
  err(await cap(t.bob, { amount: '5' }, 'x'), 422, 'validation_failed');
  err(await cap(t.bob, { amount: 5, final: 'yes' }, 'x'), 400, 'malformed_request');
  const first = await cap(t.bob, { amount: 1500 }, 'cap1');
  assert.equal(first.status, 201);
  assert.equal(first.body.amount, 1500);
  assert.equal(first.body.authorization_id, id);
  assert.equal(first.body.request_id, null);
  assert.equal(first.body.settlement_id, null);
  assert.equal(first.body.note, 'dep');
  assert.equal(first.body.visibility, 'private');
  assert.equal(first.body.from_handle, 'ada');
  assert.equal(first.body.to_handle, 'bob');
  assert.deepEqual(Object.keys(first.body).slice(-4), ['request_id', 'settlement_id', 'authorization_id', 'created_at']);
  let m = await me(t.ada);
  assert.deepEqual([m.total, m.available, m.held], [8500, 8500, 0]);
  const list = (await call('GET', '/authorizations', { token: t.ada })).body.authorizations[0];
  assert.deepEqual([list.status, list.captured_amount, list.remaining_amount, list.payment_id, list.payment_ids], ['captured', 1500, 0, first.body.payment_id, [first.body.payment_id]]);
  const replay = await cap(t.bob, { amount: 1500 }, 'cap1');
  assert.equal(replay.status, 200);
  assert.deepEqual(replay.body, first.body);
  err(await cap(t.bob, { amount: 1500, final: true }, 'cap1'), 409, 'idempotency_key_reuse');
  err(await cap(t.bob, { amount: 5 }, 'cap2'), 409, 'authorization_not_open');
  assert.ok((await call('GET', '/activity', { token: t.bob })).body.payments.some((p) => p.payment_id === first.body.payment_id));
  assert.ok(!(await call('GET', '/activity', { token: t.cy })).body.payments.some((p) => p.payment_id === first.body.payment_id));
  err(await call('POST', `/authorizations/${id}/void`, { token: t.ada }), 409, 'authorization_not_open');
  err(await call('POST', '/authorizations/nope/capture', { token: t.bob, key: 'n', body: {} }), 404, 'not_found');
});

test('capture body equality: {} versus an explicit amount are different bodies', async () => {
  const id = (await authorize(t.ada, { to_handle: 'bob', amount: 2000 })).body.authorization_id;
  const cap = (body) => call('POST', `/authorizations/${id}/capture`, { token: t.bob, key: 'same', body });
  assert.equal((await cap({})).status, 201);
  err(await cap({ amount: 2000 }), 409, 'idempotency_key_reuse');
  assert.equal((await cap('')).status, 200);
});

test('extended capture: partial captures keep the remainder held', async () => {
  const id = (await authorize(t.ada, { to_handle: 'bob', amount: 1000 })).body.authorization_id;
  const cap = (body, key) => call('POST', `/authorizations/${id}/capture`, { token: t.bob, key, body });
  const p1 = await cap({ amount: 300, final: false }, 'e1');
  assert.equal(p1.status, 201);
  let m = await me(t.ada);
  assert.deepEqual([m.total, m.available, m.held], [9700, 9000, 700]);
  let a = (await call('GET', '/authorizations?direction=incoming', { token: t.bob })).body.authorizations[0];
  assert.deepEqual([a.status, a.captured_amount, a.remaining_amount], ['open', 300, 700]);
  err(await cap({ amount: 701, final: false }, 'e2'), 422, 'capture_exceeds_authorization');
  const p2 = await cap({ amount: 200, final: false }, 'e3');
  const p3 = await cap({}, 'e4'); // omitted amount = remaining 500, closes it
  assert.equal(p3.body.amount, 500);
  a = (await call('GET', '/authorizations', { token: t.bob })).body.authorizations[0];
  assert.deepEqual([a.status, a.captured_amount, a.remaining_amount, a.payment_id], ['captured', 1000, 0, p3.body.payment_id]);
  assert.deepEqual(a.payment_ids, [p1.body.payment_id, p2.body.payment_id, p3.body.payment_id]);
  m = await me(t.ada);
  assert.deepEqual([m.total, m.available, m.held], [9000, 9000, 0]);
  // whole remainder with final:false also closes
  const id2 = (await authorize(t.ada, { to_handle: 'bob', amount: 100 })).body.authorization_id;
  await call('POST', `/authorizations/${id2}/capture`, { token: t.bob, key: 'w', body: { amount: 100, final: false } });
  err(await call('POST', `/authorizations/${id2}/capture`, { token: t.bob, key: 'w2', body: { amount: 1, final: false } }), 409, 'authorization_not_open');
  // a final partial capture releases the rest
  const id3 = (await authorize(t.ada, { to_handle: 'bob', amount: 500 })).body.authorization_id;
  await call('POST', `/authorizations/${id3}/capture`, { token: t.bob, key: 'f1', body: { amount: 100, final: false } });
  await call('POST', `/authorizations/${id3}/capture`, { token: t.bob, key: 'f2', body: { amount: 50 } });
  assert.equal((await me(t.ada)).held, 0);
});

test('void: payer only, idempotent, keeps capture records on a partial capture', async () => {
  const id = (await authorize(t.ada, { to_handle: 'bob', amount: 1000 })).body.authorization_id;
  const p = await call('POST', `/authorizations/${id}/capture`, { token: t.bob, key: 'c', body: { amount: 400, final: false } });
  err(await call('POST', `/authorizations/${id}/void`, { token: t.bob }), 403, 'forbidden');
  err(await call('POST', `/authorizations/${id}/void`, { token: t.cy }), 403, 'forbidden');
  err(await call('POST', '/authorizations/zzz/void', { token: t.ada }), 404, 'not_found');
  const v = await call('POST', `/authorizations/${id}/void`, { token: t.ada });
  assert.equal(v.status, 200);
  assert.deepEqual([v.body.status, v.body.captured_amount, v.body.remaining_amount, v.body.payment_ids], ['voided', 400, 0, [p.body.payment_id]]);
  assert.equal((await call('POST', `/authorizations/${id}/void`, { token: t.ada })).status, 200);
  assert.deepEqual([(await me(t.ada)).held, (await me(t.ada)).available], [0, 9600]);
  err(await call('POST', `/authorizations/${id}/capture`, { token: t.bob, key: 'again', body: {} }), 409, 'authorization_not_open');
});

test('list: visibility to parties, filters, paging', async () => {
  const mk = (amount) => authorize(t.ada, { to_handle: 'bob', amount });
  const ids = [];
  for (let i = 1; i <= 3; i++) ids.push((await mk(i)).body.authorization_id);
  const list = (q, tok) => call('GET', `/authorizations${q}`, { token: tok });
  assert.deepEqual((await list('', t.ada)).body.authorizations.map((a) => a.authorization_id), [...ids].reverse());
  assert.equal((await list('', t.cy)).body.authorizations.length, 0);
  assert.equal((await list('?direction=incoming', t.ada)).body.authorizations.length, 0);
  assert.equal((await list('?direction=incoming', t.bob)).body.authorizations.length, 3);
  assert.deepEqual((await list('?limit=1&offset=1', t.bob)).body.has_more, true);
  assert.equal((await list('?status=captured', t.bob)).body.authorizations.length, 0);
  for (const q of ['status=x', 'status=', 'direction=up', 'limit=0', 'offset=-1']) err(await list(`?${q}`, t.ada), 422, 'validation_failed');
  err(await call('GET', '/authorizations'), 401, 'unauthenticated');
  // settlement operator has no extra access
  assert.equal((await list('', t.cy)).body.authorizations.length, 0);
});

test('creation errors and precedence', async () => {
  const a = (body) => authorize(t.ada, body);
  err(await a({ to_handle: 'ada', amount: 5 }), 422, 'self_payment');
  err(await a({ to_handle: 'zzz', amount: 5 }), 404, 'not_found');
  err(await a({ to_handle: 'bob', amount: 0 }), 422, 'validation_failed');
  err(await a({ to_handle: 'bob', amount: 5, note: 'x'.repeat(201) }), 422, 'validation_failed');
  err(await a({ to_handle: 'bob', amount: 5, visibility: 'x' }), 422, 'validation_failed');
  err(await a({ to_handle: 5, amount: 5 }), 400, 'malformed_request');
  err(await a({ to_handle: 'bob', amount: 10001 }), 409, 'insufficient_funds');
  assert.equal((await a({ to_handle: 'bob', amount: 10000 })).status, 201);
  const first = await authorize(t.bob, { to_handle: 'cy', amount: 5 }, 'dup');
  assert.equal((await authorize(t.bob, { to_handle: 'cy', amount: 5 }, 'dup')).status, 200);
  err(await authorize(t.bob, { to_handle: 'cy', amount: 6 }, 'dup'), 409, 'idempotency_key_reuse');
  err(await call('POST', '/authorizations', { token: t.bob, body: {} }), 400, 'missing_idempotency_key');
  assert.equal(first.status, 201);
});

test('expiry follows the clock with no request at the deadline', async () => {
  await h.reset({ ...h.FIXTURE, authorization_ttl_seconds: 1 });
  t = await h.tokens();
  const a = (await authorize(t.ada, { to_handle: 'bob', amount: 4000 })).body;
  assert.equal(Date.parse(a.expires_at) - Date.parse(a.created_at), 1000);
  assert.equal((await me(t.ada)).held, 4000);
  await new Promise((r) => setTimeout(r, 1300));
  const m = await me(t.ada);
  assert.deepEqual([m.held, m.available], [0, 10000]);
  const listed = (await call('GET', '/authorizations?status=expired', { token: t.bob })).body.authorizations;
  assert.deepEqual([listed.length, listed[0].remaining_amount], [1, 0]);
  assert.equal((await call('GET', '/authorizations?status=open', { token: t.bob })).body.authorizations.length, 0);
  err(await call('POST', `/authorizations/${a.authorization_id}/capture`, { token: t.bob, key: 'late', body: {} }), 409, 'authorization_expired');
  err(await call('POST', `/authorizations/${a.authorization_id}/void`, { token: t.ada }), 409, 'authorization_not_open');
  assert.equal((await call('POST', '/payments', { token: t.ada, key: 'spend', body: { to_handle: 'bob', amount: 10000 } })).status, 201);
});

test('seeded authorizations: held derived, validation, past expiry', async () => {
  const soon = future(2 * HOUR);
  const auth = (over) => ({ id: 'a_1', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 2000, note: 'deposit', visibility: 'public', status: 'open', expires_at: soon, ...over });
  const fx = (list, extra = {}) => ({ ...h.FIXTURE, authorizations: list, ...extra });
  await h.reset(fx([auth()]));
  t = await h.tokens();
  let m = await me(t.ada);
  assert.deepEqual([m.balance, m.total, m.available, m.held], [10000, 10000, 8000, 2000]);
  const got = (await call('GET', '/authorizations', { token: t.bob })).body.authorizations[0];
  assert.equal(got.authorization_id, 'a_1');
  assert.equal(got.expires_at, auth().expires_at);
  assert.equal(got.status, 'open');
  assert.equal((await call('POST', '/authorizations/a_1/capture', { token: t.bob, key: 'c', body: { amount: 500 } })).status, 201);
  // closed, voided and expired seeds hold nothing; past-dated open is expired
  await h.reset(fx([auth({ status: 'captured' }), auth({ id: 'a_2', status: 'voided' }), auth({ id: 'a_3', status: 'expired' }), auth({ id: 'a_4', expires_at: future(-2 * HOUR) })]));
  t = await h.tokens();
  assert.equal((await me(t.ada)).held, 0);
  const l = (await call('GET', '/authorizations', { token: t.ada })).body.authorizations;
  assert.deepEqual(l.map((x) => x.status).sort(), ['captured', 'expired', 'expired', 'voided']);
  assert.equal(l.find((x) => x.authorization_id === 'a_1').captured_amount, 2000);
  // rejected fixtures change nothing
  const before = await me(t.ada);
  for (const bad of [
    fx([auth({ amount: 10001 })]),
    fx([auth({ amount: 6000 }), auth({ id: 'a_2', amount: 6000 })]),
    fx([auth({ to_user_id: 'nobody' })]), fx([auth({ status: 'weird' })]), fx([auth({ amount: 0 })]),
    fx([auth({ expires_at: 'tomorrow' })]), fx([auth(), auth()]), fx('x'.split('')),
    fx([], { authorization_ttl_seconds: 0 }), fx([], { authorization_ttl_seconds: -5 }),
    fx([], { authorization_ttl_seconds: 1.5 }), fx([], { authorization_ttl_seconds: '600' }), fx([], { authorization_ttl_seconds: true }),
  ]) err(await call('POST', '/_test/reset', { body: bad }), 422, 'validation_failed');
  assert.deepEqual(await me(t.ada), before);
  // an expired seeded hold does not count against the balance
  await h.reset(fx([auth({ amount: 10001, expires_at: future(-2 * HOUR) })]));
  await h.reset(fx([], { authorization_ttl_seconds: 5 }));
});

test('export/import of stage-2 state and of a stage-1 layout', async () => {
  const a = (await authorize(t.ada, { to_handle: 'bob', amount: 1000 }, 'ak')).body;
  const c = await call('POST', `/authorizations/${a.authorization_id}/capture`, { token: t.bob, key: 'ck', body: { amount: 300, final: false } });
  const exp = await call('GET', '/_test/export');
  assert.ok(!exp.text.includes('correct horse'));
  await h.reset({ users: [] });
  assert.equal((await call('POST', '/_test/import', { body: exp.text })).status, 204);
  assert.deepEqual(await me(t.ada), { ...(await me(t.ada)), held: 700, available: 9000, total: 9700 });
  const l = (await call('GET', '/authorizations', { token: t.bob })).body.authorizations[0];
  assert.deepEqual([l.captured_amount, l.remaining_amount, l.payment_ids], [300, 700, [c.body.payment_id]]);
  const rc = await call('POST', `/authorizations/${a.authorization_id}/capture`, { token: t.bob, key: 'ck', body: { amount: 300, final: false } });
  assert.equal(rc.status, 200);
  assert.deepEqual(rc.body, c.body);
  assert.equal((await authorize(t.ada, { to_handle: 'bob', amount: 1000 }, 'ak')).status, 200);
  const next = (await authorize(t.ada, { to_handle: 'bob', amount: 1 })).body.authorization_id;
  assert.notEqual(next, a.authorization_id);
  // tampering is rejected
  const doc = JSON.parse(exp.text);
  const bad = [
    (d) => { d.state.authorizations[0].captured_amount = 5; },
    (d) => { d.state.authorizations[0].payment_ids = ['p_none']; },
    (d) => { d.state.authorizations[0].status = 'x'; },
    (d) => { d.state.authorizations[0].from = 'ghost'; },
    (d) => { d.state.authorizations[0].amount = 99999999; },
    (d) => { d.state.authorization_ttl_seconds = 0; },
    (d) => { delete d.state.counters.authorization; },
    (d) => { d.state.authorizations[0].expires_at = 'soon'; },
  ];
  const before = await me(t.ada);
  for (const mutate of bad) {
    const d = JSON.parse(JSON.stringify(doc));
    mutate(d);
    err(await call('POST', '/_test/import', { body: d }), 422, 'validation_failed');
  }
  assert.deepEqual(await me(t.ada), before);
  // a stage-1 layout: no authorizations, no ttl, no authorization counter, payments without authorization_id
  const old = JSON.parse(exp.text);
  delete old.state.authorizations;
  delete old.state.authorization_ttl_seconds;
  delete old.state.counters.authorization;
  old.state.payments = old.state.payments.filter((p) => !p.authorization_id);
  old.state.users.find((u) => u.id === 'u_ada').balance = 10000;
  old.state.users.find((u) => u.id === 'u_bob').balance = 2500;
  assert.equal((await call('POST', '/_test/import', { body: old })).status, 204);
  assert.deepEqual(await me(t.ada), { ...(await me(t.ada)), held: 0, total: 10000, available: 10000 });
  assert.equal((await authorize(t.ada, { to_handle: 'bob', amount: 1 })).body.expires_at.length > 20, true);
});

test('timestamps: milliseconds and ordering across precisions', async () => {
  const p = await call('POST', '/payments', { token: t.ada, key: 'ts', body: { to_handle: 'bob', amount: 1 } });
  assert.match(p.body.created_at, /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}\+00:00$/);
  const seeded = (await call('GET', '/activity', { token: t.ada })).body.payments;
  assert.equal(seeded[0].payment_id, p.body.payment_id);
});

test('malformed JSON is 400 at any depth; valid but too deep is 422', async () => {
  const deep = (n) => '['.repeat(n);
  for (const n of [5, 201, 1001, 5000, 300000]) {
    const r = await call('POST', '/payments', { token: t.ada, key: `m${n}`, body: deep(n) });
    assert.equal(r.status, 400, `unclosed depth ${n}`);
    assert.equal(r.body.error.code, 'malformed_request');
  }
  const valid = (n) => `{"to_handle":"bob","amount":1,"note":${'['.repeat(n)}${']'.repeat(n)}}`;
  for (const n of [2000, 300000]) {
    const r = await call('POST', '/payments', { token: t.ada, key: `v${n}`, body: valid(n) });
    assert.equal(r.status, 422, `valid depth ${n}`);
  }
});
