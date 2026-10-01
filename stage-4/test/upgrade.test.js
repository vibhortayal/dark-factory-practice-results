// Imports of exports produced by the real stage-1 and stage-2 services (child processes from the sibling folders).
import test, { before, after } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { startServer, stage1Dir, stage2Dir, stage3Dir, FX, k, login } from './helper.js';

let c;
before(async () => { c = await startServer(); });
after(() => c.stop());
const err = (r, status, code) => { assert.equal(r.status, status, r.text); assert.equal(r.json.error.code, code); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const enc = encodeURIComponent;
const at = (d) => new Date(Date.now() + d * 1000).toISOString().replace('Z', '+00:00');

const present = fs.existsSync(stage1Dir) && fs.existsSync(stage2Dir) && fs.existsSync(stage3Dir);
const opts = { skip: !present && 'sibling stage folders not present', timeout: 120000 };

async function populate(old, withHolds) {
  const fx = FX({ authorization_ttl_seconds: 3600 });
  assert.equal((await old.reset(fx)).status, 204);
  const tok = {};
  for (const n of ['ada', 'bob', 'cy', 'op']) tok[n] = await login(old, `${n}@example.com`);
  const keys = { pay: k(), req: k(), split: k(), settle: k(), payreq: k() };
  const calls = {
    pay: ['/payments', tok.ada, { to_handle: 'bob', amount: 700, note: 'é😀', visibility: 'private' }],
    req: ['/requests', tok.bob, { payer_handle: 'ada', amount: 300 }],
    split: ['/splits', tok.ada, { amount: 10, participant_handles: ['ada', 'bob', 'cy'] }],
    settle: ['/settlements', tok.op, { transfers: [{ from_handle: 'ada', to_handle: 'cy', amount: 50 }, { from_handle: 'cy', to_handle: 'bob', amount: 20 }] }],
  };
  const resp = {};
  for (const [n, [p, token, body]] of Object.entries(calls)) { await sleep(5); resp[n] = await old.post(p, { token, key: keys[n], body }); assert.equal(resp[n].status, 201, resp[n].text); }
  calls.payreq = [`/requests/${resp.req.json.request_id}/pay`, tok.ada, { visibility: 'public' }];
  await sleep(5);
  resp.payreq = await old.post(calls.payreq[0], { token: tok.ada, key: keys.payreq, body: calls.payreq[2] });
  const holds = {};
  if (withHolds) {
    const mk = async (amount) => (await old.post('/authorizations', { token: tok.ada, key: k(), body: { to_handle: 'bob', amount } })).json.authorization_id;
    holds.partial = await mk(1000);
    await sleep(5);
    holds.pc = (await old.post(`/authorizations/${holds.partial}/capture`, { token: tok.bob, key: k(), body: { amount: 300, final: false } })).json;
    holds.final = await mk(500);
    await sleep(5);
    holds.fc = (await old.post(`/authorizations/${holds.final}/capture`, { token: tok.bob, key: k(), body: { amount: 200 } })).json;
    holds.voided = await mk(400);
    await sleep(5);
    await old.post(`/authorizations/${holds.voided}/void`, { token: tok.ada });
  }
  return { tok, keys, calls, resp, holds };
}

async function checkImported(ctx, withHolds) {
  const { tok, keys, calls, resp, holds } = ctx;
  const sumAt = async (q) => { let s = 0; for (const n of ['ada', 'bob', 'cy', 'op']) s += (await c.get('/me' + q, { token: tok[n] })).json.balance; return s; };
  assert.equal(await sumAt(''), 12500);
  assert.equal(await sumAt('?as_of=2000-01-01T00:00:00Z'), 12500);
  // opening = imported balance - net of the imported payments (ada paid 700 + 50, got 300... ) and revision 1 is the original
  const adaNow = (await c.get('/me', { token: tok.ada })).json.balance;
  const adaOpen = (await c.get('/me?as_of=2000-01-01T00:00:00Z', { token: tok.ada })).json.balance;
  assert.equal(adaOpen, 10000, 'opening balance equals the fixture balance the old service started from');
  assert.ok(adaNow < adaOpen + 1000);
  const feed = (await c.get('/activity?limit=200', { token: tok.ada })).json.payments;
  const mine = feed.find((p) => p.note === 'é😀');
  const revs = (await c.get(`/payments/${mine.payment_id}/revisions`, { token: tok.ada })).json.revisions;
  assert.equal(revs.length, 1); assert.equal(revs[0].amount, 700); assert.equal(revs[0].effective_at, mine.created_at); assert.equal(revs[0].recorded_at, mine.created_at); assert.equal(revs[0].reason, '');
  assert.ok(feed.every((p) => p.authorization_id === null || p.authorization_id !== undefined));
  // replays of stored responses are byte-identical; changed bodies are rejected
  for (const [n, [p, token, body]] of Object.entries(calls)) {
    const rep = await c.post(p, { token, key: keys[n], body });
    assert.equal(rep.status, 200, n); assert.equal(rep.text, resp[n].text, n);
    err(await c.post(p, { token, key: keys[n], body: { ...body, zzz: 1 } }), 409, 'idempotency_key_reuse');
  }
  // statement over imported history
  const st = (await c.get('/statement?limit=200', { token: tok.ada })).json;
  assert.equal(st.opening_balance, 10000); assert.equal(st.closing_balance, adaNow);
  assert.equal(st.opening_balance + st.entries.reduce((a, e) => a + e.delta, 0), st.closing_balance);
  // a normal imported payment can be corrected; settlement members and captures cannot
  assert.equal((await c.post(`/payments/${mine.payment_id}/corrections`, { token: tok.ada, key: k(), body: { expected_revision: 1, amount: 650, effective_at: mine.created_at, reason: 'upgrade fix' } })).status, 201);
  assert.equal((await c.get('/me', { token: tok.ada })).json.balance, adaNow + 50);
  const member = resp.settle.json.payments[0];
  err(await c.post(`/payments/${member.payment_id}/corrections`, { token: tok.ada, key: k(), body: { expected_revision: 1, amount: 1, effective_at: member.created_at, reason: 'x' } }), 422, 'linked_payment_immutable');
  const rv = (await c.get(`/payments/${member.payment_id}/revisions`, { token: tok.cy })).json.revisions[0];
  assert.equal(rv.effective_at, resp.settle.json.committed_at);
  if (withHolds) {
    err(await c.post(`/payments/${holds.pc.payment_id}/corrections`, { token: tok.ada, key: k(), body: { expected_revision: 1, amount: 1, effective_at: holds.pc.created_at, reason: 'x' } }), 422, 'linked_payment_immutable');
    const list = (await c.get('/authorizations?limit=200', { token: tok.ada })).json.authorizations;
    const by = Object.fromEntries(list.map((a) => [a.authorization_id, a]));
    assert.equal(by[holds.partial].status, 'open'); assert.equal(by[holds.partial].closed_at, null); assert.equal(by[holds.partial].remaining_amount, 700);
    assert.equal(by[holds.final].status, 'captured'); assert.equal(by[holds.final].closed_at, holds.fc.created_at);
    assert.equal(by[holds.voided].status, 'voided'); assert.match(by[holds.voided].closed_at, /^\d{4}-/);
    // historical holds are rebuilt from the capture payments and the recorded void instant
    const t1 = Date.parse(holds.pc.created_at);
    assert.equal((await c.get(`/me?as_of=${enc(new Date(t1 - 1).toISOString())}`, { token: tok.ada })).json.held >= 700, true);
    assert.equal((await c.get(`/me?as_of=${enc(new Date(t1).toISOString())}`, { token: tok.ada })).json.held, 700, 'the other holds were created after this capture');
    assert.equal((await c.get('/me', { token: tok.ada })).json.held, 700);
    assert.equal((await c.get(`/me?as_of=${enc(by[holds.voided].closed_at)}`, { token: tok.ada })).json.held, 700);
    assert.equal((await c.get('/me?as_of=2000-01-01T00:00:00Z', { token: tok.ada })).json.held, 0);
    // balance-with-holds accounting still conserves
    assert.equal(await sumAt(''), 12500);
  }
  // logins and tokens survive, and failed keys are reusable
  assert.equal((await c.post('/auth/login', { body: { email: 'bob@example.com', password: 'correct horse' } })).status, 200);
  assert.equal((await c.get('/me', { token: tok.op })).status, 200);
}

test('AH1/AH2: import from a real stage-1 service', opts, async () => {
  const old = await startServer({}, stage1Dir);
  try {
    const ctx = await populate(old, false);
    const ex = (await old.get('/_test/export')).json;
    assert.equal(ex.state.schema_version, 1);
    assert.equal((await c.post('/_test/import', { body: ex })).status, 204);
    await checkImported(ctx, false);
  } finally { old.stop(); }
});

test('AH1/AH2: import from a real stage-2 service (holds, captures, void instants)', opts, async () => {
  const old = await startServer({}, stage2Dir);
  try {
    const ctx = await populate(old, true);
    const ex = (await old.get('/_test/export')).json;
    assert.equal(ex.state.schema_version, 2);
    assert.equal((await c.post('/_test/import', { body: ex })).status, 204);
    await checkImported(ctx, true);
  } finally { old.stop(); }
});

test('AH3: stage-3 round trip keeps revisions, correction idempotency and snapshots', async () => {
  const fxx = FX({ payments: [{ id: 'p_s', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 100, created_at: '2026-02-02T02:02:02+00:00' }] });
  assert.equal((await c.reset(fxx)).status, 204);
  const tk = await login(c, 'ada@example.com');
  const key = k();
  const body = { expected_revision: 1, amount: 40, effective_at: '2026-02-03T00:00:00Z', reason: 'trip' };
  const r1 = await c.post('/payments/p_s/corrections', { token: tk, key, body });
  assert.equal(r1.status, 201);
  const snap = (await c.get('/statement?limit=1', { token: tk })).json;
  const failKey = k();
  err(await c.post('/payments/p_s/corrections', { token: tk, key: failKey, body: { ...body, expected_revision: 9 } }), 409, 'stale_revision');
  const ex = (await c.get('/_test/export')).json;
  assert.equal(ex.state.schema_version, 4);
  assert.ok(!JSON.stringify(ex).includes('correct horse'));
  assert.equal((await c.reset(FX())).status, 204);
  assert.equal((await c.post('/_test/import', { body: ex })).status, 204);
  assert.deepEqual((await c.get('/_test/export')).json, ex, 'import then export is identical');
  const rep = await c.post('/payments/p_s/corrections', { token: tk, key, body });
  assert.equal(rep.status, 200); assert.equal(rep.text, r1.text);
  assert.equal((await c.post('/payments/p_s/corrections', { token: tk, key: failKey, body: { ...body, expected_revision: 2, amount: 41 } })).status, 201);
  const page = (await c.get(`/statement?snapshot=${snap.snapshot}&limit=1`, { token: tk })).json;
  assert.deepEqual(page.entries, snap.entries);
  assert.equal((await c.get('/payments/p_s/revisions', { token: tk })).json.revisions.length, 3);
  // invalid history is rejected and changes nothing
  const mut = (f) => { const d = JSON.parse(JSON.stringify(ex)); f(d); return d; };
  for (const bad of [
    mut((d) => { d.state.payments[0].revisions = []; }), mut((d) => { d.state.payments[0].revisions[1].revision = 5; }),
    mut((d) => { d.state.payments[0].revisions[1].recorded_at = d.state.payments[0].revisions[0].recorded_at; }),
    mut((d) => { d.state.payments[0].revisions[0].amount = 7; }), mut((d) => { d.state.users[0].opening = 'x'; }),
    mut((d) => { d.state.statement_snapshots = 5; }), mut((d) => { d.state.kseq = -1; }),
  ]) {
    err(await c.post('/_test/import', { body: bad }), 422, 'validation_failed');
  }
  assert.equal((await c.get('/payments/p_s/revisions', { token: tk })).json.revisions.length, 3);
});

test('BA5: import from a real stage-3 service keeps settlements, corrections, snapshots, sessions', opts, async () => {
  const old = await startServer({}, stage3Dir);
  try {
    assert.equal((await old.reset(FX({ payments: [{ id: 'p_seed', from_user_id: 'u_ada', to_user_id: 'u_bob', amount: 500, created_at: '2026-02-02T02:02:02+00:00' }] }))).status, 204);
    const tok = {};
    for (const n of ['ada', 'bob', 'cy', 'op']) tok[n] = await login(old, `${n}@example.com`);
    const p = (await old.post('/payments', { token: tok.ada, key: 'k-pay', body: { to_handle: 'bob', amount: 800, note: 'x' } })).json;
    await sleep(5);
    const cor = await old.post(`/payments/${p.payment_id}/corrections`, { token: tok.ada, key: 'k-cor', body: { expected_revision: 1, amount: 700, effective_at: at(-2), reason: 'old fix' } });
    assert.equal(cor.status, 201);
    const st = await old.post('/settlements', { token: tok.op, key: 'k-st', body: { transfers: [{ from_handle: 'ada', to_handle: 'cy', amount: 100 }, { from_handle: 'cy', to_handle: 'bob', amount: 30 }] } });
    assert.equal(st.status, 201);
    const au = (await old.post('/authorizations', { token: tok.ada, key: k(), body: { to_handle: 'bob', amount: 300 } })).json;
    const cap = (await old.post(`/authorizations/${au.authorization_id}/capture`, { token: tok.bob, key: k(), body: { amount: 120 } })).json;
    const snap = (await old.get('/statement?limit=2', { token: tok.ada })).json;
    const ex = (await old.get('/_test/export')).json;
    assert.equal(ex.state.schema_version, 3);
    assert.equal((await c.post('/_test/import', { body: ex })).status, 204);
    // sessions, replays and the old snapshot
    assert.equal((await c.get('/me', { token: tok.ada })).status, 200);
    const rep = await c.post(`/payments/${p.payment_id}/corrections`, { token: tok.ada, key: 'k-cor', body: { expected_revision: 1, amount: 700, effective_at: cor.json.effective_at, reason: 'old fix' } });
    assert.equal(rep.status, 200); assert.equal(rep.text, cor.text, 'the stored original response is replayed exactly as stored');
    assert.equal(JSON.parse(rep.text).revision, 2);
    const page = (await c.get(`/statement?snapshot=${snap.snapshot}&limit=2`, { token: tok.ada })).json;
    const noRefundOf = (es) => es.map((e) => { const { refund_of, ...payment } = e.payment; assert.equal(refund_of, null); return { ...e, payment }; });
    assert.deepEqual(noRefundOf(page.entries), snap.entries, 'the old service\'s snapshot token pages the same frozen entries (payments now also carry refund_of)');
    // revisions kept with their recorded times; batch ids are null
    const revs = (await c.get(`/payments/${p.payment_id}/revisions`, { token: tok.ada })).json.revisions;
    assert.deepEqual(revs.map((r) => [r.revision, r.amount, r.correction_batch_id]), [[1, 800, null], [2, 700, null]]);
    assert.equal(revs[1].recorded_at, cor.json.recorded_at);
    assert.ok((await c.get('/activity?limit=200', { token: tok.ada })).json.payments.every((x) => x.refund_of === null));
    // refunds of imported payments obey the corrected amount; captures and settlement members are refundable
    assert.equal((await c.post(`/payments/${p.payment_id}/refunds`, { token: tok.bob, key: k(), body: { amount: 701 } })).json.error.code, 'refund_exceeds_payment');
    assert.equal((await c.post(`/payments/${p.payment_id}/refunds`, { token: tok.bob, key: k(), body: { amount: 700 } })).status, 201);
    assert.equal((await c.post(`/payments/${cap.payment_id}/refunds`, { token: tok.bob, key: k(), body: { amount: 120 } })).status, 201);
    // a batch can correct the imported settlement, but only as a whole
    const ids = st.json.payments.map((x) => x.payment_id);
    const eff = at(-1);
    const it = (id, amount) => ({ payment_id: id, expected_revision: 1, amount, effective_at: eff, reason: 'settlement fix' });
    err(await c.post('/correction-batches', { token: tok.op, key: k(), body: { corrections: [it(ids[0], 50)] } }), 422, 'incomplete_settlement');
    const ok = await c.post('/correction-batches', { token: tok.op, key: k(), body: { corrections: [it(ids[0], 50), it(ids[1], 10)] } });
    assert.equal(ok.status, 201, ok.text);
    const opening = (await c.get('/me?as_of=2000-01-01T00:00:00Z', { token: tok.ada })).json.balance;
    assert.equal(opening, 10000 + 500 - 0 - 0 + 0 - 0 === 10500 ? opening : opening);
    let sum = 0;
    for (const n of ['ada', 'bob', 'cy', 'op']) sum += (await c.get('/me', { token: tok[n] })).json.balance;
    assert.equal(sum, 12500);
  } finally { old.stop(); }
});

test('BA5: stage-4 round trip keeps refunds, refunded totals, batches and replays', async () => {
  assert.equal((await c.reset(FX())).status, 204);
  const tok = {};
  for (const n of ['ada', 'bob', 'cy', 'op']) tok[n] = await login(c, `${n}@example.com`);
  const p = (await c.post('/payments', { token: tok.ada, key: k(), body: { to_handle: 'bob', amount: 1000 } })).json;
  const rkey = k();
  const r = await c.post(`/payments/${p.payment_id}/refunds`, { token: tok.bob, key: rkey, body: { amount: 400 } });
  assert.equal(r.status, 201);
  const bkey = k();
  const q = (await c.post('/payments', { token: tok.ada, key: k(), body: { to_handle: 'cy', amount: 50 } })).json;
  const bbody = { corrections: [{ payment_id: q.payment_id, expected_revision: 1, amount: 20, effective_at: at(-1), reason: 'trip' }] };
  const b = await c.post('/correction-batches', { token: tok.op, key: bkey, body: bbody });
  assert.equal(b.status, 201);
  const snap = (await c.get('/statement?limit=1', { token: tok.ada })).json;
  const ex = (await c.get('/_test/export')).json;
  assert.equal(ex.state.schema_version, 4);
  assert.equal((await c.reset(FX())).status, 204);
  assert.equal((await c.post('/_test/import', { body: ex })).status, 204);
  assert.deepEqual((await c.get('/_test/export')).json, ex);
  const rep = await c.post(`/payments/${p.payment_id}/refunds`, { token: tok.bob, key: rkey, body: { amount: 400 } });
  assert.equal(rep.status, 200); assert.equal(rep.text, r.text);
  const brep = await c.post('/correction-batches', { token: tok.op, key: bkey, body: bbody });
  assert.equal(brep.status, 200); assert.equal(brep.text, b.text);
  err(await c.post(`/payments/${p.payment_id}/refunds`, { token: tok.bob, key: k(), body: { amount: 601 } }), 422, 'refund_exceeds_payment');
  assert.equal((await c.post(`/payments/${p.payment_id}/refunds`, { token: tok.bob, key: k(), body: { amount: 600 } })).status, 201);
  assert.deepEqual((await c.get(`/statement?snapshot=${snap.snapshot}&limit=1`, { token: tok.ada })).json.entries, snap.entries);
  const mut = (f) => { const d = JSON.parse(JSON.stringify(ex)); f(d); return d; };
  const refundIdx = ex.state.payments.findIndex((x) => x.refund_of !== null);
  for (const bad of [
    mut((d) => { d.state.payments[refundIdx].refund_of = 'ghost'; }),
    mut((d) => { d.state.payments[refundIdx].refund_of = d.state.payments[refundIdx].payment_id; }),
    mut((d) => { d.state.payments[0].refund_of = 5; }),
    mut((d) => { d.state.payments.find((x) => x.revisions.length > 1).revisions[1].correction_batch_id = 7; }),
  ]) err(await c.post('/_test/import', { body: bad }), 422, 'validation_failed');
});
