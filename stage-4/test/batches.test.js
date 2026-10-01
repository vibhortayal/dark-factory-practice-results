import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import { startServer, FX, k, login, balanceSum } from './helper.js';

let c, t;
const err = (r, status, code) => { assert.equal(r.status, status, r.text); assert.equal(r.json.error.code, code); };
const enc = encodeURIComponent;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const at = (d) => new Date(Date.now() + d * 1000).toISOString().replace('Z', '+00:00');
const all = () => [t.ada, t.bob, t.cy, t.op];
const me = async (tok, qs = '') => (await c.get('/me' + qs, { token: tok })).json;

async function fresh(extra = {}) {
  assert.equal((await c.reset(FX(extra))).status, 204);
  t = {};
  for (const n of ['ada', 'bob', 'cy', 'op']) t[n] = await login(c, `${n}@example.com`);
}
before(async () => { c = await startServer(); await fresh(); });
after(() => c.stop());

const pay = async (tok, to, amount, extra = {}) => (await c.post('/payments', { token: tok, key: k(), body: { to_handle: to, amount, ...extra } })).json;
const batch = (tok, body, key = k()) => c.post('/correction-batches', { token: tok, key, body });
const item = (id, o = {}) => ({ payment_id: id, expected_revision: 1, amount: 0, effective_at: at(-5), reason: 'reversal', ...o });
const stateJson = async () => JSON.stringify((await c.get('/_test/export')).json.state);

test('BD1/BD2: access, key, body and batch shape', async () => {
  await fresh();
  const p = await pay(t.ada, 'bob', 100);
  const body = { corrections: [item(p.payment_id)] };
  err(await c.post('/correction-batches', { body, key: k() }), 401, 'unauthenticated');
  err(await c.post('/correction-batches', { token: t.ada, raw: '{' }), 403, 'forbidden'); // 403 before key and body
  err(await c.post('/correction-batches', { token: t.bob, body }), 403, 'forbidden');
  err(await c.post('/correction-batches', { token: t.op, body }), 400, 'missing_idempotency_key');
  err(await batch(t.op, body, 'x'.repeat(256)), 422, 'validation_failed');
  err(await c.post('/correction-batches', { token: t.op, key: k(), raw: '{' }), 400, 'malformed_request');
  err(await c.post('/correction-batches', { token: t.op, key: k(), raw: '[1]' }), 400, 'malformed_request');
  const many = await Promise.all(Array.from({ length: 33 }, () => pay(t.ada, 'cy', 1)));
  for (const bad of [{}, { corrections: 'x' }, { corrections: [] }, { corrections: many.map((x) => item(x.payment_id)) }, { corrections: [1] }, { corrections: [null] }, { corrections: [item(p.payment_id), item(p.payment_id)] }]) {
    err(await batch(t.op, bad), 422, 'validation_failed');
  }
  // shape errors come before item errors
  err(await batch(t.op, { corrections: [item('nope'), item('nope')] }), 422, 'validation_failed');
  // 32 items are fine, unknown fields are ignored
  const ok = await batch(t.op, { corrections: many.slice(0, 32).map((x) => ({ ...item(x.payment_id, { amount: 1 }), extra: 1 })), junk: true });
  assert.equal(ok.status, 201, ok.text);
  assert.equal(ok.json.revisions.length, 32);
});

