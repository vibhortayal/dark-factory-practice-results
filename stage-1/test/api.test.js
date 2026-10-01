import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { setup, FX, k } from './helper.js';

let c, t;
before(async () => ({ c, t } = await setup({
  payments: [{ id: 'p_1', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 500, note: 'coffee', visibility: 'public' }],
  requests: [{ id: 'rq_1', requester_id: 'u_bob', payer_id: 'u_ada', amount: 1200, note: 'taxi', status: 'pending' }],
})));
after(() => c.stop());

const RFC = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?[+-]\d{2}:\d{2}$/;
const err = (r, status, code) => { assert.equal(r.status, status, r.text); assert.equal(r.json.error.code, code); assert.equal(typeof r.json.error.message, 'string'); };

test('B: health, headers, unknown route', async () => {
  const h = await c.get('/health');
  assert.deepEqual(h.json, { status: 'ok' });
  assert.equal(h.headers.get('content-type'), 'application/json; charset=utf-8');
  const nf = await c.get('/nope');
  err(nf, 404, 'not_found');
  assert.equal(nf.headers.get('content-type'), 'application/json; charset=utf-8');
  err(await c.call('DELETE', '/payments'), 404, 'not_found');
});

test('C14/C18/G1: seeded data, /me shape, seeded balances not replayed', async () => {
  const me = await c.get('/me', { token: t.ada });
  assert.deepEqual(me.json, { user_id: 'u_ada', display_name: 'Ada', handle: 'ada', balance: 10000, currency: 'EUR', minor_units: 2 });
  const act = await c.get('/activity', { token: t.cy });
  assert.equal(act.json.payments.length, 1);
  assert.equal(act.json.payments[0].payment_id, 'p_1');
  assert.equal(act.json.payments[0].settlement_id, null);
  assert.match(act.json.payments[0].created_at, RFC);
  const rq = await c.get('/requests', { token: t.cy });
  assert.deepEqual(rq.json, { requests: [], has_more: false });
});

test('D7/E10: authentication on every endpoint', async () => {
  const eps = [['GET', '/me'], ['POST', '/payments'], ['POST', '/requests'], ['POST', '/splits'], ['POST', '/settlements'], ['GET', '/requests'], ['GET', '/activity'], ['POST', '/requests/rq_1/pay'], ['POST', '/requests/rq_1/decline'], ['POST', '/requests/rq_1/cancel']];
  for (const [m, p] of eps) {
    err(await c.call(m, p, { body: {}, key: k() }), 401, 'unauthenticated');
    err(await c.call(m, p, { body: {}, key: k(), headers: { authorization: 'Basic x' } }), 401, 'unauthenticated');
    err(await c.call(m, p, { body: {}, key: k(), token: 'nope' }), 401, 'unauthenticated');
  }
});

