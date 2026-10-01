'use strict';
const { test, before, after } = require('node:test');
const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const path = require('node:path');

const PORT = 18000 + Math.floor(Math.random() * 1000);
const BASE = `http://127.0.0.1:${PORT}`;
let proc;
let n = 0;
const key = () => `k${Date.now()}-${n++}`;

async function call(method, p, { body, token, k, raw } = {}) {
  const headers = { 'content-type': 'application/json' };
  if (token) headers.authorization = `Bearer ${token}`;
  if (k !== undefined) headers['idempotency-key'] = k;
  const res = await fetch(BASE + p, { method, headers, body: raw !== undefined ? raw : body === undefined ? undefined : JSON.stringify(body) });
  const text = await res.text();
  return { status: res.status, json: text ? JSON.parse(text) : null, ct: res.headers.get('content-type') };
}
const user = (h, bal) => ({ id: `u_${h}`, email: `${h}@example.com`, password: 'correct horse', display_name: h, handle: h, balance: bal });
async function world(extra = {}, users = [user('ada', 10000), user('bob', 2500), user('cy', 500)]) {
  const r = await call('POST', '/_test/reset', { body: Object.assign({ currency: 'EUR', minor_units: 2, users, payments: [], requests: [] }, extra) });
  assert.equal(r.status, 204);
  const toks = {};
  for (const u of users) toks[u.handle] = (await call('POST', '/auth/login', { body: { email: u.email, password: 'correct horse' } })).json.token;
  return toks;
}
const bal = async (t) => (await call('GET', '/me', { token: t })).json.balance;

before(async () => {
  proc = spawn('node', [path.join(__dirname, '..', 'server.js')], { env: { ...process.env, PORT: String(PORT) }, stdio: 'ignore' });
  for (let i = 0; i < 50; i++) { try { if ((await fetch(BASE + '/health')).ok) return; } catch (e) { /* retry */ } await new Promise((r) => setTimeout(r, 100)); }
});
after(() => proc.kill());

test('50-way overspend: exactly the affordable number succeed, total conserved', async () => {
  const t = await world({}, [user('ada', 1000), user('bob', 0)]);
  const out = await Promise.all(Array.from({ length: 50 }, () => call('POST', '/payments', { token: t.ada, k: key(), body: { to_handle: 'bob', amount: 100 } })));
  assert.equal(out.filter((o) => o.status === 201).length, 10);
  assert.equal(out.filter((o) => o.status === 409).length, 40);
  assert.equal(await bal(t.ada), 0);
  assert.equal(await bal(t.bob), 1000);
});

test('concurrent pays of one request: one 201, rest request_not_pending', async () => {
  const t = await world();
  const rq = (await call('POST', '/requests', { token: t.bob, k: key(), body: { payer_handle: 'ada', amount: 100 } })).json.request_id;
  const out = await Promise.all(Array.from({ length: 20 }, () => call('POST', `/requests/${rq}/pay`, { token: t.ada, k: key(), body: {} })));
  assert.equal(out.filter((o) => o.status === 201).length, 1);
  assert.ok(out.filter((o) => o.status !== 201).every((o) => o.status === 409 && o.json.error.code === 'request_not_pending'));
  assert.equal(await bal(t.ada), 9900);
});

test('identical concurrent requests on one key: one 201, others 200 same body', async () => {
  const t = await world();
  const k = key();
  const out = await Promise.all(Array.from({ length: 20 }, () => call('POST', '/payments', { token: t.ada, k, body: { to_handle: 'bob', amount: 10 } })));
  assert.equal(out.filter((o) => o.status === 201).length, 1);
  assert.equal(out.filter((o) => o.status === 200).length, 19);
  assert.equal(await bal(t.ada), 9990);
});

test('idempotency: reorder ok, changed body 409, invalid body on claimed key 409, failure reusable', async () => {
  const t = await world();
  const k = key();
  assert.equal((await call('POST', '/payments', { token: t.ada, k, raw: '{"to_handle":"bob","amount":5}' })).status, 201);
  assert.equal((await call('POST', '/payments', { token: t.ada, k, raw: '{ "amount": 5.0, "to_handle": "bob" }' })).status, 200);
  assert.equal((await call('POST', '/payments', { token: t.ada, k, body: { to_handle: 'bob', amount: 'x' } })).json.error.code, 'idempotency_key_reuse');
  const k2 = key();
  assert.equal((await call('POST', '/payments', { token: t.cy, k: k2, body: { to_handle: 'bob', amount: 99999 } })).status, 409);
  assert.equal((await call('POST', '/payments', { token: t.cy, k: k2, body: { to_handle: 'bob', amount: 1 } })).status, 201);
  assert.equal((await call('POST', '/payments', { token: t.ada, body: { to_handle: 'bob', amount: 1 } })).json.error.code, 'missing_idempotency_key');
  assert.equal((await call('POST', '/payments', { token: t.ada, k: 'k'.repeat(256), body: { to_handle: 'bob', amount: 1 } })).status, 422);
  assert.equal((await call('POST', '/payments', { token: t.ada, k: 'k'.repeat(255), body: { to_handle: 'bob', amount: 1 } })).status, 201);
});

