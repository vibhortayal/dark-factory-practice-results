import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { startServer, stage1Dir, FX, k, login, balanceSum } from './helper.js';

let c, t;
const err = (r, status, code) => { assert.equal(r.status, status, r.text); assert.equal(r.json.error.code, code); };
before(async () => { c = await startServer(); await c.reset(FX()); t = { ada: await login(c, 'ada@example.com'), bob: await login(c, 'bob@example.com'), op: await login(c, 'op@example.com') }; });
after(() => c.stop());

test('K6: amount literals are judged on their exact decimal value', async () => {
  const h = { token: t.ada };
  const post = (path, raw, extra = {}) => c.post(path, { ...h, key: k(), raw, ...extra });
  const lits = ['1.0000000000000000000001', '0.99999999999999999999999', '1.00000000000000000001e0', '10.000000000000000000000001e-1', '2.5e-1'];
  for (const lit of lits) {
    err(await post('/payments', `{"to_handle":"bob","amount":${lit}}`), 422, 'validation_failed');
    err(await post('/requests', `{"payer_handle":"bob","amount":${lit}}`), 422, 'validation_failed');
    err(await post('/splits', `{"participant_handles":["bob"],"amount":${lit}}`), 422, 'validation_failed');
    err(await post('/authorizations', `{"to_handle":"bob","amount":${lit}}`), 422, 'validation_failed');
    err(await c.post('/settlements', { token: t.op, key: k(), raw: `{"transfers":[{"from_handle":"ada","to_handle":"bob","amount":${lit}}]}` }), 422, 'validation_failed');
  }
  const a = (await c.post('/authorizations', { ...h, key: k(), body: { to_handle: 'bob', amount: 1000 } })).json.authorization_id;
  for (const lit of lits) err(await c.post(`/authorizations/${a}/capture`, { token: t.bob, key: k(), raw: `{"amount":${lit}}` }), 422, 'validation_failed');
  for (const lit of ['1000', '1000.0', '1e3', '1.0e3', '10E2', '1000.000000000000000000000', '0.1e4', '100e1']) {
    const r = await post('/payments', `{"to_handle":"bob","amount":${lit}}`);
    assert.equal(r.status, 201, lit); assert.equal(r.json.amount, 1000); assert.match(r.text, /"amount":1000,/);
  }
  assert.equal((await post('/payments', '{"to_handle":"bob","amount":1.5e1}')).json.amount, 15);
  // ordinary fractions and strings stay rejected
  for (const lit of ['1.5', '1000000000.5', '"5"', 'true', 'null', '1e400']) err(await post('/payments', `{"to_handle":"bob","amount":${lit}}`), 422, 'validation_failed');
  // a literal inside a string is not a number
  const n = await post('/payments', '{"to_handle":"bob","amount":1,"note":"1.0000000000000000000001"}');
  assert.equal(n.json.note, '1.0000000000000000000001');
  // fixtures too
  err(await c.post('/_test/reset', { raw: '{"currency":"EUR","minor_units":2,"users":[{"id":"a","email":"a@x.io","password":"password1","display_name":"A","handle":"a","balance":1.0000000000000000000001}]}' }), 422, 'validation_failed');
  await c.reset(FX());
  t.ada = await login(c, 'ada@example.com'); t.bob = await login(c, 'bob@example.com'); t.op = await login(c, 'op@example.com');
});

