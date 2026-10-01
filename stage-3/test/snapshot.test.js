import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { startServer, FX, k, login } from './helper.js';

let a, b;
before(async () => { a = await startServer(); b = await startServer(); });
after(() => { a.stop(); b.stop(); });
const err = (r, status, code) => { assert.equal(r.status, status, r.text); assert.equal(r.json.error.code, code); };

async function populate(c) {
  assert.equal((await c.reset(FX({
    payments: [{ id: 'p_seed', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 500, note: 'coffee', visibility: 'private', request_id: 'rq_seed' }],
    requests: [{ id: 'rq_seed', requester_id: 'u_bob', payer_id: 'u_ada', amount: 500, status: 'paid', payment_id: 'p_seed' }],
  }))).status, 204);
  const tok = {};
  for (const n of ['ada', 'bob', 'cy', 'op']) tok[n] = await login(c, `${n}@example.com`);
  const keys = { pay: k(), req: k(), split: k(), settle: k(), payreq: k() };
  const bodies = {
    pay: ['/payments', tok.ada, { to_handle: 'bob', amount: 100, note: 'é😀', visibility: 'private' }],
    req: ['/requests', tok.bob, { payer_handle: 'ada', amount: 300, note: 'taxi' }],
    split: ['/splits', tok.ada, { amount: 10, participant_handles: ['ada', 'bob', 'cy'] }],
    settle: ['/settlements', tok.op, { transfers: [{ from_handle: 'ada', to_handle: 'cy', amount: 50 }, { from_handle: 'cy', to_handle: 'bob', amount: 50 }] }],
  };
  const resp = {};
  for (const [n, [p, token, body]] of Object.entries(bodies)) {
    resp[n] = await c.post(p, { token, key: keys[n], body });
    assert.equal(resp[n].status, 201, resp[n].text);
  }
  const rid = resp.req.json.request_id;
  bodies.payreq = [`/requests/${rid}/pay`, tok.ada, { visibility: 'private' }];
  resp.payreq = await c.post(bodies.payreq[0], { token: tok.ada, key: keys.payreq, body: bodies.payreq[2] });
  assert.equal(resp.payreq.status, 201);
  const failKey = k();
  err(await c.post('/payments', { token: tok.cy, key: failKey, body: { to_handle: 'bob', amount: 99999999 } }), 409, 'insufficient_funds');
  return { tok, keys, bodies, resp, failKey };
}

async function checkRestored(c, ctx) {
  const { tok, keys, bodies, resp } = ctx;
  for (const [n, [p, token, body]] of Object.entries(bodies)) {
    const rep = await c.post(p, { token, key: keys[n], body });
    assert.equal(rep.status, 200, `${n} ${rep.text}`);
    assert.equal(rep.text, resp[n].text);
    err(await c.post(p, { token, key: keys[n], body: { ...body, zzz: 1 } }), 409, 'idempotency_key_reuse');
  }
  // failed key still reusable
  assert.equal((await c.post('/payments', { token: tok.ada, key: ctx.failKey, body: { to_handle: 'cy', amount: 1 } })).status, 201);
  // login with password still works, tokens still valid
  assert.equal((await c.get('/me', { token: tok.ada })).status, 200);
  assert.equal((await c.post('/auth/login', { body: { email: 'ada@example.com', password: 'correct horse' } })).status, 200);
  err(await c.post('/auth/login', { body: { email: 'ada@example.com', password: 'wrong horse!' } }), 401, 'unauthenticated');
  // operator permission survives
  assert.equal((await c.post('/settlements', { token: tok.op, key: k(), body: { transfers: [{ from_handle: 'ada', to_handle: 'bob', amount: 1 }] } })).status, 201);
  err(await c.post('/settlements', { token: tok.ada, key: k(), body: { transfers: [] } }), 403, 'forbidden');
}