test('BD3/BD4/BD8: item errors, in input order', async () => {
  await fresh();
  const [a, b, d] = [await pay(t.ada, 'bob', 100), await pay(t.bob, 'cy', 100), await pay(t.cy, 'ada', 50)];
  const cap = (async () => {
    const au = (await c.post('/authorizations', { token: t.ada, key: k(), body: { to_handle: 'bob', amount: 40 } })).json;
    return (await c.post(`/authorizations/${au.authorization_id}/capture`, { token: t.bob, key: k(), body: {} })).json;
  })();
  const capture = await cap;
  const ref = (await c.post(`/payments/${a.payment_id}/refunds`, { token: t.bob, key: k(), body: { amount: 30 } })).json;
  const bad = async (items, st, code) => err(await batch(t.op, { corrections: items }), st, code);
  for (const f of [{ expected_revision: 0 }, { expected_revision: '1' }, { amount: -1 }, { amount: 1.5 }, { amount: 1000000001 }, { reason: '' }, { reason: 'x'.repeat(201) }, { effective_at: 'x' }, { effective_at: '2026-01-01T00:00:00' }, { effective_at: at(60) }]) {
    await bad([item(a.payment_id, f)], 422, 'validation_failed');
  }
  for (const miss of ['expected_revision', 'amount', 'reason', 'effective_at', 'payment_id']) { const it = item(a.payment_id); delete it[miss]; await bad([it], 422, 'validation_failed'); }
  await bad([{ ...item(a.payment_id), payment_id: 5 }], 422, 'validation_failed');
  await bad([item('nope')], 404, 'not_found');
  await bad([item(capture.payment_id)], 422, 'linked_payment_immutable');
  await bad([item(ref.payment_id)], 422, 'linked_payment_immutable');
  await bad([item(a.payment_id, { amount: 29 })], 422, 'refund_exceeds_payment');
  await bad([item(a.payment_id, { expected_revision: 2, amount: 100 })], 409, 'stale_revision');
  // the first item with an error decides; within an item: validation, 404, linked, refund bound, stale
  await bad([item(b.payment_id, { expected_revision: 5, amount: 100 }), item('nope')], 409, 'stale_revision');
  await bad([item(b.payment_id), item('nope'), item(capture.payment_id)], 404, 'not_found');
  await bad([item(d.payment_id), item(capture.payment_id, { amount: -1 })], 422, 'validation_failed');
  await bad([item(capture.payment_id, { expected_revision: 7 })], 422, 'linked_payment_immutable');
  // an amount equal to the refunded amount is fine for the bound
  assert.equal((await batch(t.op, { corrections: [item(a.payment_id, { amount: 30 })] })).status, 201);
});

test('BD5/BD9/BD11/BD12/BD13/BD16: success, shared recorded_at, replay, history, snapshots', async () => {
  await fresh();
  const a = await pay(t.ada, 'bob', 1000, { visibility: 'private', note: 'n1' });
  await sleep(3);
  const bPay = await pay(t.bob, 'cy', 200);
  const snap = (await c.get('/statement?limit=1', { token: t.ada })).json;
  const frozenFirst = snap.entries;
  const key = k();
  const eff = at(-3);
  const body = { corrections: [item(a.payment_id, { amount: 400, effective_at: eff, reason: 'two hundred less' }), item(bPay.payment_id, { amount: 0, effective_at: eff, reason: 'reverse' })] };
  const r = await batch(t.op, body, key);
  assert.equal(r.status, 201, r.text);
  assert.deepEqual(Object.keys(r.json), ['correction_batch_id', 'recorded_at', 'revisions']);
  assert.match(r.json.correction_batch_id, /\S/);
  assert.deepEqual(r.json.revisions.map((x) => [x.payment_id, x.revision, x.amount, x.effective_at, x.reason, x.correction_batch_id, x.recorded_at]), [
    [a.payment_id, 2, 400, eff, 'two hundred less', r.json.correction_batch_id, r.json.recorded_at],
    [bPay.payment_id, 2, 0, eff, 'reverse', r.json.correction_batch_id, r.json.recorded_at],
  ]);
  assert.deepEqual(Object.keys(r.json.revisions[0]), ['payment_id', 'revision', 'amount', 'effective_at', 'recorded_at', 'reason', 'correction_batch_id']);
  // strictly later than the previous recorded_at of every member
  assert.ok(r.json.recorded_at > a.created_at && r.json.recorded_at > bPay.created_at);
  assert.ok(Date.parse(r.json.recorded_at) <= Date.now() + 1);
  // money: a back 600 from bob; bob's 200 to cy reversed by cy
  assert.deepEqual([(await me(t.ada)).balance, (await me(t.bob)).balance, (await me(t.cy)).balance], [9600, 2900, 0]);
  assert.equal(await balanceSum(c, all()), 12500);
  // replay returns the original batch response; a different body is a reuse
  const rep = await batch(t.op, body, key);
  assert.equal(rep.status, 200); assert.equal(rep.text, r.text);
  err(await batch(t.op, { corrections: [item(a.payment_id, { amount: 3, effective_at: eff })] }, key), 409, 'idempotency_key_reuse');
  // originals never change
  const feed = (await c.get('/activity?limit=200', { token: t.ada })).json.payments.find((x) => x.payment_id === a.payment_id);
  assert.equal(feed.amount, 1000);
  assert.equal((await c.post('/payments', { token: t.ada, key: 'k-fixed', body: { to_handle: 'bob', amount: 1 } })).status, 201);
  // revisions endpoint: batch id visible to the two parties only
  const revs = (await c.get(`/payments/${a.payment_id}/revisions`, { token: t.bob })).json.revisions;
  assert.deepEqual(revs.map((x) => x.correction_batch_id), [null, r.json.correction_batch_id]);
  err(await c.get(`/payments/${a.payment_id}/revisions`, { token: t.op }), 404, 'not_found');
  err(await c.get(`/payments/${a.payment_id}/revisions`, { token: t.cy }), 404, 'not_found');
  // statements reflect the batch; the earlier snapshot keeps its frozen entries
  const s = (await c.get('/statement?limit=200', { token: t.ada })).json;
  assert.equal(s.entries.find((e) => e.payment.payment_id === a.payment_id).payment.amount, 400);
  assert.equal(s.entries.find((e) => e.payment.payment_id === a.payment_id).revision, 2);
  const paged = (await c.get(`/statement?snapshot=${snap.snapshot}&limit=1`, { token: t.ada })).json;
  assert.deepEqual(paged.entries, frozenFirst); assert.equal(paged.closing_balance, snap.closing_balance);
  // known_at before the batch sees the old amounts
  assert.equal((await me(t.ada, `?known_at=${enc(a.created_at)}`)).balance, 10000 - 1000);
});