test('E: signup and login rules', async () => {
  const s = await c.post('/auth/signup', { body: { email: 'A.B-c+d@x.io', password: 'longenough', display_name: 'ABCD' } });
  assert.equal(s.status, 201);
  assert.deepEqual(Object.keys(s.json).sort(), ['display_name', 'token', 'user_id']);
  const me = await c.get('/me', { token: s.json.token });
  assert.equal(me.json.handle, 'a_b_c_d');
  assert.equal(me.json.balance, 0);
  err(await c.post('/auth/signup', { body: { email: 'A.B-c+d@x.io', password: 'longenough', display_name: 'x' } }), 409, 'email_taken');
  err(await c.post('/auth/signup', { body: { email: 'a_b_c_d@y.io', password: 'longenough', display_name: 'x' } }), 409, 'handle_taken');
  assert.equal((await c.post('/auth/login', { body: { email: 'a_b_c_d@y.io', password: 'longenough' } })).status, 401);
  const long = await c.post('/auth/signup', { body: { email: 'abcdefghijklmnopqrstuvwxy@z.io', password: 'longenough', display_name: 'L' } });
  assert.equal((await c.get('/me', { token: long.json.token })).json.handle, 'abcdefghijklmnopqrst');
  err(await c.post('/auth/signup', { body: { email: 'seven@x.io', password: '1234567', display_name: 'x' } }), 422, 'validation_failed');
  assert.equal((await c.post('/auth/signup', { body: { email: 'eight@x.io', password: '12345678', display_name: 'x' } })).status, 201);
  for (const e of ['noat', '@x.io', 'a@']) err(await c.post('/auth/signup', { body: { email: e, password: 'longenough', display_name: 'x' } }), 422, 'validation_failed');
  err(await c.post('/auth/signup', { body: { password: 'longenough', display_name: 'x' } }), 422, 'validation_failed');
  err(await c.post('/auth/signup', { body: { email: 1, password: 'longenough', display_name: 'x' } }), 400, 'malformed_request');
  err(await c.post('/auth/signup', { raw: '{' }), 400, 'malformed_request');
  // login: new token each time, earlier tokens stay valid
  const l1 = await c.post('/auth/login', { body: { email: 'eight@x.io', password: '12345678' } });
  const l2 = await c.post('/auth/login', { body: { email: 'eight@x.io', password: '12345678' } });
  assert.notEqual(l1.json.token, l2.json.token);
  assert.equal((await c.get('/me', { token: l1.json.token })).status, 200);
  err(await c.post('/auth/login', { body: { email: 'eight@x.io', password: 'wrong-pass' } }), 401, 'unauthenticated');
  err(await c.post('/auth/login', { body: { email: 'ghost@x.io', password: 'wrong-pass' } }), 401, 'unauthenticated');
  err(await c.post('/auth/login', { body: { email: 'eight@x.io' } }), 422, 'validation_failed');
});

test('G2-G9: payments', async () => {
  const ok = await c.post('/payments', { token: t.ada, key: k(), body: { to_handle: 'bob', amount: 1500, note: 'dinner' } });
  assert.equal(ok.status, 201);
  assert.deepEqual(Object.keys(ok.json), ['payment_id', 'from_user_id', 'from_handle', 'to_user_id', 'to_handle', 'amount', 'currency', 'note', 'visibility', 'request_id', 'settlement_id', 'created_at']);
  assert.equal(ok.json.visibility, 'public');
  assert.equal(ok.json.request_id, null);
  assert.match(ok.json.created_at, RFC);
  assert.match(ok.text, /"amount":1500,/);
  const bad = async (body, st, code) => err(await c.post('/payments', { token: t.ada, key: k(), body }), st, code);
  for (const a of [0, -1, 1000000001, 1.5, '5', true, null]) await bad({ to_handle: 'bob', amount: a }, 422, 'validation_failed');
  await bad({ to_handle: 'bob' }, 422, 'validation_failed');
  await bad({ to_handle: 'ada', amount: 5 }, 422, 'self_payment');
  await bad({ to_handle: 'nobody', amount: 5 }, 404, 'not_found');
  for (const h of ['', 'ADA', '@ada']) await bad({ to_handle: h, amount: 5 }, 404, 'not_found');
  await bad({ to_handle: 5, amount: 5 }, 400, 'malformed_request');
  await bad({ amount: 5 }, 422, 'validation_failed');
  await bad({ to_handle: 'bob', amount: 5, note: null }, 422, 'validation_failed');
  await bad({ to_handle: 'bob', amount: 5, note: 5 }, 422, 'validation_failed');
  for (const v of [null, '', 'Public', 5]) await bad({ to_handle: 'bob', amount: 5, visibility: v }, 422, 'validation_failed');
  await bad({ to_handle: 'bob', amount: 5, note: 'x'.repeat(201) }, 422, 'validation_failed');
  await bad({ to_handle: 'bob', amount: 5, note: '😀'.repeat(201) }, 422, 'validation_failed');
  for (const note of ['x'.repeat(200), '😀'.repeat(200), '  <script>&amp; é \t ']) {
    const r = await c.post('/payments', { token: t.ada, key: k(), body: { to_handle: 'cy', amount: 1, note } });
    assert.equal(r.status, 201); assert.equal(r.json.note, note);
  }
  // raw numeric spellings
  for (const raw of ['1000.0', '1e3']) {
    const r = await c.post('/payments', { token: t.ada, key: k(), raw: `{"to_handle":"cy","amount":${raw}}` });
    assert.equal(r.status, 201); assert.equal(r.json.amount, 1000); assert.match(r.text, /"amount":1000,/);
  }
  for (const raw of ['1.5', '1e400', '"5"', '1e-1']) err(await c.post('/payments', { token: t.ada, key: k(), raw: `{"to_handle":"cy","amount":${raw}}` }), 422, 'validation_failed');
  // unknown fields ignored, unknown query parameters ignored
  assert.equal((await c.post('/payments?x=1', { token: t.ada, key: k(), body: { to_handle: 'cy', amount: 1, extra: [1] } })).status, 201);
  assert.equal((await c.get('/me?foo=bar', { token: t.ada })).status, 200);
  // boundaries
  const before = (await c.get('/me', { token: t.cy })).json.balance;
  const exact = await c.post('/payments', { token: t.cy, key: k(), body: { to_handle: 'ada', amount: before } });
  assert.equal(exact.status, 201);
  err(await c.post('/payments', { token: t.cy, key: k(), body: { to_handle: 'ada', amount: 1 } }), 409, 'insufficient_funds');
  assert.equal((await c.get('/me', { token: t.cy })).json.balance, 0);
});