test('L1/L2/L5: content negotiation and routes', async () => {
  const get = (p, accept) => fetch(c.base + p, { headers: accept === undefined ? {} : { accept } });
  for (const p of ['/', '/split', '/signup', '/login']) {
    const r = await get(p, 'text/html');
    assert.equal(r.status, 200); assert.match(r.headers.get('content-type'), /^text\/html/);
    assert.match(await r.text(), /<div id="app">/);
  }
  for (const p of ['/requests', '/authorizations']) {
    const r = await get(p, 'text/html,application/xhtml+xml,*/*;q=0.8');
    assert.equal(r.status, 200); assert.match(r.headers.get('content-type'), /^text\/html/);
    for (const accept of [undefined, '*/*', 'application/json']) {
      const j = await get(p, accept);
      assert.equal(j.status, 401); assert.equal(j.headers.get('content-type'), 'application/json; charset=utf-8');
      assert.equal((await j.json()).error.code, 'unauthenticated');
      const ok = await fetch(c.base + p, { headers: { authorization: `Bearer ${t.ada}`, ...(accept ? { accept } : {}) } });
      assert.equal(ok.status, 200); assert.match(ok.headers.get('content-type'), /json/);
    }
  }
  // POSTs never return HTML; UI routes do not shadow API paths
  const post = await fetch(c.base + '/requests', { method: 'POST', headers: { accept: 'text/html', authorization: `Bearer ${t.ada}`, 'idempotency-key': k(), 'content-type': 'application/json' }, body: '{"payer_handle":"bob","amount":5}' });
  assert.equal(post.status, 201); assert.match(post.headers.get('content-type'), /json/);
  const split = await fetch(c.base + '/split', { method: 'POST', headers: { accept: 'text/html' } });
  assert.equal(split.status, 404); assert.equal((await split.json()).error.code, 'not_found');
  // assets are served from the image, with the right types; unknown assets are an error envelope
  for (const [p, type] of [['/assets/style.css', /text\/css/], ['/assets/js/app.js', /javascript/], ['/assets/js/money.js', /javascript/]]) {
    const r = await get(p); assert.equal(r.status, 200); assert.match(r.headers.get('content-type'), type);
  }
  assert.equal((await get('/assets/nope.js')).status, 404);
  assert.equal((await get('/assets/../src/server.js')).status, 404);
  assert.equal((await get('/assets/%2e%2e/src/server.js')).status, 404);
});