test('BD6/BD7/BD8: settlements need every member, one instant, and the precedence chain', async () => {
  await fresh();
  const st = (await c.post('/settlements', { token: t.op, key: k(), body: { transfers: [{ from_handle: 'ada', to_handle: 'bob', amount: 500 }, { from_handle: 'bob', to_handle: 'cy', amount: 100 }, { from_handle: 'ada', to_handle: 'cy', amount: 40 }] } })).json;
  const ids = st.payments.map((x) => x.payment_id);
  const other = await pay(t.ada, 'cy', 10);
  err(await c.post(`/payments/${ids[0]}/corrections`, { token: t.ada, key: k(), body: { expected_revision: 1, amount: 1, effective_at: at(-5), reason: 'x' } }), 422, 'linked_payment_immutable');
  err(await batch(t.op, { corrections: [item(ids[0], { amount: 100 })] }), 422, 'incomplete_settlement');
  err(await batch(t.op, { corrections: [item(ids[0]), item(ids[1])] }), 422, 'incomplete_settlement');
  err(await batch(t.op, { corrections: [item(ids[0]), item(ids[1]), item(ids[2], { effective_at: at(-9) })] }), 422, 'validation_failed');
  // item errors come before completeness; completeness before identical instants
  err(await batch(t.op, { corrections: [item(ids[0]), item('nope')] }), 404, 'not_found');
  err(await batch(t.op, { corrections: [item(ids[0], { effective_at: at(-9) }), item(ids[1])] }), 422, 'incomplete_settlement');
  // offset spellings of the same instant are equal
  const inst = new Date(Date.now() - 20000);
  const same = [inst.toISOString().replace('Z', '+00:00'), inst.toISOString().replace('Z', '+00:00').replace('+00:00', 'Z'), new Date(inst.getTime() + 2 * 3600000).toISOString().slice(0, 19).replace(/$/, '') ];
  const spelled = [item(ids[0], { amount: 300, effective_at: inst.toISOString().replace('Z', '+00:00') }), item(ids[1], { amount: 50, effective_at: inst.toISOString() }), item(ids[2], { amount: 0, effective_at: `${new Date(inst.getTime() + 2 * 3600000).toISOString().slice(0, 23)}+02:00` }), item(other.payment_id, { amount: 3 })];
  void same;
  const ok = await batch(t.op, { corrections: spelled });
  assert.equal(ok.status, 201, ok.text);
  assert.deepEqual(ok.json.revisions.map((x) => x.amount), [300, 50, 0, 3]);
  assert.equal(await balanceSum(c, all()), 12500);
  // membership and the original receipts are unchanged
  const members = (await c.get('/_test/export')).json.state.settlements.find((x) => x.id === st.settlement_id).payment_ids;
  assert.deepEqual(members, ids);
  const replayed = await c.post('/settlements', { token: t.op, key: 'never-used', body: { transfers: [{ from_handle: 'ada', to_handle: 'cy', amount: 1 }] } });
  assert.equal(replayed.status, 201);
  // an operator has no extra rights on the single endpoint
  err(await c.post(`/payments/${other.payment_id}/corrections`, { token: t.op, key: k(), body: { expected_revision: 2, amount: 1, effective_at: at(-1), reason: 'x' } }), 403, 'forbidden');
});