test('amount forms, validation and error body shape', async () => {
  const t = await world();
  for (const a of [1000.0, 1e3]) assert.equal((await call('POST', '/payments', { token: t.ada, k: key(), raw: `{"to_handle":"bob","amount":${JSON.stringify(a)}}` })).json.amount, 1000);
  for (const a of [true, '10', null, [], {}, 1.5, 1e-1, 0]) {
    const r = await call('POST', '/payments', { token: t.ada, k: key(), body: { to_handle: 'bob', amount: a } });
    assert.equal(r.status, 422, JSON.stringify(a));
    assert.equal(r.ct, 'application/json; charset=utf-8');
  }
  assert.equal((await call('POST', '/payments', { token: t.ada, k: key(), body: { to_handle: 5, amount: 1 } })).status, 400);
  assert.equal((await call('POST', '/payments', { token: t.ada, k: key(), body: { to_handle: 'bob', amount: 1, note: null } })).status, 422);
  assert.equal((await call('POST', '/payments', { token: t.ada, k: key(), raw: '[1]' })).status, 400);
  assert.equal((await call('GET', '/me', {})).status, 401);
  assert.equal((await call('GET', '/nope', {})).json.error.code, 'not_found');
  assert.equal((await call('GET', '/activity?limit=1e2', { token: t.ada })).status, 422);
  assert.equal((await call('GET', '/activity?offset=%2B4', { token: t.ada })).status, 422);
  assert.equal((await call('GET', '/activity?limit=200', { token: t.ada })).status, 200);
});

test('splits, zero share and rounding', async () => {
  const t = await world();
  const r = await call('POST', '/splits', { token: t.ada, k: key(), body: { amount: 1, participant_handles: ['bob', 'cy', 'ada'] } });
  assert.deepEqual(r.json.shares.map((s) => s.amount), [1, 0, 0]);
  assert.equal(r.json.requests.length, 2);
  const zero = r.json.requests[1].request_id;
  assert.equal((await call('POST', `/requests/${zero}/pay`, { token: t.cy, k: key(), body: {} })).status, 201);
  const solo = await call('POST', '/splits', { token: t.ada, k: key(), body: { amount: 10, participant_handles: ['ada'] } });
  assert.deepEqual(solo.json.requests, []);
});

test('feed visibility and request privacy', async () => {
  const t = await world({ settlement_operator_ids: ['u_cy'] });
  await call('POST', '/payments', { token: t.ada, k: key(), body: { to_handle: 'bob', amount: 10, visibility: 'private' } });
  assert.equal((await call('GET', '/activity', { token: t.cy })).json.payments.length, 0);
  assert.equal((await call('GET', '/activity', { token: t.bob })).json.payments.length, 1);
  await call('POST', '/requests', { token: t.bob, k: key(), body: { payer_handle: 'ada', amount: 10 } });
  assert.equal((await call('GET', '/requests', { token: t.cy })).json.requests.length, 0);
});

test('settlements: net affordability, ordering of errors, replay', async () => {
  const t = await world({ settlement_operator_ids: ['u_cy'] }, [user('ada', 100), user('bob', 0), user('cy', 0)]);
  const body = { transfers: [{ from_handle: 'ada', to_handle: 'bob', amount: 100, visibility: 'private' }, { from_handle: 'bob', to_handle: 'cy', amount: 50 }] };
  assert.equal((await call('POST', '/settlements', { token: t.ada, k: key(), body })).status, 403);
  assert.equal((await call('POST', '/settlements', { body })).status, 401);
  const k = key();
  const r = await call('POST', '/settlements', { token: t.cy, k, body });
  assert.equal(r.status, 201);
  assert.equal(r.json.payments.length, 2);
  assert.ok(r.json.payments.every((p) => p.settlement_id === r.json.settlement_id && p.created_at === r.json.committed_at));
  assert.equal((await call('POST', '/settlements', { token: t.cy, k, body })).status, 200);
  assert.equal(await bal(t.bob), 50);
  assert.equal((await call('GET', '/activity', { token: t.cy })).json.payments.length, 1);
  const unaff = { transfers: [{ from_handle: 'ada', to_handle: 'bob', amount: 1 }, { from_handle: 'bob', to_handle: 'zzz', amount: 1 }] };
  assert.equal((await call('POST', '/settlements', { token: t.cy, k: key(), body: unaff })).status, 404);
  assert.equal((await call('POST', '/settlements', { token: t.cy, k: key(), body: { transfers: [] } })).status, 422);
  assert.equal((await call('POST', '/settlements', { token: t.cy, k: key(), body: { transfers: [{ from_handle: 'ada', to_handle: 'ada', amount: 1 }] } })).json.error.code, 'self_payment');
  assert.equal((await call('POST', '/settlements', { token: t.cy, k: key(), body: { transfers: [{ from_handle: 'ada', to_handle: 'bob', amount: 1 }] } })).json.error.code, 'insufficient_funds');
});