test('G10-G17: requests lifecycle', async () => {
  const mk = async (amount = 100, body = {}) => c.post('/requests', { token: t.bob, key: k(), body: { payer_handle: 'ada', amount, note: 'n', ...body } });
  const r = await mk(900000);
  assert.equal(r.status, 201);
  assert.deepEqual(Object.keys(r.json), ['request_id', 'requester_id', 'requester_handle', 'payer_id', 'payer_handle', 'amount', 'currency', 'note', 'status', 'payment_id', 'created_at']);
  assert.equal(r.json.status, 'pending');
  assert.ok(!('visibility' in r.json));
  err(await c.post('/requests', { token: t.bob, key: k(), body: { payer_handle: 'bob', amount: 5 } }), 422, 'self_request');
  err(await c.post('/requests', { token: t.bob, key: k(), body: { payer_handle: 'zzz', amount: 5 } }), 404, 'not_found');
  err(await c.post('/requests', { token: t.bob, key: k(), body: { payer_handle: 'ada', amount: 0 } }), 422, 'validation_failed');
  const id = r.json.request_id;
  err(await c.post(`/requests/${id}/pay`, { token: t.ada, key: k(), body: {} }), 409, 'insufficient_funds');
  assert.equal((await c.post(`/requests/${id}/pay`, { token: t.bob, key: k(), body: {} })).status, 403);
  assert.equal((await c.post(`/requests/${id}/pay`, { token: t.cy, key: k(), body: {} })).status, 403);
  err(await c.post(`/requests/nope/pay`, { token: t.ada, key: k(), body: {} }), 404, 'not_found');
  err(await c.post(`/requests/${id}/pay`, { token: t.ada, key: k(), body: { visibility: 'x' } }), 422, 'validation_failed');
  err(await c.post(`/requests/${id}/decline`, { token: t.bob }), 403, 'forbidden');
  err(await c.post(`/requests/${id}/cancel`, { token: t.ada }), 403, 'forbidden');
  err(await c.post(`/requests/nope/cancel`, { token: t.ada }), 404, 'not_found');
  const cancel = await c.post(`/requests/${id}/cancel`, { token: t.bob, key: 'ignored' });
  assert.equal(cancel.json.status, 'cancelled');
  assert.equal((await c.post(`/requests/${id}/cancel`, { token: t.bob })).status, 200);
  err(await c.post(`/requests/${id}/decline`, { token: t.ada }), 409, 'request_not_pending');
  err(await c.post(`/requests/${id}/pay`, { token: t.ada, key: k(), body: {} }), 409, 'request_not_pending');
  // decline path
  const d = (await mk(10)).json.request_id;
  assert.equal((await c.post(`/requests/${d}/decline`, { token: t.ada, raw: '' })).json.status, 'declined');
  assert.equal((await c.post(`/requests/${d}/decline`, { token: t.ada })).status, 200);
  err(await c.post(`/requests/${d}/cancel`, { token: t.bob }), 409, 'request_not_pending');
  // pay path with private visibility and empty body default
  const p1 = (await mk(10)).json.request_id;
  const paid = await c.post(`/requests/${p1}/pay`, { token: t.ada, key: k(), body: { visibility: 'private' } });
  assert.equal(paid.status, 201);
  assert.equal(paid.json.request_id, p1);
  assert.equal(paid.json.visibility, 'private');
  assert.equal(paid.json.from_handle, 'ada');
  err(await c.post(`/requests/${p1}/cancel`, { token: t.bob }), 409, 'request_not_pending');
  const list = (await c.get('/requests?direction=outgoing&status=paid', { token: t.bob })).json.requests;
  assert.equal(list.find((x) => x.request_id === p1).payment_id, paid.json.payment_id);
  const p2 = (await mk(10)).json.request_id;
  const emptyPay = await c.post(`/requests/${p2}/pay`, { token: t.ada, key: k() });
  assert.equal(emptyPay.status, 201);
  assert.equal(emptyPay.json.visibility, 'public');
  // private payment hidden from a third party, visible to both parties
  assert.ok(!(await c.get('/activity?limit=200', { token: t.cy })).json.payments.some((p) => p.payment_id === paid.json.payment_id));
  for (const tok of [t.ada, t.bob]) assert.ok((await c.get('/activity?limit=200', { token: tok })).json.payments.some((p) => p.payment_id === paid.json.payment_id));
  assert.ok(!(await c.get('/activity?limit=200', { token: t.op })).json.payments.some((p) => p.payment_id === paid.json.payment_id));
  // request payable later once funded
  const big = (await mk(11000000)).json.request_id;
  err(await c.post(`/requests/${big}/pay`, { token: t.ada, key: k(), body: {} }), 409, 'insufficient_funds');
  assert.equal((await c.get('/requests?status=pending', { token: t.ada })).json.requests.some((x) => x.request_id === big), true);
});