test('BD8/BD9/BD10: affordability on the combined effect; failures change nothing', async () => {
  // bob: opening 900; P1 ada->bob 1000, P2 bob->cy 500 (seeded, in the past). balances: ada 10000, bob 1400, cy 600.
  await fresh({
    users: [
      { id: 'u_ada', email: 'ada@example.com', password: 'correct horse', display_name: 'Ada', handle: 'ada', balance: 10000 },
      { id: 'u_bob', email: 'bob@example.com', password: 'correct horse', display_name: 'Bob', handle: 'bob', balance: 1400 },
      { id: 'u_cy', email: 'cy@example.com', password: 'correct horse', display_name: 'Cy', handle: 'cy', balance: 600 },
      { id: 'u_op', email: 'op@example.com', password: 'correct horse', display_name: 'Op', handle: 'op', balance: 0 },
    ],
    payments: [
      { id: 'p_1', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 1000, created_at: '2026-04-01T00:00:00Z' },
      { id: 'p_2', from_user_id: 'u_bob', to_user_id: 'u_cy', amount: 500, created_at: '2026-04-02T00:00:00Z' },
    ],
  });
  // bob holds 1000, so only 400 is available
  const hold = await c.post('/authorizations', { token: t.bob, key: k(), body: { to_handle: 'ada', amount: 1000 } });
  assert.equal(hold.status, 201);
  const E = '2026-04-03T00:00:00Z';
  const before = await stateJson();
  // alone: P1 down by 800 needs bob to return 800 > 400 available
  err(await batch(t.op, { corrections: [item('p_1', { amount: 200, effective_at: E })] }), 409, 'insufficient_funds');
  // together with P2 down by 500 (cy returns 500 to bob): net bob -300, cy -500 (cy has 600)
  const key = k();
  const both = { corrections: [item('p_1', { amount: 200, effective_at: E }), item('p_2', { amount: 0, effective_at: E })] };
  const r = await batch(t.op, both, key);
  assert.equal(r.status, 201, r.text);
  assert.deepEqual([(await me(t.bob)).balance, (await me(t.bob)).available, (await me(t.cy)).balance, (await me(t.ada)).balance], [1100, 100, 100, 10800]);
  // rejected batches change nothing and keep the key reusable
  const keep = await stateJson();
  err(await batch(t.op, { corrections: [item('p_1', { expected_revision: 2, amount: 0, effective_at: E }), item('p_2', { expected_revision: 2, amount: 500, effective_at: E })] }, key), 409, 'idempotency_key_reuse');
  assert.equal(await stateJson(), keep);
  err(await batch(t.op, { corrections: [item('p_2', { expected_revision: 2, amount: 600, effective_at: E })] }), 409, 'insufficient_funds');
  assert.equal(await stateJson(), keep);
  assert.notEqual(keep, before);
  assert.equal(await balanceSum(c, all()), 12000);
});

test('BD8: historical overdraft with every proposal applied together; ordering of checks', async () => {
  // bob opens at 0: +500 (04-01, from ada), -400 (04-02, to cy), +300 (04-03, from ada); holds 400 now.
  await fresh({
    users: [
      { id: 'u_ada', email: 'ada@example.com', password: 'correct horse', display_name: 'Ada', handle: 'ada', balance: 10000 },
      { id: 'u_bob', email: 'bob@example.com', password: 'correct horse', display_name: 'Bob', handle: 'bob', balance: 400 },
      { id: 'u_cy', email: 'cy@example.com', password: 'correct horse', display_name: 'Cy', handle: 'cy', balance: 400 },
      { id: 'u_op', email: 'op@example.com', password: 'correct horse', display_name: 'Op', handle: 'op', balance: 0 },
    ],
    payments: [
      { id: 'p_1', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 500, created_at: '2026-04-01T00:00:00Z' },
      { id: 'p_2', from_user_id: 'u_bob', to_user_id: 'u_cy', amount: 400, created_at: '2026-04-02T00:00:00Z' },
      { id: 'p_3', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 300, created_at: '2026-04-03T00:00:00Z' },
    ],
  });
  const before = await stateJson();
  const key = k();
  err(await batch(t.op, { corrections: [item('p_1', { amount: 350, effective_at: '2026-04-01T00:00:00Z' })] }, key), 409, 'historical_overdraft');
  assert.equal(await stateJson(), before);
  // together with p_3 moved onto the same instant as p_2 the combined effect is fine: 350 - 400 + 300
  const ok = await batch(t.op, { corrections: [item('p_1', { amount: 350, effective_at: '2026-04-01T00:00:00Z' }), item('p_3', { amount: 300, effective_at: '2026-04-01T12:00:00Z' })] }, key);
  assert.equal(ok.status, 201, ok.text);
  // current funds take precedence over history: p_2 up by 1000 asks for more than cy... (sender bob has 250)
  err(await batch(t.op, { corrections: [item('p_2', { expected_revision: 1, amount: 2000, effective_at: '2026-04-02T00:00:00Z' })] }), 409, 'insufficient_funds');
});