test('K3: no external URL anywhere in the shipped UI', () => {
  const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..', 'public');
  const files = [];
  (function walk(d) { for (const f of fs.readdirSync(d)) { const p = path.join(d, f); fs.statSync(p).isDirectory() ? walk(p) : files.push(p); } })(root);
  assert.ok(files.length > 10);
  for (const f of files) {
    const text = fs.readFileSync(f, 'utf8');
    assert.ok(!/https?:\/\//i.test(text), `${f} mentions an absolute URL`);
    assert.ok(!/@import|url\(\s*['"]?\/\//.test(text), `${f} imports external CSS`);
  }
});

test('AA3: no stage-4 surface', async () => {
  for (const p of ['/payments/p_1/refunds', '/refunds', '/correction-batches', '/correction-batches/x']) {
    const r = await c.get(p, { token: t.ada }); assert.equal(r.status, 404, p);
    assert.equal((await c.post(p, { token: t.ada, key: k(), body: {} })).status, 404, p);
  }
  const pay = (await c.post('/payments', { token: t.ada, key: k(), body: { to_handle: 'bob', amount: 5 } })).json;
  assert.ok(!('refund_of' in pay));
  const cor = await c.post(`/payments/${pay.payment_id}/corrections`, { token: t.ada, key: k(), body: { expected_revision: 1, amount: 4, effective_at: pay.created_at, reason: 'r' } });
  assert.equal(cor.status, 201);
  assert.ok(!('correction_batch_id' in cor.json));
  const revs = (await c.get(`/payments/${pay.payment_id}/revisions`, { token: t.ada })).json.revisions;
  assert.ok(revs.every((r) => !('correction_batch_id' in r)));
});

// Needs the sibling ../stage-1 folder (a source checkout); skipped inside the image, where docker-upgrade.sh covers it.
test('R7/T12/T13: upgrade from a real stage-1 service', { skip: !fs.existsSync(stage1Dir) && 'stage-1 folder not present' }, async () => {
  const old = await startServer({}, stage1Dir);
  try {
    assert.equal((await old.reset(FX())).status, 204);
    const tk = {};
    for (const n of ['ada', 'bob', 'cy', 'op']) tk[n] = await login(old, `${n}@example.com`);
    const keys = { pay: k(), req: k(), split: k(), settle: k(), payreq: k() };
    const calls = {
      pay: ['/payments', tk.ada, { to_handle: 'bob', amount: 100, note: 'é😀', visibility: 'private' }],
      req: ['/requests', tk.bob, { payer_handle: 'ada', amount: 300 }],
      split: ['/splits', tk.ada, { amount: 10, participant_handles: ['ada', 'bob', 'cy'] }],
      settle: ['/settlements', tk.op, { transfers: [{ from_handle: 'ada', to_handle: 'cy', amount: 50 }] }],
    };
    const resp = {};
    for (const [n, [p, token, body]] of Object.entries(calls)) { resp[n] = await old.post(p, { token, key: keys[n], body }); assert.equal(resp[n].status, 201); }
    const pending = (await old.post('/requests', { token: tk.bob, key: k(), body: { payer_handle: 'ada', amount: 77 } })).json.request_id;
    calls.payreq = [`/requests/${resp.req.json.request_id}/pay`, tk.ada, { visibility: 'private' }];
    resp.payreq = await old.post(calls.payreq[0], { token: tk.ada, key: keys.payreq, body: calls.payreq[2] });
    assert.equal(resp.payreq.status, 201);
    const failKey = k();
    err(await old.post('/payments', { token: tk.cy, key: failKey, body: { to_handle: 'bob', amount: 99999999 } }), 409, 'insufficient_funds');
    const ex = (await old.get('/_test/export')).json;
    assert.equal(ex.state.schema_version, 1);
    assert.equal((await c.post('/_test/import', { body: ex })).status, 204);
    // tokens, logins, balances
    const mine = async (n) => (await c.get('/me', { token: tk[n] })).json;
    assert.deepEqual(await mine('ada'), { user_id: 'u_ada', display_name: 'Ada', handle: 'ada', balance: 9550, total: 9550, available: 9550, held: 0, currency: 'EUR', minor_units: 2 });
    assert.equal((await c.post('/auth/login', { body: { email: 'bob@example.com', password: 'correct horse' } })).status, 200);
    assert.equal(await balanceSum(c, Object.values(tk)), 12500);
    // payments gain authorization_id: null; originals replay exactly as stored
    const feed = (await c.get('/activity?limit=200', { token: tk.ada })).json.payments;
    assert.ok(feed.length >= 3 && feed.every((p) => p.authorization_id === null));
    for (const [n, [p, token, body]] of Object.entries(calls)) {
      const rep = await c.post(p, { token, key: keys[n], body });
      assert.equal(rep.status, 200, n); assert.equal(rep.text, resp[n].text, n);
      err(await c.post(p, { token, key: keys[n], body: { ...body, zzz: 1 } }), 409, 'idempotency_key_reuse');
    }
    assert.ok(!('authorization_id' in (await c.post(...calls.pay.slice(0, 1), { token: tk.ada, key: keys.pay, body: calls.pay[2] })).json), 'stored response replayed unchanged');
    assert.equal((await c.post('/payments', { token: tk.ada, key: failKey, body: { to_handle: 'bob', amount: 1 } })).status, 201);
    // pending request payable; operators keep their rights; default ttl 600
    assert.equal((await c.post(`/requests/${pending}/pay`, { token: tk.ada, key: k(), body: {} })).status, 201);
    assert.equal((await c.post('/settlements', { token: tk.op, key: k(), body: { transfers: [{ from_handle: 'ada', to_handle: 'bob', amount: 1 }] } })).status, 201);
    err(await c.post('/settlements', { token: tk.ada, key: k(), body: { transfers: [] } }), 403, 'forbidden');
    const a = (await c.post('/authorizations', { token: tk.ada, key: k(), body: { to_handle: 'bob', amount: 10 } })).json;
    assert.equal(Date.parse(a.expires_at) - Date.parse(a.created_at), 600000);
    assert.deepEqual((await c.get('/authorizations', { token: tk.bob })).json.authorizations.map((x) => x.authorization_id), [a.authorization_id]);
    // stage-1 timestamps are kept untouched
    const orig = ex.state.payments.map((p) => [p.payment_id, p.created_at]);
    const now = (await c.get('/_test/export')).json.state.payments;
    for (const [id, at] of orig) assert.equal(now.find((p) => p.payment_id === id).created_at, at);
  } finally { old.stop(); }
});