test('export/import preserves tokens, receipts and keys; bad imports change nothing', async () => {
  const t = await world();
  const k = key();
  const p = await call('POST', '/payments', { token: t.ada, k, body: { to_handle: 'bob', amount: 77, note: 'é😀' } });
  const exp = await call('GET', '/_test/export');
  assert.equal(exp.json.track, 'pocketful');
  assert.ok(!JSON.stringify(exp.json).includes('correct horse'));
  await world({}, [user('zed', 1)]);
  assert.equal((await call('GET', '/me', { token: t.ada })).status, 401);
  assert.equal((await call('POST', '/_test/import', { body: exp.json })).status, 204);
  assert.equal((await call('POST', '/_test/import', { body: exp.json })).status, 204);
  assert.deepEqual((await call('GET', '/_test/export')).json, exp.json);
  const again = await call('POST', '/payments', { token: t.ada, k, body: { to_handle: 'bob', amount: 77, note: 'é😀' } });
  assert.equal(again.status, 200);
  assert.deepEqual(again.json, p.json);
  assert.equal(await bal(t.ada), 9923);
  assert.equal((await call('POST', '/_test/import', { body: { track: 'x', format_version: 1, state: {} } })).status, 422);
  assert.equal((await call('POST', '/_test/import', { body: { track: 'pocketful', format_version: 1, state: { users: 1 } } })).status, 422);
  assert.equal((await call('POST', '/_test/import', { raw: '{' })).status, 400);
  assert.deepEqual((await call('GET', '/_test/export')).json, exp.json);
});

test('auth rules and reset errors', async () => {
  const t = await world();
  const s = (email, password = 'abcdefgh') => call('POST', '/auth/signup', { body: { email, password, display_name: 'X' } });
  assert.equal((await s('A.b-C+d@x.y')).status, 201);
  assert.equal((await s('A.b-C+d@x.y')).json.error.code, 'email_taken');
  assert.equal((await s('a_b_c_d@x.y')).json.error.code, 'handle_taken');
  assert.equal((await s('q@x.y', 'short77')).status, 422);
  for (const e of ['nope', 'x@', 'a@b@c', '@x.y']) assert.equal((await s(e)).status, 422, e);
  assert.equal((await call('POST', '/auth/login', { body: { email: 'ada@example.com', password: 'bad' } })).status, 401);
  const bad = await call('POST', '/_test/reset', { body: { currency: 'EUR', minor_units: 2, users: [user('ada', -1)] } });
  assert.equal(bad.status, 422);
  assert.equal(await bal(t.ada), 10000);
});

test('deep unknown fields, odd paths, huge headers, unicode handles never 5xx', async () => {
  const t = await world();
  const n = 100000;
  const raw = '{"to_handle":"bob","amount":1,"meta":' + '['.repeat(n) + ']'.repeat(n) + '}';
  const r = await call('POST', '/payments', { token: t.ada, k: key(), raw });
  assert.ok(r.status < 500);
  const deep = '{"to_handle":"bob","amount":1,"meta":' + '['.repeat(8000) + ']'.repeat(8000) + '}';
  assert.equal((await call('POST', '/payments', { token: t.ada, k: key(), raw: deep })).status, 201);
  const http = require('node:http');
  const get = (p, headers = {}) => new Promise((res) => http.get({ host: '127.0.0.1', port: PORT, path: p, headers }, (x) => { x.resume(); res(x.statusCode); }));
  for (const p of ['//', '///', '/\\']) assert.equal(await get(p), 404);
  assert.equal(await get('/me', { authorization: 'Bearer ' + 'x'.repeat(20000) }), 401);
  assert.equal((await call('POST', '/payments', { token: t.ada, k: 'k'.repeat(17000), body: { to_handle: 'bob', amount: 1 } })).status, 422);
  const su = await call('POST', '/auth/signup', { body: { email: 'a😀b@x.y', password: '12345678', display_name: 'E' } });
  assert.equal((await call('GET', '/me', { token: su.json.token })).json.handle, 'a_b');
});