test('D8/G18/G25: paging and query validation', async () => {
  for (let i = 0; i < 5; i++) await c.post('/requests', { token: t.cy, key: k(), body: { payer_handle: 'bob', amount: 1 + i } });
  const p1 = await c.get('/requests?limit=2&offset=0&direction=outgoing', { token: t.cy });
  assert.equal(p1.json.requests.length, 2); assert.equal(p1.json.has_more, true);
  assert.deepEqual(p1.json.requests.map((x) => x.amount), [5, 4]);
  const p3 = await c.get('/requests?limit=2&offset=4&direction=outgoing', { token: t.cy });
  assert.equal(p3.json.requests.length, 1); assert.equal(p3.json.has_more, false);
  const far = await c.get('/requests?offset=100&direction=outgoing', { token: t.cy });
  assert.deepEqual(far.json, { requests: [], has_more: false });
  for (const q of ['limit=0', 'limit=201', 'limit=-1', 'limit=abc', 'limit=', 'limit=1e1', 'limit=4.0', 'limit=%2B4', 'limit=+4', 'offset=-1', 'offset=1e9', 'offset=', 'direction=sideways', 'status=weird']) {
    err(await c.get('/requests?' + q, { token: t.cy }), 422, 'validation_failed');
    if (q.startsWith('limit') || q.startsWith('offset')) err(await c.get('/activity?' + q, { token: t.cy }), 422, 'validation_failed');
  }
  assert.equal((await c.get('/requests?limit=200', { token: t.cy })).status, 200);
  assert.equal((await c.get('/activity?direction=nonsense&status=x', { token: t.cy })).status, 200);
  // requests never in the feed
  assert.ok((await c.get('/activity?limit=200', { token: t.cy })).json.payments.every((p) => 'payment_id' in p));
});