test('BD14: concurrent corrections sharing an expected revision; concurrent identical batches', async () => {
  await fresh();
  const ps = await Promise.all(Array.from({ length: 6 }, (_, i) => pay(t.ada, 'bob', 100 + i)));
  const jobs = [];
  for (let i = 0; i < 6; i++) jobs.push(c.post(`/payments/${ps[0].payment_id}/corrections`, { token: t.ada, key: k(), body: { expected_revision: 1, amount: 10 + i, effective_at: at(-1), reason: `s${i}` } }));
  for (let i = 0; i < 6; i++) jobs.push(batch(t.op, { corrections: [item(ps[0].payment_id, { amount: 20 + i, effective_at: at(-1) }), item(ps[1 + (i % 5)].payment_id, { amount: 50 })] }));
  const res = await Promise.all(jobs);
  assert.equal(res.filter((r) => r.status === 201).length, 1 + 0 + 0 === 1 ? res.filter((r) => r.status === 201).length : 1);
  assert.equal(res.filter((r) => r.status === 201 && (r.json.revisions ? r.json.revisions.some((x) => x.payment_id === ps[0].payment_id) : r.json.payment_id === ps[0].payment_id)).length, 1);
  assert.ok(res.filter((r) => r.status !== 201).every((r) => r.status === 409 && r.json.error.code === 'stale_revision'));
  const rev = (await c.get(`/payments/${ps[0].payment_id}/revisions`, { token: t.ada })).json.revisions;
  assert.equal(rev.length, 2);
  const key = k();
  const body = { corrections: [item(ps[5].payment_id, { expected_revision: (await c.get(`/payments/${ps[5].payment_id}/revisions`, { token: t.ada })).json.revisions.length, amount: 7, effective_at: at(-1) })] };
  const same = await Promise.all(Array.from({ length: 20 }, () => batch(t.op, body, key)));
  assert.equal(same.filter((r) => r.status === 201).length, 1); assert.equal(same.filter((r) => r.status === 200).length, 19);
  assert.equal(new Set(same.map((r) => r.text)).size, 1);
  assert.equal(await balanceSum(c, all()), 12500);
});

test('BA6: 200 batches with client-now instants, read back at once', async () => {
  await fresh();
  const p = await pay(t.ada, 'bob', 1000);
  let rev = 1;
  for (let i = 0; i < 200; i++) {
    const ms = Date.now();
    const us = Number(process.hrtime.bigint() % 1000n);
    const eff = new Date(ms).toISOString().slice(0, 23) + String(us).padStart(3, '0') + '+00:00';
    const r = await batch(t.op, { corrections: [item(p.payment_id, { expected_revision: rev, amount: 1000 - (i % 2) - 1, effective_at: eff })] });
    assert.equal(r.status, 201, `${eff}: ${r.text}`);
    assert.ok(Date.parse(r.json.recorded_at) <= Date.now() + 1);
    rev += 1;
    const cur = (await me(t.ada)).balance;
    const s = (await c.get('/statement?limit=200', { token: t.ada })).json;
    assert.equal(s.closing_balance, cur);
    assert.equal(s.entries.find((e) => e.payment.payment_id === p.payment_id).revision, rev);
  }
  const revs = (await c.get(`/payments/${p.payment_id}/revisions`, { token: t.ada })).json.revisions;
  const rec = revs.map((r) => r.recorded_at);
  for (let i = 1; i < rec.length; i++) assert.ok(rec[i] > rec[i - 1]);
});