test('I1-I12/J13: export, reset, import round trip; and into a second server', async () => {
  const ctx = await populate(a);
  const e1 = await a.get('/_test/export');
  assert.equal(e1.status, 200);
  assert.equal(e1.json.track, 'pocketful'); assert.equal(e1.json.format_version, 1);
  assert.equal(typeof e1.json.state.schema_version, 'number');
  assert.ok(!e1.text.includes('correct horse'), 'no plaintext password in the export');
  assert.match(e1.text, /scrypt\$/);
  // export is a snapshot: later writes do not change it
  await a.post('/payments', { token: ctx.tok.ada, key: k(), body: { to_handle: 'bob', amount: 1 } });
  const e1b = JSON.parse(e1.text);
  const e2 = await a.get('/_test/export');
  assert.notDeepEqual(e2.json, e1b);
  // wipe and restore on the same server
  assert.equal((await a.reset(FX())).status, 204);
  err(await a.get('/me', { token: ctx.tok.ada }), 401, 'unauthenticated');
  assert.equal((await a.post('/_test/import', { body: e1b })).status, 204);
  assert.deepEqual((await a.get('/_test/export')).json, e1b, 'import then export is identical (nothing regenerated)');
  assert.equal((await a.post('/_test/import', { body: e1b })).status, 204);
  assert.deepEqual((await a.get('/_test/export')).json, e1b, 'repeat import is idempotent');
  await checkRestored(a, ctx);
  // fresh server B with different state, then import A's earlier export
  assert.equal((await b.reset({ currency: 'JPY', minor_units: 0, users: [{ id: 'z', email: 'z@x.io', password: 'password1', display_name: 'Z', handle: 'z', balance: 5 }] })).status, 204);
  const zt = (await b.post('/auth/login', { body: { email: 'z@x.io', password: 'password1' } })).json.token;
  assert.equal((await b.post('/_test/import', { body: e1b })).status, 204);
  err(await b.get('/me', { token: zt }), 401, 'unauthenticated');
  err(await b.post('/auth/login', { body: { email: 'z@x.io', password: 'password1' } }), 401, 'unauthenticated');
  assert.deepEqual((await b.get('/_test/export')).json, e1b);
  const sum = async (c) => { let s = 0; for (const n of ['ada', 'bob', 'cy', 'op']) s += (await c.get('/me', { token: ctx.tok[n] })).json.balance; return s; };
  assert.equal(await sum(b), 12500);
  await checkRestored(b, ctx);
  // balances not replayed: feeds identical to the source
  // reset clears imported state
  assert.equal((await b.reset(FX())).status, 204);
  err(await b.get('/me', { token: ctx.tok.ada }), 401, 'unauthenticated');
  assert.equal((await b.get('/_test/export')).json.state.payments.length, 0);
});

test('I3: invalid imports change nothing', async () => {
  await a.reset(FX());
  const tok = await login(a, 'ada@example.com');
  const good = (await a.get('/_test/export')).json;
  const mut = (f) => { const d = JSON.parse(JSON.stringify(good)); f(d); return d; };
  const bads = [
    [], null, {}, { track: 'pocketful', format_version: 1 },
    mut((d) => { d.track = 'other'; }), mut((d) => { d.format_version = 2; }), mut((d) => { delete d.state; }), mut((d) => { d.state = 5; }),
    mut((d) => { d.state.users[0].balance = -1; }), mut((d) => { d.state.users = 'x'; }), mut((d) => { d.state.tokens[0].user_id = 'ghost'; }),
    mut((d) => { d.state.users[0].password_hash = 'plain'; }), mut((d) => { d.state.schema_version = 99; }), mut((d) => { d.state.settlement_operator_ids = ['ghost']; }),
    mut((d) => { d.state.payments = [{ payment_id: 'p', from_user_id: 'ghost' }]; }),
  ];
  for (const bad of bads) {
    err(await a.post('/_test/import', { body: bad }), 422, 'validation_failed');
    assert.equal((await a.get('/me', { token: tok })).status, 200);
  }
  err(await a.post('/_test/import', { raw: '{' }), 400, 'malformed_request');
  assert.equal((await a.get('/me', { token: tok })).status, 200);
});

test('I9: export under concurrent writes is consistent', async () => {
  await a.reset(FX());
  const tok = await login(a, 'ada@example.com');
  const writes = Array.from({ length: 40 }, () => a.post('/payments', { token: tok, key: k(), body: { to_handle: 'bob', amount: 10 } }));
  const exports = await Promise.all(Array.from({ length: 10 }, () => a.get('/_test/export')));
  await Promise.all(writes);
  for (const e of exports) assert.equal(e.json.state.users.reduce((s, u) => s + u.balance, 0), 12500);
});