test('G19-G24/H3: splits', async () => {
  const sp = await c.post('/splits', { token: t.ada, key: k(), body: { amount: 1000, participant_handles: ['ada', 'bob', 'cy'], note: 'dinner' } });
  assert.equal(sp.status, 201);
  assert.deepEqual(sp.json.shares, [{ handle: 'ada', amount: 334 }, { handle: 'bob', amount: 333 }, { handle: 'cy', amount: 333 }]);
  assert.deepEqual(sp.json.requests.map((r) => [r.payer_handle, r.amount, r.requester_handle, r.note, r.status]), [['bob', 333, 'ada', 'dinner', 'pending'], ['cy', 333, 'ada', 'dinner', 'pending']]);
  assert.deepEqual(Object.keys(sp.json), ['split_id', 'amount', 'currency', 'note', 'shares', 'requests', 'created_at']);
  const omit = await c.post('/splits', { token: t.ada, key: k(), body: { amount: 10, participant_handles: ['cy', 'bob', 'op'] } });
  assert.deepEqual(omit.json.shares.map((s) => s.amount), [4, 3, 3]);
  assert.equal(omit.json.requests.length, 3);
  const one = await c.post('/splits', { token: t.ada, key: k(), body: { amount: 1, participant_handles: ['ada', 'bob', 'cy'] } });
  assert.deepEqual(one.json.shares.map((s) => s.amount), [1, 0, 0]);
  assert.deepEqual(one.json.requests.map((r) => r.amount), [0, 0]);
  // zero-share request is payable (CHOICE G23)
  const z = await c.post(`/requests/${one.json.requests[0].request_id}/pay`, { token: t.bob, key: k(), body: {} });
  assert.equal(z.status, 201); assert.equal(z.json.amount, 0);
  const solo = await c.post('/splits', { token: t.ada, key: k(), body: { amount: 500, participant_handles: ['ada'] } });
  assert.equal(solo.status, 201); assert.deepEqual(solo.json.requests, []); assert.deepEqual(solo.json.shares, [{ handle: 'ada', amount: 500 }]);
  const bad = async (body, st, code) => err(await c.post('/splits', { token: t.ada, key: k(), body }), st, code);
  await bad({ amount: 5, participant_handles: [] }, 422, 'validation_failed');
  await bad({ amount: 5, participant_handles: ['bob', 'bob'] }, 422, 'validation_failed');
  await bad({ amount: 5, participant_handles: ['bob', 'bob', 'ghost'] }, 422, 'validation_failed');
  await bad({ amount: 5 }, 422, 'validation_failed');
  await bad({ amount: 5, participant_handles: 'bob' }, 400, 'malformed_request');
  await bad({ amount: 5, participant_handles: ['bob', 5] }, 400, 'malformed_request');
  await bad({ amount: 0, participant_handles: ['bob'] }, 422, 'validation_failed');
  await bad({ amount: 5, participant_handles: ['bob'], note: 'x'.repeat(201) }, 422, 'validation_failed');
  // atomic failure: unknown handle creates no requests
  const before = (await c.get('/requests?limit=200&direction=outgoing', { token: t.ada })).json.requests.length;
  await bad({ amount: 5, participant_handles: ['bob', 'ghost'] }, 404, 'not_found');
  assert.equal((await c.get('/requests?limit=200&direction=outgoing', { token: t.ada })).json.requests.length, before);
  // 1000 handles: validated, not a crash
  await bad({ amount: 5, participant_handles: Array.from({ length: 1000 }, (_, i) => `h${i}`) }, 404, 'not_found');
  // split is not a feed item
  assert.ok((await c.get('/activity?limit=200', { token: t.bob })).json.payments.every((p) => !('split_id' in p)));
});

test('H3: equal split property', async () => {
  const { equalShares } = await import('../src/ledger.js');
  for (const amount of [0, 1, 2, 5, 10, 999, 1000, 1000000000, 7919]) {
    for (const n of [1, 2, 3, 5, 7, 11, 100]) {
      const s = equalShares(amount, n);
      assert.equal(s.reduce((a, b) => a + b, 0), amount);
      assert.ok(Math.max(...s) - Math.min(...s) <= 1);
      assert.deepEqual(s, [...s].sort((a, b) => b - a));
    }
  }
  assert.deepEqual(equalShares(999, 3), [333, 333, 333]);
  assert.deepEqual(equalShares(5, 5), [1, 1, 1, 1, 1]);
});

test('B3/B7/C1/C16/C17: reset behaviour', async () => {
  const tok = t.ada;
  const key = k();
  await c.post('/payments', { token: tok, key, body: { to_handle: 'bob', amount: 1 } });
  err(await c.reset({ ...FX(), users: [{ id: 'x', email: 'x@x.io', password: 'password1', display_name: 'X', handle: 'x', balance: -1 }] }), 422, 'validation_failed');
  assert.equal((await c.get('/me', { token: tok })).status, 200, 'failed reset changes nothing');
  const invalids = [
    [], 5, { currency: 'EUR' }, { ...FX(), currency: 5 }, { ...FX(), minor_units: 1 }, { ...FX(), users: 'x' },
    { ...FX(), users: [{ ...FX().users[0] }, { ...FX().users[0] }] },
    { ...FX(), users: [{ ...FX().users[0], handle: 'Bad Handle' }] },
    { ...FX(), users: [{ ...FX().users[0], balance: 1.5 }] },
    { ...FX(), users: [{ ...FX().users[0] }, { ...FX().users[1], id: 'z', handle: 'ada' }] },
    { ...FX(), users: [{ ...FX().users[0] }, { ...FX().users[1], id: 'z', email: 'ada@example.com' }] },
    { ...FX(), payments: [{ id: 'p', from_user_id: 'ghost', to_user_id: 'u_ada', amount: 1 }] },
    { ...FX(), requests: [{ id: 'r', requester_id: 'u_ada', payer_id: 'u_bob', amount: 1, status: 'nope' }] },
    { ...FX(), payments: [{ id: 'p', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 1, visibility: 'secret' }] },
    { ...FX(), settlement_operator_ids: ['ghost'] },
  ];
  for (const bad of invalids) {
    err(await c.reset(bad), 422, 'validation_failed');
  }
  err(await c.post('/_test/reset', { raw: '{nope' }), 400, 'malformed_request');
  assert.equal((await c.get('/me', { token: tok })).status, 200);
  // JPY and BHD, omitted optional arrays
  const jpy = { currency: 'JPY', minor_units: 0, users: [{ id: 'a', email: 'a@x.io', password: 'password1', display_name: 'A', handle: 'a', balance: 1000 }] };
  assert.equal((await c.reset(jpy)).status, 204);
  const tk = (await c.post('/auth/login', { body: { email: 'a@x.io', password: 'password1' } })).json.token;
  assert.deepEqual((await c.get('/me', { token: tk })).json, { user_id: 'a', display_name: 'A', handle: 'a', balance: 1000, currency: 'JPY', minor_units: 0 });
  // after reset: old token 401, old idempotency key is a first use
  err(await c.get('/me', { token: tok }), 401, 'unauthenticated');
  assert.equal((await c.reset(FX())).status, 204);
  const t2 = (await c.post('/auth/login', { body: { email: 'ada@example.com', password: 'correct horse' } })).json.token;
  assert.equal((await c.post('/payments', { token: t2, key, body: { to_handle: 'bob', amount: 1 } })).status, 201);
  // large balances stay exact
  const big = { currency: 'EUR', minor_units: 2, users: [{ id: 'a', email: 'a@x.io', password: 'password1', display_name: 'A', handle: 'a', balance: 9007199254740000 }, { id: 'b', email: 'b@x.io', password: 'password1', display_name: 'B', handle: 'b', balance: 0 }] };
  assert.equal((await c.reset(big)).status, 204);
  const tb = (await c.post('/auth/login', { body: { email: 'a@x.io', password: 'password1' } })).json.token;
  for (let i = 0; i < 3; i++) assert.equal((await c.post('/payments', { token: tb, key: k(), body: { to_handle: 'b', amount: 1000000000 } })).status, 201);
  assert.equal((await c.get('/me', { token: tb })).json.balance, 9007199254740000 - 3000000000);
  // F1: large balances next to other non-empty wallets, up to 2^53 inclusive
  const mk = (x, y) => ({ currency: 'EUR', minor_units: 2, users: [{ id: 'a', email: 'a@x.io', password: 'password1', display_name: 'A', handle: 'a', balance: x }, { id: 'b', email: 'b@x.io', password: 'password1', display_name: 'B', handle: 'b', balance: y }] });
  for (const [x, y] of [[9007199254740991, 2500], [9007199254740000, 9007199254740000], [9007199254740992, 0]]) {
    assert.equal((await c.reset(mk(x, y))).status, 204, `${x} ${y}`);
    const e = await c.get('/_test/export');
    assert.equal((await c.post('/_test/import', { body: e.json })).status, 204);
  }
  err(await c.reset(mk(9007199254740994, 0)), 422, 'validation_failed');
});
